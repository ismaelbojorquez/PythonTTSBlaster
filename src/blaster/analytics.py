"""Read-only reporting snapshots. Unknown historical measurements stay NULL."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from blaster.models import TERMINAL

STATUS_LABELS = {
    "completed": "Finalizada",
    "machine": "Buzón probable",
    "amd_unknown": "AMD incierto",
    "no_answer": "Sin respuesta",
    "no_input": "Sin selección",
    "busy": "Ocupada",
    "failed": "Fallida",
    "cancelled": "Cancelada",
    "interrupted": "Interrumpida",
    "dialing": "Marcando",
    "detecting": "Analizando saludo",
    "synthesizing": "Generando voz",
    "playing": "Reproduciendo",
    "menu": "Esperando opción",
    "agent_dialing": "Marcando agente",
    "bridged": "Con agente",
    "queued": "Pendiente",
}
ACTOR_LABELS = {
    "customer": "Cliente (tramo remoto)",
    "agent": "Agente (tramo remoto)",
    "system": "Sistema",
    "operator": "Operador local",
    "trunk": "Troncal",
    "unknown": "Desconocido",
}
AMD_LABELS = {
    "human": "Humano probable",
    "machine": "Buzón probable",
    "unknown": "Incierto",
    "pending": "Sin resultado",
    "disabled": "Desactivado",
    "unmeasured": "Sin medición histórica",
}


@dataclass(frozen=True)
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    campaign_id: str | None = None
    mode: str = "sip"
    status: str | None = None
    search: str = ""
    timezone: str = "America/Mexico_City"

    def where(self):
        parts, values = ["j.started_at IS NOT NULL"], []
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("La fecha inicial debe ser anterior o igual a la final")
        zone = ZoneInfo(self.timezone)
        for day, sign in ((self.date_from, ">="), (self.date_to, "<")):
            if day:
                if sign == "<":
                    day += timedelta(days=1)
                parts.append(f"j.started_at {sign} ?")
                values.append(datetime.combine(day, time(), zone).astimezone(UTC).isoformat())
        if self.mode != "all":
            parts.append("c.mode=?")
            values.append(self.mode)
        if self.campaign_id:
            parts.append("c.id=?")
            values.append(self.campaign_id)
        if self.status:
            parts.append("j.status=?")
            values.append(self.status)
        if self.search:
            parts.append(
                "(j.phone LIKE ? ESCAPE '\\' OR j.id=? OR "
                "json_extract(j.variables,'$.nombre') LIKE ? ESCAPE '\\')"
            )
            term = self.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            values.extend((f"%{term}%", self.search, f"%{term}%"))
        return " AND ".join(parts), values


LEG_FIELDS = (
    "trunk_id",
    "id",
    "number",
    "call_id",
    "invite_at",
    "ringing_at",
    "answered_at",
    "media_at",
    "ended_at",
    "sip_code",
    "sip_reason",
    "end_actor",
    "end_reason",
    "end_evidence",
    "pdd_seconds",
    "setup_seconds",
    "connected_seconds",
    "total_seconds",
)
RECORD_FIELDS = (
    "finalized_at",
    "amd_enabled",
    "amd_verdict",
    "amd_reason",
    "amd_elapsed_ms",
    "amd_audio_ms",
    "amd_voiced_ms",
    "amd_words",
    "transfer_requested_at",
    "transfer_actor",
    "bridged_at",
    "bridge_ended_at",
    "bridge_seconds",
    "message_started_at",
    "message_completed_at",
    "tts_ms",
    "replays",
    "end_actor",
    "end_reason",
    "end_evidence",
    "processing_seconds",
)
SELECT = (
    "SELECT j.id,j.campaign_id,j.phone,j.status,j.detail,j.started_at,j.ended_at,"
    "j.variables,c.name AS campaign_name,c.mode,c.agent_number,r.version AS telemetry_version,"
    + ",".join(f"r.{key}" for key in RECORD_FIELDS)
    + ","
    + ",".join(
        f"{alias}.{key} AS {role}_{key}"
        for alias, role in (("cl", "customer"), ("al", "agent"))
        for key in LEG_FIELDS
    )
    + " FROM jobs j JOIN campaigns c ON c.id=j.campaign_id "
    "LEFT JOIN call_records r ON r.job_id=j.id "
    "LEFT JOIN call_legs cl ON cl.job_id=j.id AND cl.role='customer' "
    "LEFT JOIN call_legs al ON al.job_id=j.id AND al.role='agent' "
)


def decorate(row):
    item = dict(row)
    item["contact_name"] = json.loads(item.pop("variables")).get("nombre", "")
    item["coverage"] = "measured" if item["telemetry_version"] else "legacy"
    item["end_actor"] = item["end_actor"] or "unknown"
    item["amd_verdict"] = item["amd_verdict"] or "unmeasured"
    item["status_label"] = STATUS_LABELS.get(item["status"], item["status"])
    item["end_actor_label"] = ACTOR_LABELS.get(item["end_actor"], "Desconocido")
    item["amd_label"] = AMD_LABELS.get(item["amd_verdict"], "Sin resultado")
    return item


def mean(values):
    items = [x for x in values if x is not None]
    return round(sum(items) / len(items), 3) if items else None


class Analytics:
    def __init__(self, path: Path):
        self.path = path

    def connect(self):
        db = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        return db

    def rows(self, db, filters, *, limit=None, offset=0):
        where, values = filters.where()
        sql = SELECT + " WHERE " + where + " ORDER BY j.started_at DESC,j.id"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            values.extend((limit, offset))
        return (decorate(row) for row in db.execute(sql, values))

    def count(self, db, filters):
        where, values = filters.where()
        return db.execute(
            "SELECT COUNT(*) FROM jobs j JOIN campaigns c ON c.id=j.campaign_id WHERE " + where,
            values,
        ).fetchone()[0]

    def calls(self, filters, limit=50, offset=0):
        db = self.connect()
        try:
            db.execute("BEGIN")
            return {
                "total": self.count(db, filters),
                "limit": limit,
                "offset": offset,
                "items": list(self.rows(db, filters, limit=limit, offset=offset)),
            }
        finally:
            db.close()

    def detail(self, jid):
        db = self.connect()
        try:
            db.execute("BEGIN")
            row = db.execute(SELECT + " WHERE j.id=?", (jid,)).fetchone()
            if row is None:
                raise KeyError(jid)
            result = decorate(row)
            recording = db.execute("SELECT * FROM recordings WHERE job_id=?", (jid,)).fetchone()
            result["recording"] = dict(recording) if recording else None
            result["legs"] = [
                dict(x)
                for x in db.execute(
                    "SELECT * FROM call_legs WHERE job_id=? ORDER BY created_at", (jid,)
                )
            ]
            result["events"] = [
                {**dict(x), "data": json.loads(x["data"])}
                for x in db.execute("SELECT * FROM call_events WHERE job_id=? ORDER BY id", (jid,))
            ]
            result["history"] = [
                dict(x)
                for x in db.execute("SELECT * FROM events WHERE job_id=? ORDER BY id", (jid,))
            ]
            return result
        finally:
            db.close()

    def summary(self, filters):
        db = self.connect()
        try:
            return summarize(self.rows(db, filters), filters)
        finally:
            db.close()

    def report_data(self, filters, maximum):
        db = self.connect()
        try:
            db.execute("BEGIN")
            if self.count(db, filters) > maximum:
                raise ValueError(
                    f"El reporte supera {maximum:,} llamadas. Reduce el período "
                    "o selecciona una campaña; no se exportaron datos parciales."
                )
            rows = list(self.rows(db, filters))
            where, values = filters.where()
            events = [
                dict(x)
                for x in db.execute(
                    "SELECT e.* FROM call_events e JOIN jobs j ON j.id=e.job_id "
                    "JOIN campaigns c ON c.id=j.campaign_id WHERE " + where + " ORDER BY e.id",
                    values,
                )
            ]
            by_id = {row["id"]: row for row in rows}
            for row in rows:
                row["_legs"] = []
            for leg in db.execute(
                "SELECT l.* FROM call_legs l JOIN jobs j ON j.id=l.job_id "
                "JOIN campaigns c ON c.id=j.campaign_id WHERE " + where + " ORDER BY l.created_at",
                values,
            ):
                by_id[leg["job_id"]]["_legs"].append(dict(leg))
            return rows, summarize(rows, filters), events
        finally:
            db.close()


def summarize(rows, filters):
    counts = Counter()
    outcomes, actors, amd, codes, hours = (Counter() for _ in range(5))
    days, campaigns = defaultdict(Counter), {}
    durations = defaultdict(lambda: [0.0, 0])
    buckets = Counter({"Menos de 15 s": 0, "15–59 s": 0, "1–3 min": 0, "Más de 3 min": 0})
    zone = ZoneInfo(filters.timezone)
    for row in rows:
        counts["total"] += 1
        tracked = bool(row["telemetry_version"])
        counts["measured"] += tracked
        counts["legacy"] += not tracked
        attempted = bool(row["customer_invite_at"])
        answered = bool(row["customer_answered_at"])
        bridged = bool(row["bridged_at"])
        transfer = bool(row["transfer_requested_at"])
        counts["attempted"] += attempted
        counts["answered"] += answered
        counts["transfer_requested"] += transfer
        counts["agent_answered"] += bool(row["agent_answered_at"])
        counts["bridged"] += bridged
        counts["active"] += row["status"] not in TERMINAL
        counts["message_started"] += bool(row["message_started_at"])
        counts["message_completed"] += bool(row["message_completed_at"])
        outcomes[row["status"]] += 1
        amd[row["amd_verdict"]] += 1
        if row["status"] in TERMINAL:
            actors[row["end_actor"]] += 1
        if row["customer_sip_code"]:
            codes[str(row["customer_sip_code"])] += 1
        local = datetime.fromisoformat(row["started_at"]).astimezone(zone)
        day = days[local.date().isoformat()]
        day.update(total=1, answered=int(answered), bridged=int(bridged))
        hours[str(local.hour)] += 1
        campaign = campaigns.setdefault(
            row["campaign_id"],
            {
                "id": row["campaign_id"],
                "name": row["campaign_name"],
                "mode": row["mode"],
                "total": 0,
                "answered": 0,
                "bridged": 0,
                "machine": 0,
            },
        )
        campaign["total"] += 1
        campaign["answered"] += answered
        campaign["bridged"] += bridged
        campaign["machine"] += row["amd_verdict"] == "machine"
        for key in (
            "customer_pdd_seconds",
            "customer_setup_seconds",
            "customer_connected_seconds",
            "agent_pdd_seconds",
            "agent_setup_seconds",
            "agent_connected_seconds",
            "bridge_seconds",
            "tts_ms",
            "amd_elapsed_ms",
        ):
            value = row[key]
            if value is not None:
                durations[key][0] += value
                durations[key][1] += 1
        value = row["customer_connected_seconds"]
        if value is not None:
            bucket = (
                "Menos de 15 s"
                if value < 15
                else "15–59 s"
                if value < 60
                else ("1–3 min" if value <= 180 else "Más de 3 min")
            )
            buckets[bucket] += 1
    for key in (
        "total",
        "measured",
        "legacy",
        "attempted",
        "answered",
        "transfer_requested",
        "agent_answered",
        "bridged",
        "active",
        "message_started",
        "message_completed",
    ):
        counts.setdefault(key, 0)

    def rate(a, b):
        return round(counts[a] / counts[b], 4) if counts[b] else None

    metrics = {
        key: {"total": round(total, 3), "samples": n, "average": round(total / n, 3)}
        for key, (total, n) in durations.items()
    }
    series = [{"date": day, **dict(values)} for day, values in sorted(days.items())]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "timezone": filters.timezone,
        "counts": dict(counts),
        "answer_rate": rate("answered", "attempted"),
        "transfer_rate": rate("bridged", "transfer_requested"),
        "durations": metrics,
        "outcomes": dict(outcomes),
        "amd": dict(amd),
        "hangup_actors": dict(actors),
        "sip_codes": dict(codes),
        "daily": series,
        "hourly": [{"hour": h, "total": hours[str(h)]} for h in range(24)],
        "duration_buckets": dict(buckets),
        "campaigns": sorted(campaigns.values(), key=lambda x: x["total"], reverse=True),
    }
