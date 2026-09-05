from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from blaster.agent_pool import AgentPool
from blaster.amd import DETECTOR_VERSION, detect
from blaster.amd_calibration import AMDCalibration
from blaster.config import Settings
from blaster.diagnostics import error_detail
from blaster.dialing import DialingError, format_dial_number
from blaster.models import MENU, TERMINAL
from blaster.operations import Operations
from blaster.recordings import Recordings
from blaster.routing import TrunkRouter
from blaster.store import Store
from blaster.telemetry import CallTrace
from blaster.telephony.base import CallEnded, CallProgress, Leg, Telephony, first
from blaster.tts import close_speech, write_tone

log = logging.getLogger(__name__)


@dataclass
class Session:
    job: dict
    task: asyncio.Task | None = None
    customer: Leg | None = None
    agent: Leg | None = None
    state: str = "dialing"
    agent_requested_at: float | None = None
    trace: CallTrace | None = None
    trunk_id: str | None = None
    legs: list = field(default_factory=list)


class Engine:
    def __init__(self, settings: Settings, store: Store, telephony: Telephony, speech):
        self.settings, self.store = settings, store
        self.telephony, self.speech = telephony, speech
        self.sessions: dict[str, Session] = {}
        self.active_campaign: str | None = None
        self.scheduler: asyncio.Task | None = None
        self.next_dial = 0.0
        self.dial_lock = asyncio.Lock()
        self.wakeup = asyncio.Event()
        self.origination_pause: dict | None = None
        self.closing = False
        self.tone = settings.data_dir / "waiting.wav"
        self.work_dir = settings.data_dir / "audio"
        self.dialing_session = None
        self.telephony.on_leg = self._track_leg
        self.ops = Operations(store)
        self.router = TrunkRouter(settings, self.ops, telephony)
        self.recordings = Recordings(settings, self.ops, telephony)
        self.amd_calibration = AMDCalibration(settings, store)
        self.agent_pool = AgentPool(store, self.wakeup.set)

    def _track_leg(self, leg):
        session = self.dialing_session
        if session:
            setattr(session, leg.role, leg)
            session.legs.append(leg)
            leg.trunk_id = session.trunk_id
            session.trace.attach(leg)

    async def start(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        # Recover only our own ephemeral files, while holding the application lock.
        for child in self.work_dir.glob("call-*"):
            if child.is_dir():
                shutil.rmtree(child)
        self.store.recover()
        self.recordings.recover()
        self.amd_calibration.prune()
        write_tone(self.tone)
        await self.speech.start()
        await self.telephony.start()
        self.scheduler = asyncio.create_task(self._schedule())

    async def close(self) -> None:
        self.closing = True
        if self.active_campaign:
            self.store.set_campaign_status(self.active_campaign, "paused")
        if self.scheduler:
            self.scheduler.cancel()
            await asyncio.gather(self.scheduler, return_exceptions=True)
        tasks = [s.task for s in self.sessions.values() if s.task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.telephony.stop()
        await close_speech(self.speech)
        await self.agent_pool.close()

    def configure_concurrency(self, value: int) -> None:
        if not 1 <= value <= min(30, self.settings.trunk_channels // 2):
            raise ValueError("La concurrencia debe caber en la mitad de los canales de la troncal")
        self.settings.concurrency = value
        self.wakeup.set()

    def ensure_startable(self, cid: str | None = None) -> None:
        if self.router.reloading:
            raise ValueError("El motor está aplicando la configuración")
        if not self.telephony.available or not any(
            self.router.ready(t) for t in self.router.profiles
        ):
            raise ValueError("La troncal no está lista. Revisa su registro antes de iniciar")
        if self.active_campaign and self.active_campaign != cid:
            raise ValueError("Termina o detén la campaña actual antes de iniciar otra")

    def validate_destinations(self, agents, contacts) -> None:
        if self.settings.mode == "sip":
            for trunk in self.router.profiles.values():
                if trunk.enabled:
                    for number in (*agents, *contacts):
                        format_dial_number(number, trunk.sip.dial_format)

    def start_campaign(self, cid: str) -> None:
        campaign = self.store.campaign(cid)
        if campaign["mode"] != self.settings.mode:
            raise ValueError(
                "Crea una campaña en este modo; las campañas de simulación están aisladas"
            )
        self.ensure_startable(cid)
        if campaign["status"] == "running":
            return
        missing = self.store.missing_identifiers(cid)
        if missing:
            raise ValueError(
                f"La campaña tiene {missing} contacto(s) sin Credito o Telefono. "
                "Crea una campaña nueva con ambos identificadores"
            )
        self.store.retries.reconcile(cid)
        if not self.store.has_queued(cid):
            raise ValueError("Esta campaña ya no tiene contactos pendientes")
        self.validate_destinations(campaign["agent_numbers"], self.store.queued_numbers(cid))
        self.store.set_campaign_status(cid, "running")
        self.active_campaign = cid
        self.wakeup.set()

    def pause_campaign(self, cid: str) -> None:
        self.store.campaign(cid)
        if self.active_campaign != cid:
            raise ValueError("Esta campaña no está en ejecución")
        self.store.set_campaign_status(cid, "paused")

    async def stop_campaign(self, cid: str) -> None:
        self.store.campaign(cid)
        self.store.set_campaign_status(cid, "stopped")
        self.store.cancel_queued(cid)
        with self.store.db:
            self.store.db.execute(
                "UPDATE campaign_schedules SET state='cancelled' "
                "WHERE campaign_id=? AND state='pending'",
                (cid,),
            )
        tasks = [s.task for s in self.sessions.values() if s.job["campaign_id"] == cid]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.active_campaign == cid:
            self.active_campaign = None
        self.wakeup.set()

    def simulate(self, jid: str, action: str) -> None:
        if self.settings.mode != "simulation":
            raise ValueError("El teclado de prueba sólo existe en modo simulación")
        session = self.sessions.get(jid)
        if not session or not session.customer:
            raise ValueError("La llamada ya no está activa")
        if action == "hangup":
            session.customer.end_by("customer", "bye", "simulation")
            session.customer.emit("closed", code=200)
            session.customer.closed.set()
        elif action in {"1", "2"} and session.state in {"playing", "menu"}:
            session.customer.receive_digit(action)
        elif action == "agent_hangup" and session.agent:
            session.agent.end_by("agent", "bye", "simulation")
            session.agent.emit("closed", code=200)
            session.agent.closed.set()
        else:
            raise ValueError("Espera a que comience el mensaje para usar el teclado")

    async def _schedule(self) -> None:
        while True:
            self.wakeup.clear()
            cid = self.active_campaign
            campaign = self.store.campaign(cid) if cid else None
            running = bool(campaign and campaign["status"] == "running")
            queued = bool(running and self.store.has_queued(cid))
            if running and not queued and not self.sessions:
                self.store.set_campaign_status(cid, "completed")
                self.active_campaign = None
                self.origination_pause = None
                continue
            availability = (
                self.agent_pool.availability(campaign["agent_numbers"])
                if running
                else None
            )
            if not running or not queued:
                self.origination_pause = None
            elif not availability["free"]:
                self._pause_for_agent_capacity(cid, availability)
            else:
                self._resume_after_agent_capacity(availability)
            if running and queued and self.telephony.available and availability["free"]:
                if len(self.sessions) < self.settings.concurrency:
                    self.store.retries.reconcile(cid)
                    job = self.store.next_queued(cid)
                    tid = self.router.reserve(job["id"]) if job else None
                    if job and tid:
                        session = Session(job, trunk_id=tid)
                        session.trace = CallTrace(self.store, job["id"], self.settings.amd.enabled)
                        self.sessions[job["id"]] = session
                        self._state(session, "dialing", "Preparando llamada")
                        if job["attempt_number"] > 1:
                            self.ops.audit({}, "call.retry_started", job["id"], {
                                "campaign_id": cid, "contact_id": job["contact_id"],
                                "credit_id": job["credit_id"], "phone": job["phone"],
                                "attempt_number": job["attempt_number"],
                                "previous_job_id": job["retry_of"],
                            })
                        session.task = asyncio.create_task(self._run_session(session))
                        continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.wakeup.wait(), 0.25)

    def _pause_for_agent_capacity(self, cid: str, availability: dict) -> None:
        if self.origination_pause and self.origination_pause["campaign_id"] == cid:
            return
        self.origination_pause = {
            "campaign_id": cid,
            "reason": "agent_pool_full",
            "busy": availability["busy"],
            "total": availability["total"],
        }
        self.ops.audit({}, "campaign.capacity_paused", cid, self.origination_pause)
        log.info(
            "Originación pausada: pool de transferencia ocupado (%s/%s); campaña=%s",
            availability["busy"],
            availability["total"],
            cid,
        )

    def _resume_after_agent_capacity(self, availability: dict | None) -> None:
        previous = self.origination_pause
        if not previous:
            return
        detail = {
            "reason": previous["reason"],
            "free": len(availability["free"]) if availability else 0,
            "total": availability["total"] if availability else previous["total"],
        }
        self.origination_pause = None
        self.ops.audit({}, "campaign.capacity_resumed", previous["campaign_id"], detail)
        log.info(
            "Originación reanudada: hay %s teléfono(s) de transferencia libre(s); campaña=%s",
            detail["free"],
            previous["campaign_id"],
        )

    def _state(self, session: Session, state: str, detail: str = "") -> None:
        if session.trace and state in TERMINAL:
            closed = session.customer and session.customer.closed.is_set()
            if state in {"cancelled", "interrupted"}:
                actor = "system" if self.closing else "operator"
                reason = "shutdown" if self.closing else "campaign_stopped"
            elif closed or (session.state == "bridged" and session.agent.closed.is_set()):
                actor, reason = "unknown", "disconnected"
            else:
                actor, reason = "system", state
            session.trace.terminate(
                actor,
                reason,
                "local_policy" if actor != "unknown" else "disconnect_without_initiator",
            )
        session.state = state
        self.store.transition(session.job["id"], state, detail)

    async def _dial(self, number: str, role: str, session: Session | None = None) -> Leg:
        # Applies CPS to both customer and agent legs.
        async with self.dial_lock:
            loop = asyncio.get_running_loop()
            await asyncio.sleep(max(0, self.next_dial - loop.time()))
            self.next_dial = loop.time() + 1 / self.settings.calls_per_second
            self.dialing_session = session
            try:
                if session:
                    await self.router.pace(session.trunk_id)
                    session.trace.event("route_selected", trunk_id=session.trunk_id, role=role)
                    return await self.telephony.dial_on(number, role, session.trunk_id)
                return await self.telephony.dial(number, role)
            finally:
                self.dialing_session = None

    async def _run_session(self, session: Session) -> None:
        directory = Path(tempfile.mkdtemp(prefix="call-", dir=self.work_dir))
        try:
            async with asyncio.timeout(self.settings.max_call_seconds):
                await self._flow(session, directory)
        except asyncio.CancelledError:
            self._state(
                session,
                "interrupted" if self.closing else "cancelled",
                "Aplicación cerrada" if self.closing else "Campaña detenida",
            )
            raise
        except CallEnded as error:
            if session.customer and session.customer.ready.is_set():
                if session.state == "detecting":
                    self._state(
                        session, "amd_unknown", "La llamada terminó durante el análisis AMD"
                    )
                else:
                    self._state(session, "completed", "La persona terminó la llamada")
            else:
                status = "busy" if error.code in {486, 600} else "failed"
                if error.code in {500, 502, 503, 504}:
                    status = "temporary_error"
                elif error.code in {408, 480}:
                    status = "no_answer"
                self._state(session, status, error.detail)
        except DialingError as error:
            self._state(session, "failed", str(error))
        except TimeoutError:
            self._state(session, "failed", "Se alcanzó el tiempo máximo de la llamada")
        except Exception as error:
            stage = {
                "dialing": "iniciar la llamada",
                "detecting": "analizar quién contestó",
                "synthesizing": "generar la voz y reproducir la espera",
                "playing": "reproducir el mensaje",
                "agent_dialing": "conectar con el agente",
                "agent_waiting": "esperar un teléfono de transferencia disponible",
                "bridged": "mantener la conversación",
            }.get(session.state, "procesar la llamada")
            cause = error_detail(error)
            for trunk in self.router.profiles.values():
                if trunk.sip.password:
                    cause = cause.replace(trunk.sip.password, "[oculto]")
            detail = f"Error al {stage}: {cause}"
            log.error("Fallo de llamada %s: %s", session.job["id"], detail)
            self._state(session, "failed", detail)
        finally:
            cleanup = asyncio.create_task(self._cleanup_session(session, directory))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    async def _cleanup_session(self, session, directory):
        try:
            for leg in session.legs:
                if not leg.closed.is_set():
                    leg.end_by("system", "session_cleanup", "local_command")
            try:
                await asyncio.gather(
                    *(leg.hangup() for leg in session.legs), return_exceptions=True
                )
            finally:
                self.agent_pool.release_after_close(session.job["id"], session.agent)
            await self.recordings.finish(session)
            if session.trace:
                session.trace.finish()
                self.store.retries.plan(session.job["id"])
        finally:
            self.router.release(session.job["id"])
            shutil.rmtree(directory, ignore_errors=True)
            self.sessions.pop(session.job["id"], None)
            self.wakeup.set()

    async def _speech_while_connected(self, customer: Leg, text: str, path: Path) -> Path:
        tone = asyncio.create_task(customer.play(self.tone, loop=True))
        try:
            async with asyncio.timeout(self.settings.tts_timeout):
                index, result = await first(
                    customer.closed.wait(),
                    self.speech.synthesize(text, path),
                    asyncio.shield(tone),
                )
            if index == 0:
                raise CallEnded(customer.code)
            if index == 2:
                raise RuntimeError("El audio de espera se detuvo")
            return result
        finally:
            tone.cancel()
            await asyncio.gather(tone, return_exceptions=True)

    async def _flow(self, session: Session, directory: Path) -> None:
        attempted = set()
        while True:
            attempted.add(session.trunk_id)
            session.customer = customer = await self._dial(
                session.job["phone"], "customer", session
            )
            self._state(session, "dialing", f"Marcando {customer.number}")
            try:
                await customer.wait_ready(self.settings.ring_timeout)
                break
            except TimeoutError:
                self._state(session, "no_answer", "No contestó dentro del tiempo de timbrado")
                return
            except CallEnded as error:
                self.router.failed(
                    session.trunk_id, error.code, getattr(customer, "retry_after", 0)
                )
                if error.code not in {408, 502, 503, 504} or "answered" in customer._milestones:
                    raise
                await customer.hangup()
                self.router.release(session.job["id"])
                replacement = self.router.reserve(session.job["id"], attempted)
                if replacement is None:
                    raise
                session.trace.event(
                    "route_failover", previous=session.trunk_id, next=replacement, code=error.code
                )
                with self.store.db:
                    self.store.db.execute(
                        "UPDATE call_legs SET role=? WHERE id=?",
                        ("customer_attempt_" + customer.id, customer.id),
                    )
                session.trace.end = None
                self.store.update_call(
                    session.job["id"], end_actor="unknown", end_reason=None, end_evidence=None
                )
                session.trunk_id = replacement
        if self.settings.amd.enabled:
            self._state(session, "detecting", "Analizando el saludo antes de reproducir el mensaje")
            amd_settings = self.settings.amd.model_copy(deep=True)
            calibration_pcm = (
                bytearray() if amd_settings.calibration_capture_enabled else None
            )
            result = await detect(customer, amd_settings, capture_pcm=calibration_pcm)
            self.store.update_call(
                session.job["id"],
                amd_verdict=result.verdict,
                amd_reason=result.reason,
                amd_elapsed_ms=result.elapsed_ms,
                amd_audio_ms=result.audio_ms,
                amd_voiced_ms=result.voiced_ms,
                amd_words=result.words,
            )
            session.trace.event(
                "amd", verdict=result.verdict, reason=result.reason, elapsed_ms=result.elapsed_ms,
                audio_ms=result.audio_ms, voiced_ms=result.voiced_ms, words=result.words,
                detector_version=DETECTOR_VERSION, parameters=amd_settings.model_dump(),
            )
            if calibration_pcm:
                sample_id = self.amd_calibration.save(
                    session.job,
                    result,
                    bytes(calibration_pcm),
                    DETECTOR_VERSION,
                    amd_settings.model_dump(),
                )
                if sample_id:
                    session.trace.event(
                        "amd_calibration_saved",
                        sample_id=sample_id,
                        duration_ms=len(calibration_pcm) * 1000 // (8000 * 2),
                    )
            log.info("%s; trabajo=%s", result.detail, session.job["id"])
            if result.verdict == "machine":
                self._state(
                    session, "machine", f"{result.detail}; se cuelga sin reproducir el mensaje"
                )
                return
            if result.verdict == "unknown" and amd_settings.unknown_action == "hangup":
                self._state(session, "amd_unknown", f"{result.detail}; se cuelga por configuración")
                return
            if result.verdict == "human":
                await self.recordings.start(session, "amd_human_probable")
            elif result.verdict == "unknown":
                await self.recordings.start(session, "amd_inconclusive_continued")
            suffix = "; se continúa por configuración" if result.verdict == "unknown" else ""
            self._state(session, "detecting", result.detail + suffix)
        self._state(session, "synthesizing", "Generando voz personalizada en este equipo")
        tts_started = time.monotonic()
        message = await self._speech_while_connected(
            customer,
            f"{session.job['message']}\n{MENU}",
            directory / "message.wav",
        )
        self.store.update_call(session.job["id"], tts_ms=(time.monotonic() - tts_started) * 1000)
        session.trace.event("tts_ready")
        repeats, no_inputs = 0, 0
        while True:
            choice = await self._choice(session, message)
            if choice is None:
                no_inputs += 1
                if no_inputs >= 2:
                    self._state(session, "no_input", "No seleccionó una opción")
                    return
            elif choice == "1":
                repeats += 1
                self.store.update_call(
                    session.job["id"], replays=min(repeats, self.settings.max_repeats)
                )
                session.trace.event("repeat_requested", actor="customer")
                if repeats > self.settings.max_repeats:
                    self._state(session, "completed", "Se alcanzó el límite de repeticiones")
                    return
            elif choice == "2":
                await self._agent(session, directory)
                return

    async def _choice(self, session: Session, message: Path) -> str | None:
        customer = session.customer
        if customer.closed.is_set():
            raise CallEnded(customer.code)
        # Do not consume digits entered while a voice was still being generated.
        while not customer.digits.empty():
            customer.digits.get_nowait()
        self._state(session, "playing", "Reproduciendo mensaje y opciones")
        self.store.message_time(session.job["id"])
        session.trace.event("message_started")
        play = asyncio.create_task(customer.play(message))
        deadline = None
        try:
            while True:
                waits = [customer.closed.wait(), customer.digits.get()]
                if deadline is None:
                    waits.append(asyncio.shield(play))
                else:
                    waits.append(
                        asyncio.sleep(max(0, deadline - asyncio.get_running_loop().time()))
                    )
                index, result = await first(*waits)
                if index == 0:
                    raise CallEnded(customer.code)
                if index == 1:
                    if result in {"1", "2"}:
                        await self.recordings.start(session, "dtmf_interaction")
                        if result == "2":
                            session.agent_requested_at = time.monotonic()
                            event = session.trace.event(
                                "transfer_requested", actor="customer", evidence="dtmf_2"
                            )
                            self.store.update_call(
                                session.job["id"],
                                transfer_requested_at=event.at,
                                transfer_actor="customer",
                            )
                        return result
                elif deadline is None:
                    self.store.message_time(session.job["id"], completed=True)
                    session.trace.event("message_completed")
                    self._state(session, "menu", "Esperando opción: 1 repetir · 2 agente")
                    deadline = asyncio.get_running_loop().time() + self.settings.choice_timeout
                else:
                    return None
                if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                    return None
        finally:
            play.cancel()
            await asyncio.gather(play, return_exceptions=True)

    async def _agent(self, session: Session, directory: Path) -> None:
        customer = session.customer
        campaign = self.store.campaign(session.job["campaign_id"])
        if session.agent_requested_at is None:
            session.agent_requested_at = time.monotonic()
        self._state(session, "agent_dialing", "Opción 2 recibida; preparando llamada al agente")
        tone = asyncio.create_task(customer.play(self.tone, loop=True))
        pool_timeout = False

        def waiting():
            self._state(
                session, "agent_waiting", "Todos los teléfonos están ocupados; esperando turno"
            )
            session.trace.event("agent_pool_waiting", timeout_seconds=campaign["agent_pool_wait"])

        async def dial_and_answer():
            nonlocal pool_timeout
            if customer.closed.is_set():
                raise CallEnded(customer.code)
            started_wait = time.monotonic()
            dial_format = self.router.profiles[session.trunk_id].sip.dial_format
            numbers = list(
                dict.fromkeys(format_dial_number(n, dial_format) for n in campaign["agent_numbers"])
            )
            try:
                number = await self.agent_pool.acquire(
                    session.job["id"],
                    campaign["id"],
                    numbers,
                    campaign["agent_strategy"],
                    campaign["agent_pool_wait"],
                    waiting,
                    aliases={
                        format_dial_number(n, dial_format): n for n in campaign["agent_numbers"]
                    },
                )
            finally:
                waited = time.monotonic() - started_wait
                self.store.update_call(
                    session.job["id"],
                    agent_pool_wait_seconds=waited,
                    agent_strategy=campaign["agent_strategy"],
                )
            if number is None:
                pool_timeout = True
                session.trace.event("agent_pool_timeout", waited_seconds=waited)
                raise TimeoutError
            self.store.update_call(session.job["id"], agent_selected_number=number)
            session.trace.event(
                "agent_selected",
                number=number,
                strategy=campaign["agent_strategy"],
                waited_seconds=waited,
            )
            self._state(session, "agent_dialing", f"Marcando teléfono de transferencia {number}")
            if customer.closed.is_set():
                raise CallEnded(customer.code)
            started = time.monotonic()
            session.agent = await self._dial(number, "agent", session)
            elapsed = time.monotonic() - session.agent_requested_at
            log.info(
                "Marcación del agente solicitada en %.3f s; cola y envío %.3f s; "
                "trabajo=%s; cliente=%s; agente=%s",
                elapsed,
                time.monotonic() - started,
                session.job["id"],
                customer.id,
                session.agent.id,
            )

            async def monitor_progress():
                while True:
                    progress = await session.agent.progress.get()
                    self._agent_progress(session, progress)

            monitor = asyncio.create_task(monitor_progress())
            try:
                await session.agent.wait_ready(self.settings.agent_timeout)
            finally:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
                while not session.agent.progress.empty():
                    self._agent_progress(session, session.agent.progress.get_nowait())

        unavailable = False
        try:
            try:
                index, _ = await first(
                    customer.closed.wait(), dial_and_answer(), asyncio.shield(tone)
                )
                if index == 0:
                    raise CallEnded(customer.code)
                if index == 2:
                    raise RuntimeError("El audio de espera se detuvo")
            except (TimeoutError, CallEnded):
                if customer.closed.is_set():
                    raise CallEnded(customer.code) from None
                unavailable = True
        finally:
            tone.cancel()
            await asyncio.gather(tone, return_exceptions=True)
        if unavailable:
            if session.agent:
                if not session.agent.closed.is_set():
                    session.agent.end_by("system", "agent_timeout", "local_policy")
                await session.agent.hangup()
                self.agent_pool.release_after_close(session.job["id"], session.agent)
            self._state(session, "synthesizing", "Preparando aviso de agente no disponible")
            path = await self._speech_while_connected(
                customer,
                "En este momento no hay un agente disponible. Gracias por tu tiempo.",
                directory / "unavailable.wav",
            )
            await first(customer.closed.wait(), customer.play(path))
            self._state(
                session,
                "failed",
                "Se agotó la espera del pool de agentes"
                if pool_timeout
                else "El agente estaba ocupado o no contestó",
            )
            return
        if customer.closed.is_set():
            raise CallEnded(customer.code)
        await self.telephony.bridge(customer, session.agent)
        session.trace.bridge()
        self._state(session, "bridged", "Persona y agente conectados")
        await first(customer.closed.wait(), session.agent.closed.wait())
        self._state(session, "completed", "Conversación con agente finalizada")

    def _agent_progress(self, session: Session, progress: CallProgress) -> None:
        elapsed = max(0, progress.timestamp - session.agent_requested_at)
        if progress.event == "invite_sent":
            detail = f"INVITE del agente enviado a los {elapsed:.3f} s; esperando a la troncal"
        else:
            status = {
                100: "La troncal está procesando la llamada al agente",
                180: "La troncal indica que el agente está timbrando",
                183: "La troncal informa progreso de la llamada al agente",
                200: "El agente contestó",
                401: "La troncal solicita autenticación",
                407: "El proxy solicita autenticación",
            }.get(progress.code, "Respuesta de la troncal para el agente")
            detail = f"{status}: SIP {progress.code}, a los {elapsed:.3f} s"
        self._state(session, "agent_dialing", detail)
        log.info("%s; trabajo=%s", detail, session.job["id"])

    def snapshot(self) -> dict:
        campaign = self.store.campaign(self.active_campaign) if self.active_campaign else None
        availability = self.agent_pool.availability(campaign["agent_numbers"]) if campaign else {
            "total": 0, "busy": 0, "free": []
        }
        return {
            "trunks": self.router.snapshot(),
            "mode": self.settings.mode,
            "trunk_status": self.telephony.status,
            "ready": self.telephony.available,
            "automation_enabled": self.settings.automation.enabled,
            "amd_enabled": self.settings.amd.enabled,
            "amd_unknown_action": self.settings.amd.unknown_action,
            "concurrency": self.settings.concurrency,
            "trunk_channels": self.settings.trunk_channels,
            "active_sessions": len(self.sessions),
            "channels_in_use": sum(
                int(leg is not None and not leg.closed.is_set())
                for session in self.sessions.values()
                for leg in (session.customer, session.agent)
            ),
            "reserved_channels": len(self.sessions) * 2,
            "active_campaign": self.active_campaign,
            "origination_paused": self.origination_pause is not None,
            "origination_pause_reason": (
                self.origination_pause["reason"] if self.origination_pause else None
            ),
            "sessions": [{"id": jid, "state": s.state} for jid, s in self.sessions.items()],
            "agent_pool": {
                "total": availability["total"],
                "busy": availability["busy"],
                "free": len(availability["free"]),
                "waiting": list(self.agent_pool.pending),
                "reservations": [
                    {
                        "number": n,
                        "configured_number": self.agent_pool.aliases.get(n, n),
                        "job_id": jid,
                        "state": self.sessions[jid].state if jid in self.sessions else "closing",
                    }
                    for n, jid in self.agent_pool.busy.items()
                ],
            },
        }
