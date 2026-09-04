"""Authenticated management API. SIP credentials persist only in the configured TOML."""

from __future__ import annotations

import asyncio
import contextlib
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from blaster.automation import local_instant, next_report
from blaster.config import AutomationSettings, RecordingSettings, Settings, TrunkSettings
from blaster.models import render_message
from blaster.routing import TrunkRouter
from blaster.security import Credentials, UserInput, password_hash, safe_user, verify
from blaster.store import now


class TemplateInput(BaseModel):
    id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)
    agent_number: str = ""


class ScheduleInput(BaseModel):
    campaign_id: str
    local_at: str
    timezone: str


class ReportInput(BaseModel):
    id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=100)
    cadence: Literal["daily", "weekly"] = "daily"
    local_time: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday: int = Field(default=0, ge=0, le=6)
    timezone: str = "America/Mexico_City"
    format: Literal["xlsx", "csv"] = "xlsx"
    period_days: int = Field(default=1, ge=1, le=365)
    mode: Literal["sip", "simulation", "all"] = "sip"
    enabled: bool = True


class GlobalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concurrency: int = Field(ge=1, le=30)
    trunk_channels: int = Field(ge=2, le=60)
    calls_per_second: float = Field(gt=0, le=20)
    routing: Literal["priority", "weighted"]
    ring_timeout: float = Field(gt=0, le=180)
    agent_timeout: float = Field(gt=0, le=180)
    choice_timeout: float = Field(gt=0, le=120)
    max_call_seconds: float = Field(gt=0, le=14400)
    reporting_timezone: str
    report_max_rows: int = Field(ge=100, le=100000)
    recordings: RecordingSettings
    automation: AutomationSettings


def profile_data(t):
    data = t.model_dump()
    data["sip"]["password"] = t.sip.password
    return data


def settings_data(settings):
    data = settings.model_dump(exclude={"config_path"})
    data["sip"]["password"] = settings.sip.password
    data["auth"]["bootstrap_password"] = settings.auth.bootstrap_password
    data["trunks"] = [profile_data(t) for t in settings.trunks]
    return data


def write_config(path, updates):
    import tomlkit

    text = path.read_text()
    doc = tomlkit.parse(text)
    for key, value in updates.items():
        doc[key] = value
    content = tomlkit.dumps(doc)
    fd, temp = tempfile.mkstemp(prefix=".config-", suffix=".toml", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)
    return text


async def reconfigure(app, updates):
    engine = app.state.engine
    settings = engine.settings
    if engine.sessions or engine.active_campaign or engine.router.reloading:
        raise HTTPException(
            409, "Detén la campaña y espera a que terminen las llamadas para aplicar."
        )
    if not settings.config_path:
        raise HTTPException(409, "Inicia con --config config.toml para guardar los cambios.")
    candidate = Settings.model_validate({**settings_data(settings), **updates})
    candidate.config_path = settings.config_path
    if candidate.mode == "sip":
        candidate.validate_live()
    old_values = settings_data(settings)
    old_text = None
    engine.router.reloading = True
    try:
        old_text = write_config(settings.config_path, updates)
        await engine.telephony.stop()
        for key in updates:
            setattr(settings, key, getattr(candidate, key))
        engine.router = TrunkRouter(settings, engine.ops, engine.telephony)
        engine.router.reloading = True
        await engine.telephony.start()
    except BaseException:
        if old_text is not None:
            # Restore content atomically, without exposing secrets in errors or audit.
            restore = Settings.model_validate(old_values)
            for key in updates:
                setattr(settings, key, getattr(restore, key))
            # Remove newly introduced keys as well.
            fd, temp = tempfile.mkstemp(prefix=".config-", dir=settings.config_path.parent)
            with os.fdopen(fd, "w") as output:
                output.write(old_text)
            os.chmod(temp, 0o600)
            os.replace(temp, settings.config_path)
            engine.router = TrunkRouter(settings, engine.ops, engine.telephony)
            with contextlib.suppress(Exception):
                await engine.telephony.stop()
                await engine.telephony.start()
        raise
    finally:
        engine.router.reloading = False
        engine.wakeup.set()


class UserUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    role: Literal["admin", "operator", "analyst"]
    enabled: bool
    password: str = Field(default="", max_length=256, repr=False)


def management_router():
    router = APIRouter()

    def ops(request):
        return request.app.state.engine.ops

    def cookie(response, token, settings, public_url):
        response.set_cookie(
            "blaster_session",
            token,
            httponly=True,
            secure=public_url.startswith("https://"),
            samesite="strict",
            max_age=settings.session_hours * 3600,
            path="/",
        )

    @router.get("/api/auth/status")
    async def auth_status(request: Request):
        security = request.app.state.security
        return {
            "enabled": security.settings.enabled,
            "setup_required": not security.db.execute("SELECT 1 FROM users LIMIT 1").fetchone(),
            "user": security.user(request.cookies.get("blaster_session")),
        }

    @router.post("/api/auth/setup")
    async def setup(payload: UserInput, request: Request, response: Response):
        security = request.app.state.security
        if security.db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise HTTPException(409, "El administrador inicial ya existe")
        if len(payload.password) < 12:
            raise ValueError("Usa una contraseña de al menos 12 caracteres")
        encoded = await asyncio.to_thread(password_hash, payload.password)
        # Recheck after the asynchronous hash: only one first administrator may be created.
        if security.db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise HTTPException(409, "El administrador inicial ya existe")
        payload.role, payload.enabled = "admin", True
        uid = security.create(payload, encoded)
        cookie(
            response,
            security.issue(uid),
            security.settings,
            request.app.state.engine.settings.web_public_url,
        )
        user = safe_user(security.db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
        ops(request).audit(user, "auth.setup", uid)
        return user

    @router.post("/api/auth/login")
    async def login(payload: Credentials, request: Request, response: Response):
        security = request.app.state.security
        security.throttle(request.client.host if request.client else "local")
        row = security.db.execute(
            "SELECT * FROM users WHERE username=?", (payload.username,)
        ).fetchone()
        valid = await asyncio.to_thread(
            verify, payload.password, row["password_hash"] if row else security.dummy
        )
        if not row or not valid or not row["enabled"]:
            ops(request).audit({}, "auth.login_failed", "")
            raise HTTPException(401, "Usuario o contraseña incorrectos")
        user = safe_user(row)
        cookie(
            response,
            security.issue(row["id"]),
            security.settings,
            request.app.state.engine.settings.web_public_url,
        )
        ops(request).audit(user, "auth.login", row["id"])
        return user

    @router.post("/api/auth/logout")
    async def logout(request: Request, response: Response):
        request.app.state.security.revoke(request.cookies.get("blaster_session"))
        response.delete_cookie("blaster_session", path="/")
        return {"ok": True}

    @router.get("/api/manage/users")
    async def users(request: Request):
        return [safe_user(r) for r in ops(request).rows("SELECT * FROM users ORDER BY username")]

    @router.post("/api/manage/users")
    async def create_user(payload: UserInput, request: Request):
        if len(payload.password) < 12:
            raise ValueError("Usa una contraseña de al menos 12 caracteres")
        encoded = await asyncio.to_thread(password_hash, payload.password)
        try:
            uid = request.app.state.security.create(payload, encoded)
        except sqlite3.IntegrityError as error:
            raise ValueError("Ese usuario ya existe") from error
        return {"id": uid}

    @router.post("/api/manage/users/{uid}")
    async def update_user(uid: str, payload: UserUpdate, request: Request):
        db = ops(request).db
        encoded = None
        if payload.password:
            if len(payload.password) < 12:
                raise ValueError("Usa una contraseña de al menos 12 caracteres")
            encoded = await asyncio.to_thread(password_hash, payload.password)
        row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            raise KeyError(uid)
        if (
            row["role"] == "admin"
            and row["enabled"]
            and (payload.role != "admin" or not payload.enabled)
        ):
            count = db.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1"
            ).fetchone()[0]
            if count <= 1:
                raise ValueError("Debe permanecer al menos un administrador activo")
        with db:
            db.execute(
                "UPDATE users SET display_name=?,role=?,enabled=?,password_hash=? WHERE id=?",
                (
                    payload.display_name,
                    payload.role,
                    int(payload.enabled),
                    encoded or row["password_hash"],
                    uid,
                ),
            )
            db.execute("DELETE FROM auth_sessions WHERE user_id=?", (uid,))
        return {"ok": True}

    @router.get("/api/manage/audit")
    async def audit(request: Request, offset: int = 0):
        return ops(request).rows(
            "SELECT * FROM audit ORDER BY id DESC LIMIT 100 OFFSET ?", (max(0, offset),)
        )

    @router.get("/api/manage/trunks")
    async def trunks(request: Request):
        return {
            "routing": request.app.state.engine.settings.routing,
            "items": request.app.state.engine.router.snapshot(),
        }

    @router.post("/api/manage/trunks")
    async def save_trunk(payload: TrunkSettings, request: Request):
        engine = request.app.state.engine
        profiles = engine.settings.trunk_profiles()
        old = next((t for t in profiles if t.id == payload.id), None)
        if old and not payload.sip.password:
            payload.sip.password = old.sip.password
        updated = [payload if t.id == payload.id else t for t in profiles]
        if old is None:
            updated.append(payload)
        await reconfigure(request.app, {"trunks": [profile_data(t) for t in updated]})
        engine.ops.trunk_event(
            payload.id, "configuration", "Configuración actualizada desde el panel"
        )
        return {"ok": True}

    @router.get("/api/manage/trunks/{tid}/history")
    async def trunk_history(tid: str, request: Request, offset: int = 0):
        return ops(request).rows(
            "SELECT * FROM trunk_events WHERE trunk_id=? ORDER BY id DESC LIMIT 100 OFFSET ?",
            (tid, max(0, offset)),
        )

    @router.get("/api/manage/config")
    async def get_config(request: Request):
        data = request.app.state.engine.settings.model_dump()
        return {key: data[key] for key in GlobalInput.model_fields}

    @router.post("/api/manage/config")
    async def set_config(payload: GlobalInput, request: Request):
        await reconfigure(request.app, payload.model_dump())
        return {"ok": True}

    @router.get("/api/manage/templates")
    async def templates(request: Request):
        return ops(request).rows("SELECT * FROM templates ORDER BY updated_at DESC")

    @router.post("/api/manage/templates")
    async def save_template(payload: TemplateInput, request: Request):
        from string import Formatter

        from blaster.models import phone_number

        fields = {name for _, name, _, _ in Formatter().parse(payload.message) if name}
        render_message(payload.message, {k: "ejemplo" for k in fields})
        agent = phone_number(payload.agent_number) if payload.agent_number else ""
        tid = payload.id or uuid4().hex
        with ops(request).db:
            ops(request).db.execute(
                "INSERT INTO templates VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,message=excluded.message,"
                "agent_number=excluded.agent_number,updated_at=excluded.updated_at,"
                "updated_by=excluded.updated_by",
                (tid, payload.name, payload.message, agent, now(), request.state.user["id"]),
            )
        return {"id": tid}

    @router.post("/api/manage/templates/{tid}/delete")
    async def delete_template(tid: str, request: Request):
        with ops(request).db:
            ops(request).db.execute("DELETE FROM templates WHERE id=?", (tid,))
        return {"ok": True}

    @router.get("/api/manage/schedules")
    async def schedules(request: Request):
        return ops(request).rows(
            "SELECT s.*,c.name AS campaign_name,c.mode FROM campaign_schedules s "
            "JOIN campaigns c ON c.id=s.campaign_id ORDER BY s.due_at DESC LIMIT 200"
        )

    @router.post("/api/manage/schedules")
    async def create_schedule(payload: ScheduleInput, request: Request):
        engine = request.app.state.engine
        campaign = engine.store.campaign(payload.campaign_id)
        if campaign["mode"] != engine.settings.mode:
            raise ValueError("La campaña pertenece a otro modo de telefonía")
        if engine.active_campaign == payload.campaign_id:
            raise ValueError("La campaña está activa; detenla antes de programar")
        if not engine.store.next_queued(payload.campaign_id):
            raise ValueError("La campaña no tiene contactos pendientes")
        try:
            due = local_instant(payload.local_at, payload.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Fecha u hora inválida: verifica la zona horaria") from error
        if due <= datetime.now(UTC):
            raise ValueError("Elige una fecha y hora futuras")
        sid = uuid4().hex
        try:
            with ops(request).db:
                ops(request).db.execute(
                    "INSERT INTO campaign_schedules "
                    "(id,campaign_id,due_at,timezone,created_by,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        sid,
                        payload.campaign_id,
                        due.isoformat(),
                        payload.timezone,
                        request.state.user["id"],
                        now(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("La campaña ya tiene una programación pendiente") from error
        return {"id": sid, "due_at": due.isoformat()}

    @router.post("/api/manage/schedules/{sid}/cancel")
    async def cancel_schedule(sid: str, request: Request):
        with ops(request).db:
            ops(request).db.execute(
                "UPDATE campaign_schedules SET state='cancelled' WHERE id=? AND state='pending'",
                (sid,),
            )
        return {"ok": True}

    @router.get("/api/manage/report-schedules")
    async def report_schedules(request: Request):
        return {
            "schedules": ops(request).rows(
                "SELECT * FROM report_schedules ORDER BY created_at DESC"
            ),
            "runs": ops(request).rows(
                "SELECT r.*,s.name FROM report_runs r JOIN "
                "report_schedules s ON s.id=r.schedule_id "
                "ORDER BY r.created_at DESC LIMIT 100"
            ),
        }

    @router.post("/api/manage/report-schedules")
    async def save_report_schedule(payload: ReportInput, request: Request):
        try:
            ZoneInfo(payload.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Zona horaria inválida") from error
        row = payload.model_dump()
        rid = payload.id or uuid4().hex
        with ops(request).db:
            ops(request).db.execute(
                """INSERT INTO report_schedules VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,cadence=excluded.cadence,
                local_time=excluded.local_time,weekday=excluded.weekday,timezone=excluded.timezone,
                format=excluded.format,period_days=excluded.period_days,mode=excluded.mode,
                enabled=excluded.enabled,next_run=excluded.next_run""",
                (
                    rid,
                    payload.name,
                    payload.cadence,
                    payload.local_time,
                    payload.weekday,
                    payload.timezone,
                    payload.format,
                    payload.period_days,
                    payload.mode,
                    int(payload.enabled),
                    next_report(row),
                    request.state.user["id"],
                    now(),
                ),
            )
        return {"id": rid}

    @router.get("/api/manage/report-runs/{rid}/download")
    async def report_download(rid: str, request: Request):
        row = (
            ops(request)
            .db.execute("SELECT * FROM report_runs WHERE id=? AND status='ready'", (rid,))
            .fetchone()
        )
        if not row:
            raise KeyError(rid)
        path = request.app.state.automation.report_dir / row["filename"]
        if not path.is_file():
            raise KeyError(rid)
        ops(request).audit(request.state.user, "report.download", rid)
        return FileResponse(path, filename="blaster-" + row["created_at"][:10] + path.suffix)

    @router.get("/api/manage/alerts")
    async def alerts(request: Request):
        return ops(request).rows("SELECT * FROM alerts ORDER BY created_at DESC LIMIT 200")

    @router.post("/api/manage/alerts/{aid}/acknowledge")
    async def acknowledge(aid: str, request: Request):
        with ops(request).db:
            ops(request).db.execute(
                "UPDATE alerts SET acknowledged_at=?,acknowledged_by=? WHERE id=?",
                (now(), request.state.user["id"], aid),
            )
        return {"ok": True}

    @router.get("/api/recordings/{jid}")
    async def recording(jid: str, request: Request):
        row = (
            ops(request)
            .db.execute("SELECT * FROM recordings WHERE job_id=? AND status='ready'", (jid,))
            .fetchone()
        )
        if not row:
            raise KeyError(jid)
        path = request.app.state.engine.recordings.directory / (jid + ".ogg")
        if not path.is_file():
            raise KeyError(jid)
        ops(request).audit(request.state.user, "recording.listen", jid)
        return FileResponse(
            path, media_type="audio/ogg", filename=jid + ".ogg", content_disposition_type="inline"
        )

    return router
