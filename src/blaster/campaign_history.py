"""Campaign copies and executions keep independent jobs and immutable origin links."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def migrate(db, path: Path):
    if db.execute("PRAGMA user_version").fetchone()[0] >= 5:
        return
    if db.execute("SELECT 1 FROM campaigns LIMIT 1").fetchone():
        backup = path.with_name(f"{path.name}.before-executions-{uuid4().hex[:8]}.bak")
        with sqlite3.connect(backup) as target:
            db.backup(target)
        backup.chmod(0o600)
    db.executescript("""
        BEGIN;
        CREATE TABLE campaign_copies (
            campaign_id TEXT PRIMARY KEY REFERENCES campaigns(id),
            source_id TEXT NOT NULL REFERENCES campaigns(id),
            root_id TEXT NOT NULL REFERENCES campaigns(id),
            execution_number INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('rerun','duplicate')),
            actor_id TEXT, actor_name TEXT NOT NULL, note TEXT NOT NULL,
            request_id TEXT NOT NULL UNIQUE, fingerprint TEXT NOT NULL,
            start_error TEXT,
            UNIQUE(root_id, execution_number)
        );
        CREATE INDEX copies_source ON campaign_copies(source_id);
        PRAGMA user_version=5;
        COMMIT;
    """)


class CampaignHistory:
    def __init__(self, store):
        self.store, self.db = store, store.db

    def lineage(self, cid):
        row = self.db.execute(
            "SELECT x.source_id,x.root_id,x.execution_number,x.kind,x.actor_name,x.note,"
            "x.start_error,c.name AS source_name FROM campaign_copies x "
            "JOIN campaigns c ON c.id=x.source_id WHERE x.campaign_id=?", (cid,),
        ).fetchone()
        return dict(row) if row else {
            "source_id": None, "root_id": cid, "execution_number": 1, "kind": "original",
            "actor_name": None, "note": "", "start_error": None,
        }

    def replay(self, request_id, fingerprint):
        row = self.db.execute(
            "SELECT campaign_id,fingerprint FROM campaign_copies WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if row and row["fingerprint"] != fingerprint:
            raise ValueError("La solicitud ya se usó con otros datos. Abre de nuevo la acción")
        return row["campaign_id"] if row else None

    @staticmethod
    def fingerprint(cid, kind, name, note, actor):
        value = json.dumps([cid, kind, name, note, actor.get("id"), actor.get("username")])
        return hashlib.sha256(value.encode()).hexdigest()

    def check_rerun(self, cid):
        campaign = self.store.campaign(cid)
        if campaign["status"] not in {"completed", "stopped"}:
            raise ValueError("Finaliza o detén esta campaña antes de volver a ejecutarla")
        root = self.lineage(cid)["root_id"]
        if self.db.execute(
            "SELECT 1 FROM campaigns c LEFT JOIN campaign_copies x ON x.campaign_id=c.id "
            "WHERE (c.id=? OR x.root_id=?) AND c.status NOT IN ('completed','stopped') LIMIT 1",
            (root, root),
        ).fetchone():
            raise ValueError("Ya existe una ejecución pendiente. Ábrela para iniciarla o detenerla")

    def copy(self, cid, kind, name, note, request_id, actor, mode, fingerprint):
        source = self.store.campaign(cid)
        jobs = self.store.jobs(cid, 10000)
        if not jobs:
            raise ValueError("La campaña no tiene contactos para copiar")
        missing = self.store.missing_identifiers(cid)
        if missing:
            raise ValueError(
                f"La campaña tiene {missing} contacto(s) sin Credito o Telefono. "
                "Crea una campaña nueva con ambos identificadores"
            )
        new_id, stamp = uuid4().hex, datetime.now(UTC).isoformat()
        root = self.lineage(cid)["root_id"] if kind == "rerun" else new_id
        # All writes, including the audit, commit together before any calls can start.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if kind == "rerun":
                self.check_rerun(cid)
            number = (
                self.db.execute(
                    "SELECT COALESCE(MAX(execution_number),1)+1 "
                    "FROM campaign_copies WHERE root_id=?",
                    (root,),
                ).fetchone()[0] if kind == "rerun" else 1
            )
            self.db.execute(
                "INSERT INTO campaigns "
                "(id,name,template,agent_number,status,created_at,mode,country,agent_country,"
                "agent_numbers,agent_strategy,agent_pool_wait,retry_policy) "
                "SELECT ?,?,template,agent_number,'draft',?,?,country,agent_country,"
                "agent_numbers,agent_strategy,agent_pool_wait,retry_policy "
                "FROM campaigns WHERE id=?",
                (new_id, name, stamp, mode, cid),
            )
            self.db.executemany(
                "INSERT INTO jobs(id,campaign_id,phone,credit_id,variables,message,"
                "status,updated_at) "
                "VALUES(?,?,?,?,?,?,'queued',?)",
                [(uuid4().hex, new_id, j["phone"], j["credit_id"],
                  json.dumps(j["variables"], ensure_ascii=False), j["message"], stamp)
                 for j in jobs],
            )
            self.db.execute(
                "INSERT INTO campaign_copies(campaign_id,source_id,root_id,execution_number,"
                "kind,actor_id,actor_name,note,request_id,fingerprint) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (new_id, cid, root, number, kind, actor.get("id"),
                 actor.get("username", "sistema"), note, request_id, fingerprint),
            )
            detail = {
                "source_id": cid, "source_name": source["name"], "root_id": root,
                "execution_number": number, "contacts": len(jobs), "scope": "all",
                "mode": mode, "source_mode": source["mode"], "name": name, "note": note,
                "request_id": request_id,
                "retry_policy": source["retry_policy"],
            }
            self.db.execute(
                "INSERT INTO audit(created_at,actor_id,actor_name,action,target,detail) "
                "VALUES(?,?,?,?,?,?)",
                (stamp, actor.get("id"), actor.get("username", "sistema"),
                 "campaign.rerun_created" if kind == "rerun" else "campaign.duplicated",
                 new_id, json.dumps(detail, ensure_ascii=False)),
            )
        return new_id

    def history(self, cid, offset=0):
        self.store.campaign(cid)
        lineage = self.lineage(cid)
        root = lineage["root_id"]
        where = "(c.id=? OR x.root_id=?)"
        total = self.db.execute(
            "SELECT COUNT(*) FROM campaigns c LEFT JOIN campaign_copies x ON x.campaign_id=c.id "
            f"WHERE {where}", (root, root),
        ).fetchone()[0]
        rows = self.db.execute(
            "SELECT c.id,c.name,c.status,c.created_at,c.mode,"
            "COALESCE(x.execution_number,1) AS execution_number,x.actor_name,x.note,"
            "(SELECT MIN(started_at) FROM jobs WHERE campaign_id=c.id) AS started_at,"
            "(SELECT COUNT(DISTINCT contact_id) FROM jobs WHERE campaign_id=c.id) AS contacts,"
            "(SELECT COUNT(*) FROM jobs j JOIN call_legs l ON l.job_id=j.id "
            "WHERE j.campaign_id=c.id AND l.role='customer' "
            "AND l.invite_at IS NOT NULL) AS attempted,"
            "(SELECT COUNT(*) FROM jobs j JOIN call_legs l ON l.job_id=j.id "
            "WHERE j.campaign_id=c.id AND l.role='customer' "
            "AND l.answered_at IS NOT NULL) AS answered "
            "FROM campaigns c LEFT JOIN campaign_copies x ON x.campaign_id=c.id "
            f"WHERE {where} ORDER BY execution_number DESC LIMIT 50 OFFSET ?",
            (root, root, offset),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            if not item["actor_name"]:
                creator = self.db.execute(
                    "SELECT actor_name FROM audit WHERE target=? "
                    "AND action IN ('campaign.created','campaign.started_on_create',"
                    "'campaign.scheduled') ORDER BY id LIMIT 1", (row["id"],),
                ).fetchone()
                item["actor_name"] = creator["actor_name"] if creator else None
            # Historical originals may predate explicit actor tracking; never invent an actor.
            event = self.db.execute(
                "SELECT actor_name,created_at FROM audit WHERE target=? "
                "AND action IN ('campaign.started','campaign.rerun_started',"
                "'campaign.started_on_create','schedule.started') ORDER BY id LIMIT 1",
                (row["id"],),
            ).fetchone()
            item["started_by"] = event["actor_name"] if event else None
            item["requested_at"] = event["created_at"] if event else None
            items.append(item)
        return {"lineage": lineage, "items": items, "total": total, "offset": offset}
