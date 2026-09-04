"""Durable local scheduling. One campaign at a time, no duplicate report runs."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from blaster.analytics import Filters
from blaster.reports import cdr_csv, excel_report


def local_instant(value, timezone):
    zone = ZoneInfo(timezone)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    aware = parsed.replace(tzinfo=zone)
    if aware.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != parsed:
        raise ValueError("Esta hora no existe por un cambio de horario")
    if aware.utcoffset() != parsed.replace(tzinfo=zone, fold=1).utcoffset():
        raise ValueError("Hora ambigua: indica una fecha ISO con desplazamiento UTC")
    return aware.astimezone(UTC)


def next_report(row, after=None):
    after = after or datetime.now(UTC)
    zone = ZoneInfo(row["timezone"])
    local = after.astimezone(zone)
    clock = time.fromisoformat(row["local_time"])
    for offset in range(9):
        day = local.date() + timedelta(days=offset)
        if row["cadence"] == "weekly" and day.weekday() != row["weekday"]:
            continue
        candidate = datetime.combine(day, clock, zone)
        # Spring gap: use the first representable wall time after the gap.
        candidate = candidate.astimezone(UTC).astimezone(zone)
        if candidate.astimezone(UTC) > after:
            return candidate.astimezone(UTC).isoformat()
    raise ValueError("No se pudo calcular la siguiente ejecución")


class Automation:
    def __init__(self, settings, engine, analytics, report_lock):
        self.settings, self.engine, self.ops = settings, engine, engine.ops
        self.analytics, self.report_lock = analytics, report_lock
        self.task = self.report_task = None
        self.last_maintenance = 0
        self.down_since = {}
        self.report_dir = settings.data_dir / "reports"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.chmod(0o700)

    async def start(self):
        with self.ops.db:
            self.ops.db.execute(
                "UPDATE report_runs SET status='failed',detail=? WHERE status='running'",
                ("Proceso interrumpido; no se duplicó el envío",),
            )
        self.task = asyncio.create_task(self.run())

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.report_task:
            await self.report_task

    async def run(self):
        while True:
            try:
                if self.settings.automation.enabled:
                    await self.tick()
                elif datetime.now(UTC).timestamp() - self.last_maintenance > 3600:
                    self.last_maintenance = datetime.now(UTC).timestamp()
                    self.engine.recordings.prune()
            except Exception:
                self.ops.alert(
                    "scheduler_error",
                    "Error de programación",
                    "No se pudo completar una revisión de tareas. Se volverá a intentar.",
                    "error",
                )
            await asyncio.sleep(self.settings.automation.poll_seconds)

    async def tick(self, instant=None):
        instant = instant or datetime.now(UTC)
        stamp = instant.isoformat()
        for row in self.ops.rows(
            "SELECT * FROM campaign_schedules WHERE state='pending' "
            "AND due_at<=? ORDER BY due_at,created_at",
            (stamp,),
        ):
            due = datetime.fromisoformat(row["due_at"])
            state, detail = None, ""
            if instant - due > timedelta(minutes=self.settings.automation.late_schedule_minutes):
                state, detail = "missed", "Horario vencido; requiere reprogramación"
            elif not self.engine.store.next_queued(row["campaign_id"]):
                state, detail = "skipped", "Sin contactos pendientes"
            elif (
                self.engine.active_campaign
                or not self.engine.telephony.available
                or self.engine.router.reloading
                or not any(self.engine.router.ready(t) for t in self.engine.router.profiles)
            ):
                continue
            else:
                try:
                    self.engine.start_campaign(row["campaign_id"])
                    state, detail = "started", "Campaña iniciada por programación"
                except ValueError as error:
                    state, detail = "failed", str(error)
            with self.ops.db:
                self.ops.db.execute(
                    "UPDATE campaign_schedules SET state=?,detail=?,started_at=? "
                    "WHERE id=? AND state='pending'",
                    (state, detail, stamp if state == "started" else None, row["id"]),
                )
            self.ops.audit({}, "schedule." + state, row["campaign_id"], {"schedule_id": row["id"]})
            if state in {"missed", "failed"}:
                self.ops.alert("schedule_" + row["id"], "Campaña programada sin iniciar", detail)
            if state == "started":
                break
        if self.report_task is None or self.report_task.done():
            rows = self.ops.rows(
                "SELECT * FROM report_schedules WHERE enabled=1 AND next_run<=? "
                "ORDER BY next_run LIMIT 1",
                (stamp,),
            )
            if rows:
                row = rows[0]
                run_id = uuid4().hex
                with self.ops.db:
                    inserted = self.ops.db.execute(
                        "INSERT OR IGNORE INTO report_runs "
                        "(id,schedule_id,due_at,created_at,status) VALUES(?,?,?,?,?)",
                        (run_id, row["id"], row["next_run"], stamp, "running"),
                    ).rowcount
                    self.ops.db.execute(
                        "UPDATE report_schedules SET next_run=? WHERE id=?",
                        (next_report(row, instant), row["id"]),
                    )
                if inserted:
                    self.report_task = asyncio.create_task(self.generate(row, run_id))
        self.monitor(instant)
        if instant.timestamp() - self.last_maintenance > 3600:
            self.last_maintenance = instant.timestamp()
            self.engine.recordings.prune()
            cutoff = (
                instant - timedelta(days=self.settings.automation.report_retention_days)
            ).isoformat()
            for row in self.ops.rows(
                "SELECT * FROM report_runs WHERE status='ready' AND created_at<?", (cutoff,)
            ):
                with contextlib.suppress(FileNotFoundError):
                    (self.report_dir / row["filename"]).unlink()
                with self.ops.db:
                    self.ops.db.execute(
                        "UPDATE report_runs SET status='expired',filename=NULL WHERE id=?",
                        (row["id"],),
                    )

    async def generate(self, row, run_id):
        def build():
            due = datetime.fromisoformat(row["next_run"]).astimezone(ZoneInfo(row["timezone"]))
            end = due.date() - timedelta(days=1)
            selected = Filters(
                date_from=end - timedelta(days=row["period_days"] - 1),
                date_to=end,
                mode=row["mode"],
                timezone=row["timezone"],
            )
            rows, summary, events = self.analytics.report_data(
                selected, self.settings.report_max_rows
            )
            return (
                excel_report(rows, summary, events, selected)
                if row["format"] == "xlsx"
                else cdr_csv(rows)
            )

        try:
            async with self.report_lock:
                content = await asyncio.to_thread(build)
                name = run_id + "." + row["format"]
                path = self.report_dir / name
                await asyncio.to_thread(path.write_bytes, content)
                path.chmod(0o600)
            with self.ops.db:
                self.ops.db.execute(
                    "UPDATE report_runs SET status='ready',filename=?,size_bytes=? WHERE id=?",
                    (name, len(content), run_id),
                )
            self.ops.audit({}, "report.generated", run_id, {"schedule_id": row["id"]})
            self.ops.alert(
                "report_ready_" + run_id, "Reporte automático disponible", row["name"], "info"
            )
        except Exception as error:
            detail = (
                str(error) if isinstance(error, ValueError) else "No se pudo generar el archivo"
            )
            with self.ops.db:
                self.ops.db.execute(
                    "UPDATE report_runs SET status='failed',detail=? WHERE id=?", (detail, run_id)
                )
            self.ops.alert(
                "report_failed_" + run_id, "Falló un reporte automático", detail, "error"
            )

    def monitor(self, instant):
        for trunk in self.engine.router.snapshot():
            tid = trunk["id"]
            state = (trunk["available"], trunk["status"])
            if self.engine.router.last_state.get(tid) != state:
                self.engine.router.last_state[tid] = state
                self.ops.trunk_event(tid, "status", trunk["status"])
            if trunk["enabled"] and not trunk["available"]:
                since = self.down_since.setdefault(tid, instant)
                if (
                    instant - since
                ).total_seconds() >= self.settings.automation.trunk_alert_seconds:
                    self.ops.alert(
                        "trunk_" + tid, "Troncal sin disponibilidad", trunk["name"], "error"
                    )
            else:
                self.down_since.pop(tid, None)
                self.ops.resolve("trunk_" + tid)
        cutoff = (instant - timedelta(minutes=15)).isoformat()
        row = self.ops.db.execute(
            "SELECT COUNT(*) n,SUM(status='failed') failures FROM jobs "
            "WHERE ended_at>=? AND status NOT IN ('cancelled','interrupted')",
            (cutoff,),
        ).fetchone()
        cfg = self.settings.automation
        if (
            row["n"] >= cfg.failure_alert_min_calls
            and (row["failures"] or 0) * 100 / row["n"] >= cfg.failure_alert_percent
        ):
            self.ops.alert(
                "failure_rate",
                "Aumentaron las llamadas fallidas",
                f"{row['failures']} de {row['n']} llamadas en los últimos 15 minutos",
            )
        else:
            self.ops.resolve("failure_rate")
