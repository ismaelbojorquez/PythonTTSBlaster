"""Persistent operations, schedules and audit. Accessed on the application loop."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from blaster.store import now


def migrate(db, path: Path):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version >= 2:
        return
    if db.execute("SELECT 1 FROM campaigns LIMIT 1").fetchone():
        backup = path.with_name(path.name + ".before-operations-" + uuid4().hex[:8] + ".bak")
        with sqlite3.connect(backup) as target:
            db.backup(target)
        backup.chmod(0o600)
    db.executescript("""
        BEGIN;
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','operator','analyst')),
            enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            expires_at TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, actor_id TEXT,
            actor_name TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL,
            detail TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trunks (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL,
            priority INTEGER NOT NULL, weight INTEGER NOT NULL, channels INTEGER NOT NULL,
            calls_per_second REAL NOT NULL, profile TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trunk_events (
            id INTEGER PRIMARY KEY, trunk_id TEXT NOT NULL, created_at TEXT NOT NULL,
            kind TEXT NOT NULL, detail TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS templates (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, message TEXT NOT NULL,
            agent_number TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT
        );
        CREATE TABLE IF NOT EXISTS campaign_schedules (
            id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
            due_at TEXT NOT NULL, timezone TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
            created_by TEXT, created_at TEXT NOT NULL, started_at TEXT,
            detail TEXT NOT NULL DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_pending_schedule ON campaign_schedules(campaign_id)
            WHERE state='pending';
        CREATE TABLE IF NOT EXISTS report_schedules (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, cadence TEXT NOT NULL,
            local_time TEXT NOT NULL, weekday INTEGER NOT NULL, timezone TEXT NOT NULL,
            format TEXT NOT NULL, period_days INTEGER NOT NULL, mode TEXT NOT NULL,
            enabled INTEGER NOT NULL, next_run TEXT NOT NULL, created_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS report_runs (
            id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL REFERENCES report_schedules(id),
            due_at TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL,
            filename TEXT, size_bytes INTEGER, detail TEXT NOT NULL DEFAULT '',
            UNIQUE(schedule_id,due_at)
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id TEXT PRIMARY KEY, dedupe_key TEXT NOT NULL, severity TEXT NOT NULL,
            title TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL,
            resolved_at TEXT, acknowledged_at TEXT, acknowledged_by TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_alert ON alerts(dedupe_key)
            WHERE resolved_at IS NULL;
        CREATE TABLE IF NOT EXISTS recordings (
            job_id TEXT PRIMARY KEY REFERENCES jobs(id), status TEXT NOT NULL,
            filename TEXT, started_at TEXT NOT NULL, ended_at TEXT, evidence TEXT NOT NULL,
            size_bytes INTEGER, duration_seconds REAL, detail TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS schedule_due ON campaign_schedules(state,due_at);
        CREATE INDEX IF NOT EXISTS audit_date ON audit(created_at);
        ALTER TABLE call_legs ADD COLUMN trunk_id TEXT;
        PRAGMA user_version=2;
        COMMIT;
    """)


class Operations:
    def __init__(self, store):
        self.store, self.db = store, store.db

    def audit(self, actor, action, target="", detail=None):
        with self.db:
            self.db.execute(
                "INSERT INTO audit(created_at,actor_id,actor_name,action,target,detail) "
                "VALUES(?,?,?,?,?,?)",
                (
                    now(),
                    actor.get("id"),
                    actor.get("username", "sistema"),
                    action,
                    str(target),
                    json.dumps(detail or {}, ensure_ascii=False),
                ),
            )

    def alert(self, key, title, detail, severity="warning"):
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO alerts "
                "(id,dedupe_key,severity,title,detail,created_at) VALUES(?,?,?,?,?,?)",
                (uuid4().hex, key, severity, title, detail, now()),
            )

    def resolve(self, key):
        with self.db:
            self.db.execute(
                "UPDATE alerts SET resolved_at=? WHERE dedupe_key=? AND resolved_at IS NULL",
                (now(), key),
            )

    def trunk_event(self, tid, kind, detail):
        with self.db:
            self.db.execute(
                "INSERT INTO trunk_events(trunk_id,created_at,kind,detail) VALUES(?,?,?,?)",
                (tid, now(), kind, detail),
            )

    def rows(self, sql, args=()):
        return [dict(row) for row in self.db.execute(sql, args)]
