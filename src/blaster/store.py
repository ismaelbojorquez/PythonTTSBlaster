from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from blaster.models import TERMINAL, CampaignInput, render_message


def now() -> str:
    return datetime.now(UTC).isoformat()


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

    def _migrate_analytics(self, path: Path) -> None:
        if self.db.execute("PRAGMA user_version").fetchone()[0] > 2:
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

    def create_campaign(self, payload: CampaignInput, mode: str = "simulation") -> str:
        cid, timestamp = uuid4().hex, now()
        with self.db:
            self.db.execute(
                "INSERT INTO campaigns VALUES (?,?,?,?,?,?,?)",
                (
                    cid,
                    payload.name,
                    payload.template,
                    payload.agent_number,
                    "draft",
                    timestamp,
                    mode,
                ),
            )
            self.db.executemany(
                """
                INSERT INTO jobs (id,campaign_id,phone,variables,message,status,updated_at)
                VALUES (?,?,?,?,?,'queued',?)
            """,
                [
                    (
                        uuid4().hex,
                        cid,
                        c.phone,
                        json.dumps(c.variables, ensure_ascii=False),
                        render_message(payload.template, {**c.variables, "telefono": c.phone}),
                        timestamp,
                    )
                    for c in payload.contacts
                ],
            )
        return cid

    def campaigns(self) -> list[dict]:
        result = []
        for row in self.db.execute("SELECT * FROM campaigns ORDER BY created_at DESC"):
            campaign = dict(row)
            campaign["counts"] = dict(
                self.db.execute(
                    "SELECT status, COUNT(*) FROM jobs WHERE campaign_id=? GROUP BY status",
                    (campaign["id"],),
                ).fetchall()
            )
            campaign["total"] = sum(campaign["counts"].values())
            result.append(campaign)
        return result

    def campaign(self, cid: str) -> dict:
        row = self.db.execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone()
        if row is None:
            raise KeyError("Campaña no encontrada")
        return dict(row)

    def set_campaign_status(self, cid: str, status: str) -> None:
        with self.db:
            self.db.execute("UPDATE campaigns SET status=? WHERE id=?", (status, cid))

    def jobs(self, cid: str, limit: int = 200, offset: int = 0) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM jobs WHERE campaign_id=? ORDER BY rowid LIMIT ? OFFSET ?",
            (cid, limit, offset),
        )
        return [{**dict(row), "variables": json.loads(row["variables"])} for row in rows]

    def next_queued(self, cid: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM jobs WHERE campaign_id=? AND status='queued' ORDER BY rowid LIMIT 1",
            (cid,),
        ).fetchone()
        return dict(row) if row else None

    def queued_numbers(self, cid: str) -> list[str]:
        return [
            row["phone"]
            for row in self.db.execute(
                "SELECT phone FROM jobs WHERE campaign_id=? AND status='queued'", (cid,)
            )
        ]

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
            self.db.execute(
                """
                UPDATE jobs SET status='cancelled',detail='Campaña detenida',ended_at=?,
                updated_at=? WHERE campaign_id=? AND status='queued'
            """,
                (now(), now(), cid),
            )

    def close(self) -> None:
        self.db.close()
