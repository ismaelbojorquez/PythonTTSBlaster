from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from blaster.models import TERMINAL, CampaignInput, render_message
from blaster.retries import RetryPolicy

LATEST_JOB = "NOT EXISTS (SELECT 1 FROM jobs newer WHERE newer.contact_id=j.contact_id " \
    "AND newer.attempt_number>j.attempt_number)"


def now() -> str:
    return datetime.now(UTC).isoformat()


def agent_settings(row) -> dict:
    item = dict(row)
    item["agent_numbers"] = json.loads(item["agent_numbers"]) or (
        [item["agent_number"]] if item["agent_number"] else []
    )
    if "retry_policy" in item:
        item["retry_policy"] = RetryPolicy.model_validate_json(item["retry_policy"]).model_dump()
    return item


class Store:
    """SQLite is accessed only from the application's asyncio thread."""

    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, template TEXT NOT NULL,
                agent_number TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                mode TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                phone TEXT NOT NULL, variables TEXT NOT NULL, message TEXT NOT NULL,
                status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
                started_at TEXT, ended_at TEXT, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS jobs_campaign_status ON jobs(campaign_id, status);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                status TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
            );
        """)
        self._migrate_analytics(path)
        from blaster.operations import migrate

        migrate(self.db, path)
        self._migrate_countries(path)
        self._migrate_agent_pool(path)
        from blaster.campaign_history import CampaignHistory
        from blaster.campaign_history import migrate as migrate_executions

        migrate_executions(self.db, path)
        self.history = CampaignHistory(self)
        from blaster.retries import Retries
        from blaster.retries import migrate as migrate_retries

        migrate_retries(self.db, path)
        self.retries = Retries(self)
        from blaster.traceability import migrate as migrate_traceability

        migrate_traceability(self.db, path)
        from blaster.amd_calibration import migrate as migrate_amd_calibration

        migrate_amd_calibration(self.db, path)

    def _migrate_agent_pool(self, path: Path) -> None:
        if self.db.execute("PRAGMA user_version").fetchone()[0] >= 4:
            return
        if (
            self.db.execute("SELECT 1 FROM campaigns LIMIT 1").fetchone()
            or self.db.execute("SELECT 1 FROM templates LIMIT 1").fetchone()
        ):
            backup = path.with_name(f"{path.name}.before-agent-pool-{uuid4().hex[:8]}.bak")
            with sqlite3.connect(backup) as target:
                self.db.backup(target)
            backup.chmod(0o600)
        with self.db:
            self.db.execute("BEGIN")
            for table in ("campaigns", "templates"):
                self.db.execute(
                    f"ALTER TABLE {table} ADD COLUMN agent_numbers TEXT NOT NULL DEFAULT '[]'"
                )
                self.db.execute(
                    f"ALTER TABLE {table} ADD COLUMN agent_strategy TEXT "
                    "NOT NULL DEFAULT 'round_robin'"
                )
                self.db.execute(
                    f"ALTER TABLE {table} ADD COLUMN agent_pool_wait REAL NOT NULL DEFAULT 30"
                )
            self.db.execute(
                "ALTER TABLE campaigns ADD COLUMN agent_cursor INTEGER NOT NULL DEFAULT 0"
            )
            self.db.execute("ALTER TABLE call_records ADD COLUMN agent_selected_number TEXT")
            self.db.execute("ALTER TABLE call_records ADD COLUMN agent_strategy TEXT")
            self.db.execute("ALTER TABLE call_records ADD COLUMN agent_pool_wait_seconds REAL")
            self.db.execute("PRAGMA user_version=4")

    def _migrate_countries(self, path: Path) -> None:
        if self.db.execute("PRAGMA user_version").fetchone()[0] >= 3:
            return
        if (
            self.db.execute("SELECT 1 FROM campaigns LIMIT 1").fetchone()
            or self.db.execute("SELECT 1 FROM templates LIMIT 1").fetchone()
        ):
            backup = path.with_name(f"{path.name}.before-countries-{uuid4().hex[:8]}.bak")
            with sqlite3.connect(backup) as target:
                self.db.backup(target)
            backup.chmod(0o600)
        with self.db:
            self.db.execute("BEGIN")
            self.db.execute("ALTER TABLE campaigns ADD COLUMN country TEXT")
            self.db.execute("ALTER TABLE campaigns ADD COLUMN agent_country TEXT")
            self.db.execute("ALTER TABLE templates ADD COLUMN agent_country TEXT")
            self.db.execute("PRAGMA user_version=3")

    def _migrate_analytics(self, path: Path) -> None:
        if self.db.execute("PRAGMA user_version").fetchone()[0] > 8:
            raise RuntimeError("La base requiere una versión más reciente de Blaster")
        if self.db.execute("PRAGMA user_version").fetchone()[0] >= 2:
            return
        exists = self.db.execute("SELECT 1 FROM sqlite_master WHERE name='call_records'").fetchone()
        if not exists and self.db.execute("SELECT 1 FROM jobs LIMIT 1").fetchone():
            backup = path.with_name(f"{path.name}.before-analytics-{uuid4().hex[:8]}.bak")
            with sqlite3.connect(backup) as target:
                self.db.backup(target)
            backup.chmod(0o600)
        self.db.executescript("""
            BEGIN;
            CREATE TABLE IF NOT EXISTS call_records (
                job_id TEXT PRIMARY KEY REFERENCES jobs(id), version INTEGER NOT NULL DEFAULT 1,
                started_at TEXT NOT NULL, finalized_at TEXT, processing_seconds REAL,
                amd_enabled INTEGER NOT NULL, amd_verdict TEXT NOT NULL,
                amd_reason TEXT, amd_elapsed_ms INTEGER, amd_audio_ms INTEGER,
                amd_voiced_ms INTEGER, amd_words INTEGER,
                transfer_requested_at TEXT, transfer_actor TEXT,
                bridged_at TEXT, bridge_ended_at TEXT, bridge_seconds REAL,
                message_started_at TEXT, message_completed_at TEXT,
                tts_ms REAL, replays INTEGER NOT NULL DEFAULT 0,
                end_actor TEXT NOT NULL DEFAULT 'unknown', end_reason TEXT,
                end_evidence TEXT
            );
            CREATE TABLE IF NOT EXISTS call_legs (
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                role TEXT NOT NULL, number TEXT NOT NULL, call_id TEXT,
                created_at TEXT NOT NULL, invite_at TEXT, ringing_at TEXT,
                answered_at TEXT, media_at TEXT, ended_at TEXT,
                sip_code INTEGER, sip_reason TEXT, end_actor TEXT NOT NULL DEFAULT 'unknown',
                end_reason TEXT, end_evidence TEXT,
                pdd_seconds REAL, setup_seconds REAL, connected_seconds REAL, total_seconds REAL,
                UNIQUE(job_id, role)
            );
            CREATE TABLE IF NOT EXISTS call_events (
                id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                leg_id TEXT REFERENCES call_legs(id), kind TEXT NOT NULL,
                created_at TEXT NOT NULL, data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS calls_started ON call_records(started_at);
            CREATE INDEX IF NOT EXISTS jobs_started ON jobs(started_at);
            CREATE INDEX IF NOT EXISTS call_events_job ON call_events(job_id, id);
            CREATE INDEX IF NOT EXISTS events_job ON events(job_id, id);
            PRAGMA user_version=1;
            COMMIT;
        """)

    def begin_call(self, jid: str, amd_enabled: bool) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO call_records(job_id,started_at,amd_enabled,amd_verdict) "
                "VALUES(?,?,?,?)",
                (jid, now(), amd_enabled, "pending" if amd_enabled else "disabled"),
            )

    def update_call(self, jid: str, **fields) -> None:
        self._update("call_records", "job_id", jid, fields)

    def message_time(self, jid: str, *, completed: bool = False) -> None:
        column = "message_completed_at" if completed else "message_started_at"
        with self.db:
            self.db.execute(
                f"UPDATE call_records SET {column}=COALESCE({column},?) WHERE job_id=?",
                (now(), jid),
            )

    def _update(self, table, key, value, fields):
        # Column names come only from application code, never HTTP parameters.
        if fields:
            with self.db:
                self.db.execute(
                    f"UPDATE {table} SET {','.join(f'{name}=?' for name in fields)} WHERE {key}=?",
                    (*fields.values(), value),
                )

    def add_leg(self, jid, leg):
        with self.db:
            self.db.execute(
                "INSERT INTO call_legs(id,job_id,role,number,created_at,trunk_id) "
                "VALUES(?,?,?,?,?,?)",
                (leg.id, jid, leg.role, leg.number, now(), getattr(leg, "trunk_id", None)),
            )

    def call_event(self, jid, lid, event, fields=None):
        with self.db:
            if fields:
                self.db.execute(
                    f"UPDATE call_legs SET {','.join(f'{name}=?' for name in fields)} WHERE id=?",
                    (*fields.values(), lid),
                )
            self.db.execute(
                "INSERT INTO call_events(job_id,leg_id,kind,created_at,data) VALUES(?,?,?,?,?)",
                (jid, lid, event.kind, event.at, json.dumps(event.data, ensure_ascii=False)),
            )

    def recover(self) -> None:
        placeholders = ",".join("?" for _ in TERMINAL)
        ids = self.db.execute(
            f"SELECT id FROM jobs WHERE status NOT IN ({placeholders}, 'queued')",
            tuple(TERMINAL),
        ).fetchall()
        for row in ids:
            self.transition(row["id"], "interrupted", "La aplicación se cerró durante la llamada")
        with self.db:
            # A crash supplies no observed disconnect time: keep durations NULL.
            self.db.execute(
                """
                UPDATE call_records SET finalized_at=?, end_reason='process_interrupted',
                end_evidence='startup_recovery'
                WHERE finalized_at IS NULL
            """,
                (now(),),
            )
            self.db.execute("UPDATE campaigns SET status='paused' WHERE status='running'")
        self.retries.reconcile()

    def create_campaign(
        self, payload: CampaignInput, mode: str = "simulation", *, schedule: dict | None = None
    ) -> str:
        cid, timestamp = uuid4().hex, now()
        with self.db:
            self.db.execute(
                "INSERT INTO campaigns "
                "(id,name,template,agent_number,status,created_at,mode,country,agent_country,"
                "agent_numbers,agent_strategy,agent_pool_wait,retry_policy) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    cid,
                    payload.name,
                    payload.template,
                    payload.agent_number,
                    "draft",
                    timestamp,
                    mode,
                    payload.country,
                    payload.agent_country,
                    json.dumps(payload.agent_numbers),
                    payload.agent_strategy,
                    payload.agent_pool_wait,
                    payload.retry_policy.model_dump_json(),
                ),
            )
            self.db.executemany(
                """
                INSERT INTO jobs
                (id,campaign_id,phone,credit_id,variables,message,status,updated_at)
                VALUES (?,?,?,?,?,?,'queued',?)
            """,
                [
                    (
                        uuid4().hex,
                        cid,
                        c.phone,
                        c.credit_id,
                        json.dumps(c.variables, ensure_ascii=False),
                        render_message(
                            payload.template,
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
                        timestamp,
                    )
                    for c in payload.contacts
                ],
            )
            if schedule:
                self.db.execute(
                    "INSERT INTO campaign_schedules "
                    "(id,campaign_id,due_at,timezone,created_by,created_at) VALUES(?,?,?,?,?,?)",
                    (uuid4().hex, cid, schedule["due_at"], schedule["timezone"],
                     schedule.get("created_by"), timestamp),
                )
        return cid

    def campaigns(self) -> list[dict]:
        result = []
        for row in self.db.execute("SELECT * FROM campaigns ORDER BY created_at DESC"):
            campaign = agent_settings(row)
            campaign["counts"] = dict(
                self.db.execute(
                    f"SELECT status, COUNT(*) FROM jobs j WHERE campaign_id=? "
                    f"AND {LATEST_JOB} GROUP BY status",
                    (campaign["id"],),
                ).fetchall()
            )
            campaign["total"] = sum(campaign["counts"].values())
            campaign["retry_summary"] = dict(self.db.execute(
                "SELECT COUNT(CASE WHEN started_at IS NOT NULL THEN 1 END) AS attempts,"
                "COUNT(CASE WHEN status='queued' AND attempt_number>1 THEN 1 END) AS pending,"
                "MIN(CASE WHEN status='queued' AND attempt_number>1 THEN available_at END) "
                "AS next_at FROM jobs WHERE campaign_id=?", (campaign["id"],),
            ).fetchone())
            campaign["schedule"] = self.pending_schedule(campaign["id"])
            campaign["display_status"] = "scheduled" if campaign["schedule"] else campaign["status"]
            campaign["lineage"] = self.history.lineage(campaign["id"])
            result.append(campaign)
        return result

    def campaign(self, cid: str) -> dict:
        row = self.db.execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone()
        if row is None:
            raise KeyError("Campaña no encontrada")
        return agent_settings(row)

    def pending_schedule(self, cid: str) -> dict | None:
        row = self.db.execute(
            "SELECT id,due_at,timezone,state FROM campaign_schedules "
            "WHERE campaign_id=? AND state='pending'", (cid,),
        ).fetchone()
        return dict(row) if row else None

    def set_agent_cursor(self, cid: str, cursor: int):
        with self.db:
            self.db.execute("UPDATE campaigns SET agent_cursor=? WHERE id=?", (cursor, cid))

    def set_campaign_status(self, cid: str, status: str) -> None:
        with self.db:
            self.db.execute("UPDATE campaigns SET status=? WHERE id=?", (status, cid))

    def jobs(self, cid: str, limit: int = 200, offset: int = 0, *, latest=True) -> list[dict]:
        rows = self.db.execute(
            "SELECT j.*,"
            "(SELECT l.trunk_id FROM call_legs l WHERE l.job_id=j.id AND l.role='customer' "
            "ORDER BY l.created_at DESC LIMIT 1) AS customer_trunk_id,"
            "(SELECT t.name FROM call_legs l LEFT JOIN trunks t ON t.id=l.trunk_id "
            "WHERE l.job_id=j.id AND l.role='customer' "
            "ORDER BY l.created_at DESC LIMIT 1) AS customer_trunk_name,"
            "(SELECT l.trunk_id FROM call_legs l WHERE l.job_id=j.id AND l.role='agent' "
            "ORDER BY l.created_at DESC LIMIT 1) AS agent_trunk_id,"
            "(SELECT t.name FROM call_legs l LEFT JOIN trunks t ON t.id=l.trunk_id "
            "WHERE l.job_id=j.id AND l.role='agent' "
            "ORDER BY l.created_at DESC LIMIT 1) AS agent_trunk_name "
            "FROM jobs j WHERE campaign_id=? "
            + (f"AND {LATEST_JOB} " if latest else "")
            + "ORDER BY (SELECT rowid FROM jobs root WHERE root.id=j.contact_id),"
            "attempt_number LIMIT ? OFFSET ?",
            (cid, limit, offset),
        )
        return [{**dict(row), "variables": json.loads(row["variables"])} for row in rows]

    def next_queued(self, cid: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM jobs WHERE campaign_id=? AND status='queued' "
            "AND (available_at IS NULL OR available_at<=?) "
            "ORDER BY COALESCE(available_at,updated_at),rowid LIMIT 1", (cid, now()),
        ).fetchone()
        return dict(row) if row else None

    def has_queued(self, cid: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM jobs WHERE campaign_id=? AND status='queued' LIMIT 1", (cid,),
        ).fetchone() is not None

    def queued_numbers(self, cid: str) -> list[str]:
        return [
            row["phone"]
            for row in self.db.execute(
                "SELECT phone FROM jobs WHERE campaign_id=? AND status='queued'", (cid,)
            )
        ]

    def missing_identifiers(self, cid: str) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM jobs WHERE campaign_id=? "
            "AND (TRIM(phone)='' OR TRIM(credit_id)='')",
            (cid,),
        ).fetchone()[0]

    def transition(self, jid: str, status: str, detail: str = "") -> None:
        timestamp = now()
        with self.db:
            self.db.execute(
                """
                UPDATE jobs SET status=?, detail=?, updated_at=?,
                started_at=CASE WHEN ?='dialing' THEN COALESCE(started_at,?) ELSE started_at END,
                ended_at=CASE WHEN ? THEN ? ELSE ended_at END WHERE id=?
            """,
                (status, detail, timestamp, status, timestamp, status in TERMINAL, timestamp, jid),
            )
            self.db.execute(
                "INSERT INTO events (job_id,status,detail,created_at) VALUES (?,?,?,?)",
                (jid, status, detail, timestamp),
            )

    def events(self, jid: str) -> list[dict]:
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM events WHERE job_id=? ORDER BY id DESC LIMIT 100",
                (jid,),
            )
        ]

    def cancel_queued(self, cid: str) -> None:
        with self.db:
            pending = self.db.execute(
                "SELECT id,contact_id,attempt_number FROM jobs "
                "WHERE campaign_id=? AND status='queued' AND attempt_number>1", (cid,),
            ).fetchall()
            for job in pending:
                self.db.execute(
                    "INSERT INTO events(job_id,status,detail,created_at) "
                    "VALUES(?,'cancelled','Reintento cancelado: campaña detenida',?)",
                    (job["id"], now()),
                )
                self.db.execute(
                    "INSERT INTO audit(created_at,actor_name,action,target,detail) "
                    "VALUES(?,'sistema','call.retry_cancelled',?,?)",
                    (now(), job["id"], json.dumps({"campaign_id": cid, **dict(job)})),
                )
            self.db.execute(
                """
                UPDATE jobs SET status='cancelled',detail='Campaña detenida',ended_at=?,
                updated_at=? WHERE campaign_id=? AND status='queued'
            """,
                (now(), now(), cid),
            )

    def close(self) -> None:
        self.db.close()
