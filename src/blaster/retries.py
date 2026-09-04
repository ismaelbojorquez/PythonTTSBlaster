"""Durable per-contact attempts. A retry never reuses a job or its CDR."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

RetryOutcome = Literal["no_answer", "busy", "machine", "amd_unknown", "temporary_error"]


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_attempts: int = Field(default=1, ge=1, le=10, strict=True)
    delay_seconds: int = Field(default=300, ge=1, le=604800, strict=True)
    outcomes: list[RetryOutcome] = Field(
        default_factory=lambda: ["no_answer", "busy", "machine", "amd_unknown"], max_length=5,
    )

    @model_validator(mode="after")
    def valid_outcomes(self):
        self.outcomes = list(dict.fromkeys(self.outcomes))
        if self.max_attempts > 1 and not self.outcomes:
            raise ValueError("Selecciona al menos un resultado que permita reintentar")
        return self


def migrate(db, path):
    if db.execute("PRAGMA user_version").fetchone()[0] >= 6:
        return
    if db.execute("SELECT 1 FROM jobs LIMIT 1").fetchone():
        backup = path.with_name(f"{path.name}.before-retries-{uuid4().hex[:8]}.bak")
        with sqlite3.connect(backup) as target:
            db.backup(target)
        backup.chmod(0o600)
    with db:
        db.execute("BEGIN")
        db.execute("ALTER TABLE campaigns ADD COLUMN retry_policy TEXT NOT NULL DEFAULT '{}'")
        db.execute("ALTER TABLE jobs ADD COLUMN contact_id TEXT REFERENCES jobs(id)")
        db.execute("ALTER TABLE jobs ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1")
        db.execute("ALTER TABLE jobs ADD COLUMN retry_of TEXT REFERENCES jobs(id)")
        db.execute("ALTER TABLE jobs ADD COLUMN available_at TEXT")
        db.execute("UPDATE jobs SET contact_id=id")
        # Legacy insert paths and initial jobs get their own immutable contact root.
        db.execute("CREATE TRIGGER jobs_contact_root AFTER INSERT ON jobs "
                   "WHEN NEW.contact_id IS NULL BEGIN "
                   "UPDATE jobs SET contact_id=NEW.id WHERE id=NEW.id; END")
        db.execute("CREATE UNIQUE INDEX jobs_contact_attempt "
                   "ON jobs(campaign_id,contact_id,attempt_number)")
        db.execute("CREATE UNIQUE INDEX jobs_retry_parent ON jobs(retry_of)")
        db.execute("CREATE INDEX jobs_due ON jobs(campaign_id,status,available_at)")
        db.execute("CREATE TABLE retry_decisions ("
                   "job_id TEXT PRIMARY KEY REFERENCES jobs(id), reason TEXT NOT NULL,"
                   "next_job_id TEXT REFERENCES jobs(id), policy TEXT NOT NULL,"
                   "created_at TEXT NOT NULL)")
        db.execute("PRAGMA user_version=6")


class Retries:
    def __init__(self, store):
        self.store, self.db = store, store.db

    def reconcile(self, cid=None):
        """Finish a decision missed by a crash, without making any phone calls."""
        rows = self.db.execute(
            "SELECT j.id FROM jobs j JOIN campaigns c ON c.id=j.campaign_id "
            "JOIN call_records r ON r.job_id=j.id "
            "LEFT JOIN retry_decisions d ON d.job_id=j.id "
            "WHERE d.job_id IS NULL AND r.finalized_at IS NOT NULL "
            "AND c.status IN ('running','paused') "
            "AND COALESCE(json_extract(c.retry_policy,'$.max_attempts'),1)>1 "
            + ("AND c.id=? " if cid else ""),
            (cid,) if cid else (),
        ).fetchall()
        for row in rows:
            self.plan(row["id"])

    def plan(self, jid):
        row = self.db.execute(
            "SELECT j.*,c.retry_policy,c.status AS campaign_status,r.finalized_at,"
            "r.end_reason AS call_end_reason "
            "FROM jobs j JOIN campaigns c ON c.id=j.campaign_id "
            "LEFT JOIN call_records r ON r.job_id=j.id WHERE j.id=?", (jid,),
        ).fetchone()
        if not row or not row["finalized_at"]:
            return None
        policy = RetryPolicy.model_validate_json(row["retry_policy"])
        if policy.max_attempts == 1:
            return None
        existing = self.db.execute(
            "SELECT next_job_id FROM retry_decisions WHERE job_id=?", (jid,),
        ).fetchone()
        if existing:
            return existing["next_job_id"]
        outcome = row["status"]
        if outcome == "failed":
            leg = self.db.execute(
                "SELECT sip_code,answered_at FROM call_legs WHERE job_id=? AND role='customer'",
                (jid,),
            ).fetchone()
            if leg and not leg["answered_at"] and leg["sip_code"] in {500, 502, 503, 504}:
                outcome = "temporary_error"
        # SIP 200 alone does not identify a person. Playback is a conservative stop:
        # AMD-disabled / unknown-continue recipients must not be repeatedly contacted.
        human = self.db.execute(
            "SELECT 1 FROM jobs j JOIN call_records r ON r.job_id=j.id "
            "WHERE j.contact_id=? AND (r.amd_verdict='human' "
            "OR r.message_started_at IS NOT NULL OR r.transfer_requested_at IS NOT NULL "
            "OR r.bridged_at IS NOT NULL OR r.replays>0 "
            "OR EXISTS(SELECT 1 FROM call_events e WHERE e.job_id=j.id AND e.kind='dtmf')) "
            "LIMIT 1", (row["contact_id"],),
        ).fetchone()
        unclosed = self.db.execute(
            "SELECT 1 FROM call_legs WHERE job_id=? AND role LIKE 'customer%' "
            "AND invite_at IS NOT NULL AND ended_at IS NULL LIMIT 1", (jid,),
        ).fetchone()
        reason = "scheduled"
        if human:
            reason = "contact_reached"
        elif row["campaign_status"] not in {"running", "paused"}:
            reason = "campaign_stopped"
        elif row["call_end_reason"] == "process_interrupted":
            reason = "interrupted"
        elif unclosed:
            reason = "unconfirmed_disconnect"
        elif outcome not in policy.outcomes:
            reason = "outcome_excluded"
        elif row["attempt_number"] >= policy.max_attempts:
            reason = "attempt_limit"
        stamp = datetime.now(UTC).isoformat()
        next_id = uuid4().hex if reason == "scheduled" else None
        # Use finalization after hangup, never the first INVITE, as the interval origin.
        due = (datetime.fromisoformat(row["finalized_at"]) + timedelta(
            seconds=policy.delay_seconds,
        )).isoformat()
        detail = {
            "campaign_id": row["campaign_id"], "contact_id": row["contact_id"],
            "credit_id": row["credit_id"], "phone": row["phone"],
            "previous_job_id": jid, "attempt_number": row["attempt_number"],
            "outcome": outcome, "reason": reason, "policy": policy.model_dump(),
        }
        with self.db:
            if next_id:
                detail.update(next_job_id=next_id, available_at=due,
                              next_attempt_number=row["attempt_number"] + 1)
                self.db.execute(
                    "INSERT INTO jobs(id,campaign_id,phone,credit_id,variables,message,"
                    "status,detail,"
                    "updated_at,contact_id,attempt_number,retry_of,available_at) "
                    "VALUES(?,?,?,?,?,?,'queued',?,?,?,?,?,?)",
                    (next_id, row["campaign_id"], row["phone"], row["credit_id"],
                     row["variables"], row["message"],
                     "Reintento pendiente", stamp, row["contact_id"], row["attempt_number"] + 1,
                     jid, due),
                )
                self.db.execute(
                    "INSERT INTO events(job_id,status,detail,created_at) VALUES(?,'queued',?,?)",
                    (next_id, "Reintento programado después del intento "
                     f"{row['attempt_number']}; disponible desde {due}", stamp),
                )
            self.db.execute(
                "INSERT INTO retry_decisions VALUES(?,?,?,?,?)",
                (jid, reason, next_id, policy.model_dump_json(), stamp),
            )
            self.db.execute(
                "INSERT INTO audit(created_at,actor_name,action,target,detail) VALUES(?,?,?,?,?)",
                (stamp, "sistema", "call.retry_scheduled" if next_id else "call.retry_finished",
                 jid, json.dumps(detail, ensure_ascii=False)),
            )
        return next_id
