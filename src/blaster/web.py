from __future__ import annotations

import asyncio
import csv
import fcntl
import io
import json
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from blaster.analytics import Analytics, Filters
from blaster.automation import Automation
from blaster.config import Settings
from blaster.dialing import format_dial_number
from blaster.engine import Engine
from blaster.management import management_router, write_config
from blaster.models import MENU, CampaignInput, parse_contacts, render_message
from blaster.preview import AudioPreviewInput, SpeechPreview
from blaster.reports import cdr_csv, excel_report
from blaster.security import Security
from blaster.store import Store
from blaster.telephony.simulated import SimulatedTelephony
from blaster.tts import PiperSpeech, SimulatedSpeech

STATIC = Path(__file__).parent / "static"


class CampaignForm(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    template: str = Field(min_length=1, max_length=4000)
    agent_number: str
    csv_text: str = Field(min_length=1, max_length=8_000_000)

    def campaign(self, settings: Settings) -> CampaignInput:
        campaign = CampaignInput(
            name=self.name,
            template=self.template,
            agent_number=self.agent_number,
            contacts=parse_contacts(self.csv_text),
        )
        if settings.mode == "sip":
            for trunk in settings.trunk_profiles():
                if trunk.enabled:
                    format_dial_number(campaign.agent_number, trunk.sip.dial_format)
                    for contact in campaign.contacts:
                        format_dial_number(contact.phone, trunk.sip.dial_format)
        return campaign


class ConcurrencyInput(BaseModel):
    concurrency: int = Field(ge=1, le=30)


class SimulationInput(BaseModel):
    action: str


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
                speech = PiperSpeech(settings.voice_model, settings.tts_workers)
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
            automation = Automation(settings, engine, app.state.analytics, report_lock)
            app.state.automation = automation
            await automation.start()
            yield
        finally:
            if automation:
                await automation.close()
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
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
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
                    ("/api/manage/users", "/api/manage/audit", "/api/manage/config")
                ) or (
                    (path.startswith("/api/manage/trunks") or path == "/api/settings")
                    and request.method != "GET"
                )
                readonly = user["role"] == "analyst"
                if (
                    (admin and user["role"] != "admin")
                    or (readonly and path.startswith("/api/recordings/"))
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

    report_lock = asyncio.Lock()

    @app.get("/api/reports/{format}")
    async def report(format: Literal["xlsx", "csv"], selected: Filters = selected_filters):
        if report_lock.locked():
            raise HTTPException(409, "Ya se está preparando un reporte. Espera a que termine.")

        def generate():
            rows, summary, events = app.state.analytics.report_data(
                selected, settings.report_max_rows
            )
            return (
                excel_report(rows, summary, events, selected) if format == "xlsx" else cdr_csv(rows)
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

    @app.post("/api/campaigns", status_code=201)
    async def create_campaign(payload: CampaignForm):
        cid = app.state.store.create_campaign(payload.campaign(settings), settings.mode)
        return {"id": cid}

    @app.post("/api/preview")
    async def preview(payload: CampaignForm):
        campaign = payload.campaign(settings)
        return {
            "count": len(campaign.contacts),
            "menu": MENU,
            "samples": [
                {
                    "phone": c.phone,
                    "message": render_message(
                        campaign.template, {**c.variables, "telefono": c.phone}
                    ),
                }
                for c in campaign.contacts[:3]
            ],
        }

    @app.post("/api/preview/audio")
    async def preview_audio(payload: AudioPreviewInput):
        message, phone = payload.sample()
        service = app.state.speech_preview
        if service.lock.locked():
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

    @app.post("/api/campaigns/{cid}/{action}")
    async def campaign_action(cid: str, action: str):
        engine = app.state.engine
        if action == "start":
            engine.start_campaign(cid)
            with engine.store.db:
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
        columns = ["phone", "status", "detail", "started_at", "ended_at"]
        writer.writerow(["telefono", "estado", "detalle", "inicio", "fin"])
        for row in app.state.store.jobs(cid, limit=10000):
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
