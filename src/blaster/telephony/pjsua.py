"""PJSUA2 endpoint embedded in Python; all native objects stay on one owner thread.

Callbacks only enqueue asyncio notifications. Audio flows in PJMEDIA, never through
Python sample-by-sample. No microphone or speaker is opened.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import queue
import re
import struct
import threading
import time
from pathlib import Path
from uuid import uuid4

from blaster.config import Settings
from blaster.diagnostics import error_detail
from blaster.dialing import format_dial_number
from blaster.telemetry import CallEvent
from blaster.telephony.base import AudioStream, CallEnded, CallProgress, Leg, Telephony

log = logging.getLogger(__name__)


class PJSUALeg(Leg):
    def __init__(self, number: str, role: str, backend: PJSUATelephony):
        super().__init__(number, role)
        self.backend = backend
        self.playbacks: dict[str, asyncio.Future] = {}

    @contextlib.asynccontextmanager
    async def capture_audio(self):
        stream = AudioStream()
        try:
            await self.backend.command("start_capture", self.id, stream)
            yield stream
        finally:
            stream.stop()
            await self.backend.command("stop_capture", self.id, stream)

    async def play(self, path: Path, *, loop: bool = False) -> None:
        if self.closed.is_set():
            raise CallEnded(self.code, self.reason)
        token = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.playbacks[token] = future
        try:
            await self.backend.command("play", self.id, str(path), token, loop)
            await future
        finally:
            self.playbacks.pop(token, None)
            await self.backend.command("stop_play", self.id, token)

    async def hangup(self) -> None:
        if not self.closed.is_set():
            self.end_by("system", "cleanup", "local_command")
            await self.backend.command("hangup", self.id)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.closed.wait(), 5)
        # Retain native objects until DISCONNECTED; their lifetime is independent.
        self.backend.legs.pop(self.id, None)


class PJSUATelephony(Telephony):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.legs: dict[str, PJSUALeg] = {}
        self.commands: queue.Queue = queue.Queue()
        self.stopping = threading.Event()
        self.trunk_states = {}
        self.recording_paths = {}
        self.thread: threading.Thread | None = None

    async def start(self) -> None:
        self.stopping.clear()
        self.trunk_states = {}
        self.loop = asyncio.get_running_loop()
        self.started = self.loop.create_future()
        self.thread = threading.Thread(target=self._run, name="sip-owner", daemon=True)
        self.thread.start()
        try:
            await asyncio.wait_for(asyncio.shield(self.started), 20)
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        self.stopping.set()
        if self.thread:
            await asyncio.to_thread(self.thread.join, 10)
        self.available = False

    async def command(self, name: str, *args):
        if self.stopping.is_set():
            if name in {"hangup", "stop_play", "stop_capture", "stop_recording"}:
                return None
            raise RuntimeError("El motor SIP está detenido")
        future = self.loop.create_future()
        self.commands.put((name, args, future))
        return await future

    async def dial(self, number: str, role: str, trunk_id: str | None = None) -> PJSUALeg:
        if not self.available:
            raise RuntimeError("La troncal SIP no está disponible")
        profiles = {t.id: t for t in self.settings.trunk_profiles()}
        trunk_id = trunk_id or next(iter(profiles))
        if not self.trunk_states.get(trunk_id, {}).get("available"):
            raise RuntimeError("La troncal seleccionada no está disponible")
        number = format_dial_number(number, profiles[trunk_id].sip.dial_format)
        leg = PJSUALeg(number, role, self)
        leg.trunk_id = trunk_id
        self.legs[leg.id] = leg
        self.track(leg)
        pending = asyncio.create_task(self.command("dial", leg.id, leg.number, trunk_id))
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await pending
                await leg.hangup()
            self.legs.pop(leg.id, None)
            raise
        except Exception:
            self.legs.pop(leg.id, None)
            raise
        return leg

    async def dial_on(self, number, role, trunk_id):
        return await self.dial(number, role, trunk_id)

    async def bridge(self, customer: Leg, agent: Leg) -> None:
        await self.command("bridge", customer.id, agent.id)

    def _settle(self, future: asyncio.Future, result=None, error: Exception | None = None):
        if not future.done():
            if error is None:
                future.set_result(result)
            else:
                future.set_exception(error)

    def _event(self, lid: str, event: str, value=None) -> None:
        leg = self.legs.get(lid)
        if leg is None:
            return
        if event == "ready":
            leg.emit("media_ready")
            leg.ready.set()
        elif event == "closed":
            leg.code, leg.reason = value
            leg.emit("closed", code=leg.code, reason=leg.reason)
            leg.closed.set()
        elif event == "trace":
            if value.kind == "termination":
                if leg.termination is not None:
                    return
                actor = value.data["actor"]
                if actor == "remote":
                    value.data["actor"] = leg.role
                leg.termination = (
                    value.data["actor"],
                    value.data["reason"],
                    value.data["evidence"],
                )
            if value.kind == "response":
                leg.retry_after = value.data.get("retry_after", 0)
            leg.record(value)
        elif event == "digit":
            leg.receive_digit(value)
        elif event == "progress":
            if leg.progress.full():
                leg.progress.get_nowait()
            leg.progress.put_nowait(value)
        elif event == "eof":
            future = leg.playbacks.get(value)
            if future and not future.done():
                future.set_result(None)

    def _notify(self, lid: str, event: str, value=None) -> None:
        self.loop.call_soon_threadsafe(self._event, lid, event, value)

    def _registration(self, available: bool, code: int, trunk_id="default") -> None:
        self.trunk_states[trunk_id] = {
            "available": available,
            "code": code,
            "status": "Conectada" if available else f"Registro SIP: {code}",
        }
        self.available = any(t["available"] for t in self.trunk_states.values())
        self.status = (
            f"{sum(t['available'] for t in self.trunk_states.values())} troncales listas"
            if self.available
            else f"Registro SIP: {code}"
        )

    async def start_recording(self, customer, path):
        await self.command("start_recording", customer.id, str(path))
        self.recording_paths[customer.id] = path

    async def stop_recording(self, customer):
        await self.command("stop_recording", customer.id)
        path = self.recording_paths.pop(customer.id, None)
        if path:
            await asyncio.to_thread(self._wait_recording_closed, path)

    @staticmethod
    def _wait_recording_closed(path):
        # PJMEDIA removes conference ports asynchronously. The native WAV writer
        # fills both RIFF and data lengths only after its last reference is released.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with path.open("rb") as file:
                    header = file.read(44)
                size = path.stat().st_size
                if (
                    len(header) == 44
                    and header[:4] == b"RIFF"
                    and header[8:12] == b"WAVE"
                    and header[36:40] == b"data"
                    and struct.unpack_from("<I", header, 4)[0] + 8 == size
                    and struct.unpack_from("<I", header, 40)[0] + 44 == size
                ):
                    return
            except OSError:
                pass
            time.sleep(0.01)
        raise RuntimeError("La grabación nativa no terminó de cerrar el archivo")

    def _run(self) -> None:
        ep = None
        accounts = {}
        recordings = {}
        calls = {}
        retired: set[str] = set()
        media_dirty: set[str] = set()
        forward: list[tuple[str, str]] = []
        try:
            import pjsua2 as pj

            owner = self

            class NativeCall(pj.Call):
                def __init__(self, lid, account, call_id=pj.PJSUA_INVALID_ID):
                    super().__init__(account, call_id)
                    self.lid = lid
                    self.player = None
                    self.player_token = None
                    self.peer = None
                    self.connected_ports = None
                    self.invite_reported = False
                    self.reported_responses = set()
                    self.capture = None
                    self.capture_source = None
                    self.identity_reported = False
                    self.answer_reported = False

                def trace(self, kind, **data):
                    owner._notify(self.lid, "trace", CallEvent(kind, data))

                def received(self, event):
                    # Extract only evidence we use; never persist SIP messages or credentials.
                    message = ""
                    if event.type == pj.PJSIP_EVENT_RX_MSG:
                        message = event.body.rxMsg.rdata.wholeMsg
                    elif (
                        event.type == pj.PJSIP_EVENT_TSX_STATE
                        and event.body.tsxState.type == pj.PJSIP_EVENT_RX_MSG
                    ):
                        message = event.body.tsxState.src.rdata.wholeMsg
                    method = message.partition(" ")[0]
                    if method in {"BYE", "CANCEL"}:
                        self.trace(
                            "termination",
                            actor="remote",
                            reason=method.lower(),
                            evidence=f"rx_{method.lower()}",
                        )

                def onCallTsxState(self, prm):
                    self.received(prm.e)
                    if prm.e.type != pj.PJSIP_EVENT_TSX_STATE:
                        return
                    event = prm.e.body.tsxState
                    if event.tsx.role != pj.PJSIP_ROLE_UAC or event.tsx.method != "INVITE":
                        return
                    if event.type == pj.PJSIP_EVENT_TX_MSG and not self.invite_reported:
                        self.invite_reported = True
                        self.trace("invite_sent")
                        owner._notify(
                            self.lid, "progress", CallProgress("invite_sent", time.monotonic())
                        )
                    elif event.type == pj.PJSIP_EVENT_RX_MSG:
                        code = event.tsx.statusCode
                        if code not in self.reported_responses:
                            self.reported_responses.add(code)
                            message = event.src.rdata.wholeMsg
                            retry = re.search(r"(?im)^Retry-After:\s*(\d+)", message)
                            self.trace(
                                "response",
                                code=code,
                                retry_after=min(86400, int(retry.group(1))) if retry else 0,
                            )
                            if code == 180:
                                self.trace("ringing")
                            if 200 <= code < 300 and not self.answer_reported:
                                self.answer_reported = True
                                self.trace("answered")
                            if 300 <= code < 400:
                                self.trace("redirect_reported", code=code, actor="trunk")
                            owner._notify(
                                self.lid,
                                "progress",
                                CallProgress("response", time.monotonic(), code),
                            )

                def onCallState(self, prm):
                    info = self.getInfo()
                    self.received(prm.e)
                    if not self.identity_reported and info.callIdString:
                        self.identity_reported = True
                        self.trace("identity", call_id=" ".join(info.callIdString.split())[:160])
                    if info.state == pj.PJSIP_INV_STATE_CONFIRMED and not self.answer_reported:
                        self.answer_reported = True
                        self.trace("answered")
                    if info.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                        ended = CallEnded(info.lastStatusCode, info.lastReason)
                        if not self.answer_reported and info.lastStatusCode >= 300:
                            # Only a received SIP response proves rejection by the network.
                            is_rx = prm.e.type == pj.PJSIP_EVENT_RX_MSG or (
                                prm.e.type == pj.PJSIP_EVENT_TSX_STATE
                                and prm.e.body.tsxState.type == pj.PJSIP_EVENT_RX_MSG
                            )
                            if is_rx:
                                self.trace(
                                    "termination",
                                    actor="trunk",
                                    reason="sip_response",
                                    evidence=f"rx_sip_{info.lastStatusCode}",
                                )
                        owner._notify(self.lid, "closed", (ended.code, ended.reason))
                        if info.lastStatusCode >= 300:
                            log.warning(
                                "Llamada SIP rechazada: %s; id=%s; Call-ID=%s",
                                ended.detail,
                                self.lid,
                                " ".join(info.callIdString.split())[:160],
                            )
                        retired.add(self.lid)
                    else:
                        media_dirty.add(self.lid)

                def onCallMediaState(self, prm):
                    media_dirty.add(self.lid)

                def onDtmfDigit(self, prm):
                    if self.peer:
                        forward.append((self.peer, prm.digit))
                    else:
                        if prm.digit in {"1", "2"}:
                            log.info("DTMF %s recibido; llamada=%s", prm.digit, self.lid)
                        owner._notify(self.lid, "digit", prm.digit)

                def onCallTransferRequest(self, prm):
                    # Remote REFER must never create a call outside the campaign scheduler.
                    prm.statusCode = 603
                    self.trace("refer_rejected", actor="remote", code=603)

                def audio(self):
                    info = self.getInfo()
                    if info.state != pj.PJSIP_INV_STATE_CONFIRMED:
                        return None
                    for media in info.media:
                        if (
                            media.type == pj.PJMEDIA_TYPE_AUDIO
                            and media.status == pj.PJSUA_CALL_MEDIA_ACTIVE
                        ):
                            return self.getAudioMedia(media.index)
                    return None

            class NativePlayer(pj.AudioMediaPlayer):
                def __init__(self, lid, token, loop):
                    super().__init__()
                    self.lid, self.token = lid, token
                    self.loop = loop

                def onEof2(self):
                    # This callback may run on the native media thread. Never destroy here.
                    # PJSUA2 also reports EOF at every iteration of a looping file.
                    if not self.loop:
                        owner._notify(self.lid, "eof", self.token)

            class NativeCapture(pj.AudioMediaPort):
                def __init__(self, stream):
                    super().__init__()
                    self.stream = stream

                def onFrameReceived(self, frame):
                    if self.stream.stopped or self.stream.error:
                        return
                    # The PCM conference sink also receives silence during RTP gaps.
                    # Do not interpret silence as proof of a voicemail answer.
                    if frame.type != pj.PJMEDIA_FRAME_TYPE_AUDIO:
                        return
                    try:
                        buf = bytearray(frame.buf.size())
                        frame.buf.copy_to_bytearray(buf)
                        self.stream.push(bytes(buf))
                    except Exception:
                        self.stream.error = "invalid_audio"

            class NativeAccount(pj.Account):
                def __init__(self, tid):
                    super().__init__()
                    self.tid = tid

                def onRegState(self, prm):
                    info = self.getInfo()
                    owner.loop.call_soon_threadsafe(
                        owner._registration,
                        bool(info.regIsActive),
                        info.regStatus,
                        self.tid,
                    )

                def onIncomingCall(self, prm):
                    # Outbound-only application; reject unsolicited incoming calls.
                    lid = uuid4().hex
                    call = NativeCall(lid, self, prm.callId)
                    calls[lid] = call
                    param = pj.CallOpParam()
                    param.statusCode = 486
                    call.hangup(param)

            def destroy(obj):
                if obj is not None:
                    type(obj).__swig_destroy__(obj)
                    obj.thisown = False

            def stop_player(call):
                if call.player:
                    destroy(call.player)
                    call.player = None
                    call.player_token = None

            def stop_recording(lid):
                recorder = recordings.pop(lid, None)
                if recorder:
                    destroy(recorder)

            def record_sources(call):
                recorder = recordings.get(call.lid)
                if recorder:
                    audio = call.audio()
                    if audio is not None:
                        audio.startTransmit(recorder)
                    if call.player:
                        call.player.startTransmit(recorder)
                    if call.peer in calls:
                        peer_audio = calls[call.peer].audio()
                        if peer_audio is not None:
                            peer_audio.startTransmit(recorder)

            def stop_capture(call):
                if call.capture:
                    call.capture.stream.stop()
                    if call.capture_source is not None:
                        with contextlib.suppress(Exception):
                            call.capture_source.stopTransmit(call.capture)
                    destroy(call.capture)
                    call.capture = call.capture_source = None

            def connect_capture(call, audio):
                source = call.capture_source
                if source is None or source.getPortId() != audio.getPortId():
                    if source is not None:
                        with contextlib.suppress(Exception):
                            source.stopTransmit(call.capture)
                    audio.startTransmit(call.capture)
                    call.capture_source = audio

            def connect(call, peer):
                a, b = call.audio(), peer.audio()
                if a is None or b is None:
                    raise RuntimeError("El audio SIP aún no está disponible")
                ports = (a.getPortId(), b.getPortId())
                if call.connected_ports != ports:
                    a.startTransmit(b)
                    b.startTransmit(a)
                    call.connected_ports = ports
                    peer.connected_ports = ports[::-1]

            def execute(name, *args):
                if name == "dial":
                    lid, number, tid = args
                    call = NativeCall(lid, accounts[tid])
                    calls[lid] = call
                    param = pj.CallOpParam(True)
                    param.opt.audioCount = 1
                    param.opt.videoCount = 0
                    if hasattr(param.opt, "textCount"):
                        param.opt.textCount = 0
                    try:
                        call.makeCall(f"sip:{number}@{profiles[tid].sip.domain}", param)
                    except Exception:
                        retired.add(lid)
                        raise
                    return
                if name == "stop_recording":
                    stop_recording(args[0])
                    return
                call = calls.get(args[0])
                if call is None or args[0] in retired:
                    if name in {"hangup", "stop_play", "stop_capture", "stop_recording"}:
                        return
                    raise CallEnded()
                if name == "hangup":
                    stop_capture(call)
                    call.hangup(pj.CallOpParam())
                elif name == "start_recording":
                    if call.lid not in recordings:
                        recorder = pj.AudioMediaRecorder()
                        recorder.createRecorder(args[1])
                        recordings[call.lid] = recorder
                        record_sources(call)
                elif name == "start_capture":
                    if call.capture:
                        raise RuntimeError("Ya hay un análisis de audio en esta llamada")
                    audio = call.audio()
                    if audio is None:
                        raise RuntimeError("El audio SIP aún no está disponible")
                    capture = NativeCapture(args[1])
                    call.capture = capture
                    fmt = pj.MediaFormatAudio()
                    fmt.init(pj.PJMEDIA_FORMAT_PCM, 8000, 1, 20000, 16)
                    capture.createPort(f"amd-{call.lid[:12]}", fmt)
                    connect_capture(call, audio)
                elif name == "stop_capture":
                    if call.capture and call.capture.stream is args[1]:
                        stop_capture(call)
                elif name == "play":
                    _, path, token, loop = args
                    stop_player(call)
                    audio = call.audio()
                    if audio is None:
                        raise RuntimeError("El audio SIP aún no está disponible")
                    player = NativePlayer(call.lid, token, loop)
                    call.player, call.player_token = player, token
                    player.createPlayer(path, 0 if loop else pj.PJMEDIA_FILE_NO_LOOP)
                    player.startTransmit(audio)
                    record_sources(call)
                elif name == "stop_play":
                    if call.player_token == args[1]:
                        stop_player(call)
                elif name == "bridge":
                    peer = calls.get(args[1])
                    if peer is None or peer.lid in retired:
                        raise CallEnded()
                    stop_player(call)
                    stop_player(peer)
                    stop_capture(call)
                    stop_capture(peer)
                    connect(call, peer)
                    call.peer, peer.peer = peer.lid, call.lid
                    record_sources(call)

            ep = pj.Endpoint()
            ep.libCreate()
            config = pj.EpConfig()
            config.uaConfig.threadCnt = 0
            config.uaConfig.mainThreadOnly = True
            config.uaConfig.maxCalls = self.settings.trunk_channels
            config.logConfig.level = 1
            config.logConfig.consoleLevel = 1
            config.medConfig.clockRate = 8000
            config.medConfig.sndClockRate = 8000
            config.medConfig.maxMediaPorts = self.settings.trunk_channels * 3 + 8
            ep.libInit(config)
            profiles = {t.id: t for t in self.settings.trunk_profiles() if t.enabled}
            transports = {}
            for trunk in profiles.values():
                sip = trunk.sip
                key = (sip.transport, sip.local_port, sip.bind_address, sip.public_address)
                if key not in transports:
                    transport = pj.TransportConfig()
                    transport.port = sip.local_port
                    transport.boundAddress = sip.bind_address
                    transport.publicAddress = sip.public_address
                    kind = (
                        pj.PJSIP_TRANSPORT_UDP if sip.transport == "udp" else pj.PJSIP_TRANSPORT_TCP
                    )
                    transports[key] = ep.transportCreate(kind, transport)
            ep.libStart()
            ep.audDevManager().setNullDev()
            for codec in ep.codecEnum2():
                ep.codecSetPriority(codec.codecId, 0)
            ep.codecSetPriority("PCMU/8000/1", 255)
            ep.codecSetPriority("PCMA/8000/1", 254)
            for tid, trunk in profiles.items():
                sip = trunk.sip
                cfg = pj.AccountConfig()
                cfg.idUri = f"sip:{sip.caller_id or sip.username}@{sip.domain}"
                cfg.sipConfig.transportId = transports[
                    (sip.transport, sip.local_port, sip.bind_address, sip.public_address)
                ]
                cfg.regConfig.registerOnAdd = sip.registration_enabled
                cfg.regConfig.registrarUri = (
                    sip.registrar or f"sip:{sip.domain}" if sip.registration_enabled else ""
                )
                if sip.proxy:
                    cfg.sipConfig.proxies.append(sip.proxy)
                if sip.password:
                    cfg.sipConfig.authCreds.append(
                        pj.AuthCredInfo(
                            "digest", "*", sip.auth_username or sip.username, 0, sip.password
                        )
                    )
                cfg.mediaConfig.transportConfig.port = sip.rtp_port
                cfg.mediaConfig.transportConfig.portRange = sip.rtp_port_range
                cfg.mediaConfig.transportConfig.boundAddress = sip.bind_address
                cfg.mediaConfig.transportConfig.publicAddress = sip.public_address
                cfg.natConfig.iceEnabled = False
                account = NativeAccount(tid)
                accounts[tid] = account
                account.create(cfg)
                if not sip.registration_enabled:
                    self.loop.call_soon_threadsafe(self._registration, True, 200, tid)
            self.loop.call_soon_threadsafe(self._settle, self.started)

            while not self.stopping.is_set():
                # Bound each batch so commands cannot starve SIP timers.
                for _ in range(50):
                    try:
                        name, args, future = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        result = execute(name, *args)
                        self.loop.call_soon_threadsafe(self._settle, future, result)
                    except CallEnded as error:
                        self.loop.call_soon_threadsafe(self._settle, future, None, error)
                    except Exception as error:
                        cause = error_detail(error)
                        for t in profiles.values():
                            if t.sip.password:
                                cause = cause.replace(t.sip.password, "[oculto]")
                        detail = f"La operación SIP {name} falló: {cause}"
                        log.error("%s; llamada=%s", detail, args[0] if args else "—")
                        self.loop.call_soon_threadsafe(
                            self._settle,
                            future,
                            None,
                            RuntimeError(detail),
                        )
                ep.libHandleEvents(10)
                for lid in list(media_dirty):
                    media_dirty.discard(lid)
                    call = calls.get(lid)
                    if call and lid not in retired:
                        with contextlib.suppress(Exception):
                            audio = call.audio()
                            if audio is not None:
                                self._notify(lid, "ready")
                                if call.capture:
                                    connect_capture(call, audio)
                                if call.peer and call.peer in calls:
                                    connect(call, calls[call.peer])
                                elif call.player:
                                    call.player.startTransmit(audio)
                                record_sources(call)
                for lid, digit in forward:
                    if lid in calls and lid not in retired:
                        with contextlib.suppress(Exception):
                            calls[lid].dialDtmf(digit)
                forward.clear()
                for lid in list(retired):
                    retired.discard(lid)
                    call = calls.pop(lid, None)
                    if call:
                        stop_recording(call.lid)
                        stop_capture(call)
                        stop_player(call)
                        if call.peer in calls:
                            calls[call.peer].peer = None
                        destroy(call)
                    call = None
        except Exception as error:
            log.error("El motor SIP falló (%s)", type(error).__name__)
            self.loop.call_soon_threadsafe(
                self._settle,
                self.started,
                None,
                RuntimeError("No se pudo iniciar PJSUA2. Revisa su instalación y puertos SIP/RTP"),
            )
        finally:
            self.stopping.set()
            for t in self.settings.trunk_profiles():
                self.loop.call_soon_threadsafe(self._registration, False, 0, t.id)
            if ep:
                with contextlib.suppress(Exception):
                    ep.hangupAllCalls()
                    end = time.monotonic() + 3
                    while calls and time.monotonic() < end:
                        ep.libHandleEvents(20)
                        for lid in list(retired):
                            retired.discard(lid)
                            call = calls.pop(lid, None)
                            if call:
                                stop_recording(call.lid)
                                stop_capture(call)
                                stop_player(call)
                                destroy(call)
                            call = None
                    for call in calls.values():
                        stop_recording(call.lid)
                        stop_capture(call)
                        stop_player(call)
                        destroy(call)
                    calls.clear()
                    call = None
                    for account in accounts.values():
                        account.shutdown()
                        destroy(account)
                    accounts.clear()
                    account = None
                    ep.libDestroy()
                    destroy(ep)
                    ep = None
            for lid in list(self.legs):
                self._notify(lid, "closed", (503, "El motor SIP se detuvo"))
            while not self.commands.empty():
                _, _, future = self.commands.get_nowait()
                self.loop.call_soon_threadsafe(
                    self._settle,
                    future,
                    None,
                    RuntimeError("El motor SIP se detuvo"),
                )
