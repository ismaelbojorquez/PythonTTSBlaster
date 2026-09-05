from __future__ import annotations

import asyncio
import csv
import fcntl
import io
import json
import tempfile
import unicodedata
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.background import BackgroundTask
from starlette.middleware.trustedhost import TrustedHostMiddleware

from blaster.agent_pool import AgentStrategy
from blaster.analytics import Analytics, Filters
from blaster.automation import Automation, campaign_due_at
from blaster.config import Settings
from blaster.contact_files import import_contacts, read_csv
from blaster.countries import countries, country_code, history_phone_number
from blaster.dialing import format_dial_number
from blaster.engine import Engine
from blaster.management import management_router, write_config
from blaster.models import (
    MENU,
    CampaignInput,
    parse_contacts,
    render_message,
    transfer_numbers,
)
from blaster.preview import AudioPreviewInput, SpeechPreview
from blaster.reports import cdr_csv, excel_report
from blaster.retries import RetryPolicy
from blaster.security import Security
from blaster.store import Store, now
from blaster.telephony.simulated import SimulatedTelephony
from blaster.traceability import build_recording_bundle
from blaster.tts import SimulatedSpeech, close_speech, speech_for
from blaster.voices import VoiceManager

STATIC = Path(__file__).parent / "static"


class CampaignCopyForm(BaseModel):
    request_id: UUID
    name: str = Field(default="", max_length=100)
    note: str = Field(default="", max_length=500)


class CampaignForm(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    template: str = Field(min_length=1, max_length=4000)
    agent_number: str = ""
    agent_numbers_text: str = Field(default="", max_length=4000)
    agent_strategy: AgentStrategy = "round_robin"
    agent_pool_wait: float = Field(default=30, ge=0, le=300)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    csv_text: str = Field(min_length=1, max_length=8_000_000)
    country: str = "MX"
    agent_country: str = ""
    execution: Literal["draft", "now", "scheduled"] = "draft"
    local_at: str = Field(default="", max_length=64)
    schedule_timezone: str = Field(default="", max_length=100)

    def campaign(self, settings: Settings) -> CampaignInput:
        agents = transfer_numbers(
            self.agent_numbers_text, self.agent_number, self.agent_country or self.country
        )
        campaign = CampaignInput(
            name=self.name,
            template=self.template,
            agent_numbers=agents,
            agent_strategy=self.agent_strategy,
            agent_pool_wait=self.agent_pool_wait,
            retry_policy=self.retry_policy,
            contacts=parse_contacts(self.csv_text, self.country),
            country=country_code(self.country),
            agent_country=country_code(self.agent_country or self.country),
        )
        if settings.mode == "sip":
            for trunk in settings.trunk_profiles():
                if trunk.enabled:
                    for number in campaign.agent_numbers:
                        format_dial_number(number, trunk.sip.dial_format)
                    for contact in campaign.contacts:
                        format_dial_number(contact.phone, trunk.sip.dial_format)
        return campaign


class ConcurrencyInput(BaseModel):
    concurrency: int = Field(ge=1, le=30)


class SimulationInput(BaseModel):
    action: str


class ContactInspectionInput(BaseModel):
    csv_text: str = Field(min_length=1, max_length=8_000_000)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        lock = (settings.data_dir / "app.lock").open("a+")
        store = engine = automation = None
        try:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError(
                    "Ya hay una instancia usando este directorio de datos"
                ) from error
            if settings.mode == "sip":
                settings.validate_live()
                from blaster.telephony.pjsua import PJSUATelephony

                phone = PJSUATelephony(settings)
                speech = speech_for(settings)
            else:
                phone = SimulatedTelephony()
                speech = SimulatedSpeech()
            store = Store(settings.data_dir / "blaster.sqlite3")
            engine = Engine(settings, store, phone, speech)
            app.state.engine, app.state.store = engine, store
            app.state.analytics = Analytics(settings.data_dir / "blaster.sqlite3")
            app.state.security = Security(engine.ops, settings.auth)
            await app.state.security.bootstrap(public_access=bool(settings.web_public_url))
            await engine.start()
            app.state.speech_preview = SpeechPreview(
                settings, speech if settings.mode == "sip" else None
            )
            app.state.voice_manager = VoiceManager(settings)
            automation = Automation(settings, engine, app.state.analytics, report_lock)
            app.state.automation = automation
            await automation.start()
            yield
        finally:
            if automation:
                await automation.close()
            preview_speech = getattr(getattr(app.state, "speech_preview", None), "speech", None)
            if preview_speech is not None and (
                engine is None or preview_speech is not engine.speech
            ):
                await close_speech(preview_speech)
            if engine:
                await engine.close()
            if store:
                store.close()
            lock.close()

    app = FastAPI(title="Python Blaster TTS", lifespan=lifespan, docs_url=None, redoc_url=None)
    allowed_hosts = ["127.0.0.1", "localhost", "testserver"]
    if settings.web_public_url:
        allowed_hosts.append(urlsplit(settings.web_public_url).hostname)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            allowed_origins = {str(request.base_url).rstrip("/")}
            if settings.web_public_url:
                allowed_origins.add(settings.web_public_url)
            if origin and origin not in allowed_origins:
                return JSONResponse({"detail": "Origen no autorizado"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Origen no autorizado"}, status_code=403)
            content_type = request.headers.get("content-type", "").split(";")[0]
            file_upload = (
                request.url.path == "/api/contacts/import"
                and request.method == "POST"
                and content_type == "application/octet-stream"
            )
            if content_type != "application/json" and not file_upload:
                return JSONResponse({"detail": "Se requiere application/json"}, status_code=415)
            # Check actual received bytes too, so chunked bodies cannot bypass the limit.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 8_500_000:
                    return JSONResponse({"detail": "El archivo supera 8 MB"}, status_code=413)
            request._body = bytes(body)
        path = request.url.path
        if path.startswith("/api/"):
            public = path in {"/api/auth/status", "/api/auth/login", "/api/auth/setup"}
            user = app.state.security.user(request.cookies.get("blaster_session"))
            request.state.user = user
            if not public:
                if not user:
                    return JSONResponse({"detail": "Inicia sesión para continuar"}, status_code=401)
                admin = path.startswith(
                    (
                        "/api/manage/users",
                        "/api/manage/audit",
                        "/api/manage/config",
                        "/api/manage/voices",
                    )
                ) or (
                    (path.startswith("/api/manage/trunks") or path == "/api/settings")
                    and request.method != "GET"
                )
                readonly = user["role"] == "analyst"
                if (
                    (admin and user["role"] != "admin")
                    or (readonly and path.startswith("/api/recordings/"))
                    or (readonly and path.startswith("/api/amd-calibration"))
                    or (readonly and path.startswith("/api/traceability/bundle"))
                    or (
                        readonly
                        and request.method not in {"GET", "HEAD", "OPTIONS"}
                        and path != "/api/auth/logout"
                    )
                ):
                    return JSONResponse(
                        {"detail": "Tu rol no permite esta acción"}, status_code=403
                    )
        response = await call_next(request)
        if (
            path.startswith("/api/")
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and response.status_code < 400
            and getattr(request.state, "user", None)
        ):
            body = getattr(request, "_body", b"{}")
            try:
                fields = list(json.loads(body))
            except (ValueError, TypeError):
                fields = []
            app.state.engine.ops.audit(
                request.state.user,
                request.method + " " + path,
                path,
                {"fields": fields, "status": response.status_code},
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; media-src 'self' blob:; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse(
            {"detail": "; ".join(item["msg"] for item in error.errors())}, status_code=422
        )

    @app.exception_handler(ValueError)
    async def value_error(request: Request, error: ValueError):
        detail = "Revisa los datos de la campaña"
        if isinstance(error, ValidationError):
            detail = "; ".join(item["msg"] for item in error.errors())
        else:
            detail = str(error)
        return JSONResponse({"detail": detail}, status_code=422)

    @app.exception_handler(KeyError)
    async def key_error(request: Request, error: KeyError):
        return JSONResponse({"detail": "No se encontró el registro solicitado"}, status_code=404)

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/healthz", include_in_schema=False)
    async def health():
        app.state.store.db.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get("/api/countries")
    async def country_catalog():
        return countries()

    @app.get("/api/status")
    async def status():
        return {
            **app.state.engine.snapshot(),
            "reporting_timezone": settings.reporting_timezone,
            "report_max_rows": settings.report_max_rows,
        }

    def filters(
        date_from: date | None = None,
        date_to: date | None = None,
        campaign_id: str | None = Query(default=None, max_length=64),
        mode: Literal["sip", "simulation", "all"] | None = None,
        status: str | None = Query(default=None, max_length=32),
        search: str = Query(default="", max_length=100),
    ) -> Filters:
        result = Filters(
            date_from,
            date_to,
            campaign_id,
            mode or settings.mode,
            status,
            search,
            settings.reporting_timezone,
        )
        result.where()
        return result

    selected_filters = Depends(filters)
    page_limit = Query(default=50, ge=1, le=200)
    page_offset = Query(default=0, ge=0)

    @app.get("/api/analytics/summary")
    async def analytics_summary(selected: Filters = selected_filters):
        return await asyncio.to_thread(app.state.analytics.summary, selected)

    @app.get("/api/calls")
    async def calls(
        selected: Filters = selected_filters, limit: int = page_limit, offset: int = page_offset
    ):
        return await asyncio.to_thread(app.state.analytics.calls, selected, limit, offset)

    @app.get("/api/calls/{jid}")
    async def call_detail(jid: str):
        return await asyncio.to_thread(app.state.analytics.detail, jid)

    def trace_filters(
        by: Literal["credit", "phone"],
        query: str = Query(min_length=1, max_length=255),
        country: str = Query(default="MX", min_length=2, max_length=2),
    ) -> Filters:
        value = unicodedata.normalize("NFC", query.strip())
        if not value:
            raise ValueError("Escribe el Credito o Telefono que deseas consultar")
        if by == "phone":
            value = history_phone_number(value, country)
        elif any(ord(character) < 32 for character in value):
            raise ValueError("Credito contiene caracteres no válidos")
        result = Filters(
            mode="all",
            timezone=settings.reporting_timezone,
            credit_id=value if by == "credit" else None,
            phone=value if by == "phone" else None,
        )
        result.where()
        return result

    selected_trace = Depends(trace_filters)

    @app.get("/api/traceability")
    async def traceability(
        selected: Filters = selected_trace,
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = page_offset,
    ):
        return await asyncio.to_thread(app.state.analytics.trace, selected, limit, offset)

    report_lock = asyncio.Lock()

    @app.get("/api/reports/{format}")
    async def report(
        format: Literal["xlsx", "csv"],
        selected: Filters = selected_filters,
        lang: Literal["es", "en"] = Query(default="es"),
    ):
        if report_lock.locked():
            raise HTTPException(409, "Ya se está preparando un reporte. Espera a que termine.")

        def generate():
            rows, summary, events = app.state.analytics.report_data(
                selected, settings.report_max_rows
            )
            return (
                excel_report(rows, summary, events, selected, lang)
                if format == "xlsx"
                else cdr_csv(rows, lang)
            )

        async with report_lock:
            # The export uses its own read snapshot and never blocks the SIP event loop.
            task = asyncio.create_task(asyncio.to_thread(generate))
            try:
                content = await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
        mime = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if format == "xlsx"
            else "text/csv; charset=utf-8"
        )
        return Response(
            content,
            media_type=mime,
            headers={
                "Content-Disposition": f'attachment; filename="blaster-reporte.{format}"',
            },
        )

    @app.get("/api/traceability/report.xlsx")
    async def traceability_report(
        request: Request,
        selected: Filters = selected_trace,
        lang: Literal["es", "en"] = Query(default="es"),
    ):
        if report_lock.locked():
            raise HTTPException(409, "Ya se está preparando un reporte. Espera a que termine.")

        def generate():
            rows, summary, events = app.state.analytics.report_data(
                selected, settings.report_max_rows
            )
            return excel_report(rows, summary, events, selected, lang), len(rows)

        async with report_lock:
            content, count = await asyncio.to_thread(generate)
        identifier = selected.credit_id if selected.credit_id is not None else selected.phone
        app.state.engine.ops.audit(
            request.state.user,
            "traceability.report_downloaded",
            identifier,
            {"by": "credit" if selected.credit_id is not None else "phone", "calls": count},
        )
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": 'attachment; filename="blaster-trazabilidad.xlsx"',
            },
        )

    @app.get("/api/traceability/bundle.zip")
    async def traceability_bundle(
        request: Request,
        selected: Filters = selected_trace,
        lang: Literal["es", "en"] = Query(default="es"),
    ):
        if report_lock.locked():
            raise HTTPException(409, "Ya se está preparando una descarga. Espera a que termine.")
        report_dir = settings.data_dir / "reports"
        report_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = tempfile.NamedTemporaryFile(
            prefix="traceability-", suffix=".zip", dir=report_dir, delete=False
        )
        target = Path(handle.name)
        handle.close()

        def generate():
            rows, summary, events = app.state.analytics.report_data(
                selected, settings.report_max_rows
            )
            xlsx = excel_report(rows, summary, events, selected, lang)
            return build_recording_bundle(
                target, rows, xlsx, app.state.engine.recordings.directory, lang
            )

        try:
            async with report_lock:
                bundle = await asyncio.to_thread(generate)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        identifier = selected.credit_id if selected.credit_id is not None else selected.phone
        app.state.engine.ops.audit(
            request.state.user,
            "traceability.bundle_downloaded",
            identifier,
            {"by": "credit" if selected.credit_id is not None else "phone", **bundle},
        )
        return FileResponse(
            target,
            media_type="application/zip",
            filename="blaster-trazabilidad-grabaciones.zip",
            background=BackgroundTask(target.unlink, missing_ok=True),
        )

    @app.post("/api/settings")
    async def configure(payload: ConcurrencyInput):
        previous = settings.concurrency
        app.state.engine.configure_concurrency(payload.concurrency)
        if settings.config_path:
            try:
                write_config(settings.config_path, {"concurrency": payload.concurrency})
            except OSError as error:
                settings.concurrency = previous
                raise ValueError("No se pudo guardar la concurrencia en el TOML") from error
        return app.state.engine.snapshot()

    @app.get("/api/campaigns")
    async def campaigns():
        return app.state.store.campaigns()

    @app.post("/api/campaigns/{cid}/retries")
    async def configure_retries(cid: str, payload: RetryPolicy, request: Request):
        store = app.state.store
        campaign = store.campaign(cid)
        if campaign["status"] != "draft" or store.db.execute(
            "SELECT 1 FROM jobs WHERE campaign_id=? AND started_at IS NOT NULL LIMIT 1", (cid,),
        ).fetchone():
            raise ValueError("Configura los reintentos antes de iniciar la campaña. "
                             "Puedes duplicarla para preparar otro envío")
        with store.db:
            store.db.execute("UPDATE campaigns SET retry_policy=? WHERE id=?",
                             (payload.model_dump_json(), cid))
            # Audit and policy are one transaction, even when a draft has a schedule.
            store.db.execute(
                "INSERT INTO audit(created_at,actor_id,actor_name,action,target,detail) "
                "VALUES(?,?,?,?,?,?)",
                (now(), request.state.user.get("id"), request.state.user.get("username", "local"),
                 "campaign.retries_updated", cid, json.dumps({
                     "before": campaign["retry_policy"], "after": payload.model_dump(),
                 })),
            )
        return {"ok": True, "retry_policy": payload.model_dump()}

    @app.post("/api/campaigns", status_code=201)
    async def create_campaign(payload: CampaignForm, request: Request):
        campaign = payload.campaign(settings)
        engine, store = app.state.engine, app.state.store
        schedule = None
        if payload.execution == "scheduled":
            if not settings.automation.enabled:
                raise ValueError(
                    "Activa las tareas programadas en Configuración antes de programar"
                )
            due = campaign_due_at(payload.local_at, payload.schedule_timezone)
            schedule = {
                "due_at": due.isoformat(), "timezone": payload.schedule_timezone,
                "created_by": request.state.user["id"],
            }
        elif payload.execution == "now":
            engine.ensure_startable()
            engine.validate_destinations(
                campaign.agent_numbers, [c.phone for c in campaign.contacts]
            )
        cid = store.create_campaign(campaign, settings.mode, schedule=schedule)
        engine.ops.audit(request.state.user, "campaign.created", cid, {
            "name": campaign.name, "contacts": len(campaign.contacts),
            "mode": settings.mode, "execution": payload.execution,
            "retry_policy": campaign.retry_policy.model_dump(),
        })
        if payload.execution == "now":
            try:
                engine.start_campaign(cid)
            except ValueError as error:
                # A last-minute trunk change must not lose the saved campaign or invite retries.
                return {"id": cid, "execution": "draft", "start_error": str(error)}
        if schedule:
            engine.ops.audit(request.state.user, "campaign.scheduled", cid, schedule)
        elif payload.execution == "now":
            engine.ops.audit(request.state.user, "campaign.started_on_create", cid, {})
        return {"id": cid, "execution": payload.execution, "schedule": store.pending_schedule(cid)}

    @app.post("/api/preview")
    async def preview(payload: CampaignForm):
        campaign = payload.campaign(settings)
        return {
            "count": len(campaign.contacts),
            "agent_numbers": campaign.agent_numbers,
            "menu": MENU,
            "samples": [
                {
                    "phone": c.phone,
                    "message": render_message(
                        campaign.template,
                        {
                            **c.variables,
                            "telefono": c.phone,
                            "phone": c.phone,
                            "telephone": c.phone,
                            "credito": c.credit_id,
                            "credit": c.credit_id,
                            "account": c.credit_id,
                            "account_id": c.credit_id,
                        },
                    ),
                }
                for c in campaign.contacts[:3]
            ],
        }

    @app.post("/api/contacts/import")
    async def contacts_import(
        request: Request,
        filename: str = Query(max_length=255),
        sheet: str = Query(default="", max_length=100),
    ):
        return await asyncio.to_thread(import_contacts, await request.body(), filename, sheet)

    @app.post("/api/contacts/inspect")
    async def contacts_inspect(payload: ContactInspectionInput):
        table = await asyncio.to_thread(read_csv, payload.csv_text)
        return table.metadata()

    @app.post("/api/preview/audio")
    async def preview_audio(payload: AudioPreviewInput):
        message, phone = payload.sample()
        service = app.state.speech_preview
        if service.lock.locked() or app.state.voice_manager.lock.locked():
            raise HTTPException(429, "Ya se está generando una muestra. Espera e intenta de nuevo.")
        async with service.lock:
            try:
                async with asyncio.timeout(settings.tts_timeout):
                    return await service.generate(message, phone)
            except TimeoutError as error:
                raise HTTPException(
                    504, "La voz tardó demasiado. Intenta con un mensaje más corto."
                ) from error
            except ValueError:
                raise
            except Exception as error:
                raise HTTPException(
                    503, "No se pudo generar el audio. Revisa la voz local y el motor Piper."
                ) from error

    @app.get("/api/campaigns/{cid}/jobs")
    async def jobs(cid: str, offset: int = 0, limit: int = 100):
        app.state.store.campaign(cid)
        return app.state.store.jobs(cid, min(200, max(1, limit)), max(0, offset))

    @app.get("/api/jobs/{jid}/events")
    async def events(jid: str):
        return app.state.store.events(jid)

    @app.get("/api/campaigns/{cid}/history")
    async def campaign_history(cid: str, offset: int = Query(default=0, ge=0)):
        return app.state.store.history.history(cid, offset)

    async def copy_campaign(cid, kind, payload, request):
        store, engine = app.state.store, app.state.engine
        history = store.history
        source = store.campaign(cid)
        name = payload.name.strip() or (
            source["name"] if kind == "rerun" else source["name"][:92] + " (copia)"
        )
        note = payload.note.strip()
        actor = request.state.user
        fingerprint = history.fingerprint(cid, kind, name, note, actor)
        new_id = history.replay(str(payload.request_id), fingerprint)
        if new_id:
            return {"id": new_id, "replayed": True,
                    "start_error": history.lineage(new_id)["start_error"]}
        try:
            if kind == "rerun":
                if source["mode"] != settings.mode:
                    raise ValueError("Duplica la campaña para crear un borrador en el modo actual")
                history.check_rerun(cid)
                engine.ensure_startable()
                engine.validate_destinations(
                    source["agent_numbers"], [j["phone"] for j in store.jobs(cid, 10000)]
                )
            new_id = history.copy(
                cid, kind, name, note, str(payload.request_id), actor, settings.mode, fingerprint
            )
        except ValueError as error:
            engine.ops.audit(actor, f"campaign.{kind}_rejected", cid, {
                "request_id": str(payload.request_id), "reason": str(error), "note": note,
            })
            raise
        if kind == "rerun":
            engine.ops.audit(actor, "campaign.start_requested", new_id, history.lineage(new_id))
            try:
                engine.start_campaign(new_id)
            except ValueError as error:
                with store.db:
                    store.db.execute(
                        "UPDATE campaign_copies SET start_error=? WHERE campaign_id=?",
                        (str(error), new_id),
                    )
                engine.ops.audit(actor, "campaign.start_failed", new_id, {"reason": str(error)})
                return {"id": new_id, "start_error": str(error), "replayed": False}
            engine.ops.audit(actor, "campaign.rerun_started", new_id, history.lineage(new_id))
        return {"id": new_id, "replayed": False}

    @app.post("/api/campaigns/{cid}/rerun", status_code=201)
    async def rerun_campaign(cid: str, payload: CampaignCopyForm, request: Request):
        return await copy_campaign(cid, "rerun", payload, request)

    @app.post("/api/campaigns/{cid}/duplicate", status_code=201)
    async def duplicate_campaign(cid: str, payload: CampaignCopyForm, request: Request):
        return await copy_campaign(cid, "duplicate", payload, request)

    @app.post("/api/campaigns/{cid}/{action}")
    async def campaign_action(cid: str, action: str, request: Request):
        engine = app.state.engine
        if action == "start":
            engine.store.campaign(cid)
            lineage = engine.store.history.lineage(cid)
            engine.ops.audit(request.state.user, "campaign.start_requested", cid, lineage)
            try:
                engine.start_campaign(cid)
            except ValueError as error:
                engine.ops.audit(
                    request.state.user, "campaign.start_failed", cid, {"reason": str(error)}
                )
                raise
            engine.ops.audit(request.state.user, "campaign.started", cid, lineage)
            with engine.store.db:
                engine.store.db.execute(
                    "UPDATE campaign_copies SET start_error=NULL WHERE campaign_id=?", (cid,),
                )
                engine.store.db.execute(
                    "UPDATE campaign_schedules SET state='cancelled',"
                    "detail='Iniciada manualmente' WHERE campaign_id=? "
                    "AND state='pending'",
                    (cid,),
                )
        elif action == "pause":
            engine.pause_campaign(cid)
        elif action == "stop":
            await engine.stop_campaign(cid)
        else:
            raise HTTPException(404, "Acción no encontrada")
        return {"ok": True}

    @app.post("/api/jobs/{jid}/simulate")
    async def simulate(jid: str, payload: SimulationInput):
        app.state.engine.simulate(jid, payload.action)
        return {"ok": True}

    @app.get("/api/campaigns/{cid}/export")
    async def export(cid: str):
        app.state.store.campaign(cid)
        output = io.StringIO()
        writer = csv.writer(output)
        columns = [
            "credit_id", "phone", "customer_trunk_name", "customer_trunk_id", "status",
            "detail", "started_at", "ended_at", "id", "contact_id", "attempt_number",
            "retry_of", "available_at",
        ]
        writer.writerow([
            "credito", "telefono", "troncal", "id_troncal", "estado", "detalle", "inicio",
            "fin", "id_llamada", "id_contacto", "intento", "intento_anterior",
            "disponible_desde",
        ])
        for row in app.state.store.jobs(cid, limit=100000, latest=False):
            values = [str(row[column] or "") for column in columns]
            # Preserve telephone numbers and prevent spreadsheet formula interpretation.
            writer.writerow(
                [
                    "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
                    for value in values
                ]
            )
        return Response(
            "\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="resultados-{cid[:8]}.csv"'},
        )

    app.include_router(management_router())
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
