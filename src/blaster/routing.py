"""Capacity reservation and weighted routing; one shared native SIP endpoint."""

from __future__ import annotations

import asyncio
import json
import time

from blaster.store import now


class TrunkRouter:
    def __init__(self, settings, operations, phone):
        self.settings, self.ops, self.phone = settings, operations, phone
        self.profiles = {t.id: t for t in settings.trunk_profiles()}
        self.reservations = {}
        self.weights = {}
        self.next_dial = {}
        self.cooldown = {}
        self.last_state = {}
        self.reloading = False
        self.sync()

    def sync(self):
        with self.ops.db:
            configured = set(self.profiles)
            for old in self.ops.rows("SELECT id FROM trunks"):
                if old["id"] not in configured:
                    self.ops.db.execute("UPDATE trunks SET enabled=0 WHERE id=?", (old["id"],))
            for t in self.profiles.values():
                profile = t.sip.model_dump()  # password is explicitly excluded by the model.
                self.ops.db.execute(
                    """INSERT INTO trunks VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET name=excluded.name,enabled=excluded.enabled,
                    priority=excluded.priority,weight=excluded.weight,channels=excluded.channels,
                    calls_per_second=excluded.calls_per_second,profile=excluded.profile,
                    updated_at=excluded.updated_at""",
                    (
                        t.id,
                        t.name,
                        int(t.enabled),
                        t.priority,
                        t.weight,
                        t.channels,
                        t.calls_per_second,
                        json.dumps(profile),
                        now(),
                    ),
                )

    def ready(self, tid):
        states = getattr(self.phone, "trunk_states", None)
        return (
            not self.reloading
            and self.profiles[tid].enabled
            and (
                states.get(tid, {}).get("available", False)
                if states is not None
                else self.phone.available
            )
            and self.cooldown.get(tid, 0) <= time.monotonic()
        )

    def used(self, tid):
        return 2 * sum(v == tid for v in self.reservations.values())

    def reserve(self, jid, exclude=()):
        candidates = [
            t
            for t in self.profiles.values()
            if t.id not in exclude and self.ready(t.id) and self.used(t.id) + 2 <= t.channels
        ]
        if not candidates:
            return None
        priority = min(t.priority for t in candidates)
        candidates = [t for t in candidates if t.priority == priority]
        for t in candidates:
            self.weights[t.id] = self.weights.get(t.id, 0) + (
                t.weight if self.settings.routing == "weighted" else 1
            )
        chosen = max(candidates, key=lambda t: (self.weights[t.id], t.id))
        self.weights[chosen.id] -= sum(
            t.weight if self.settings.routing == "weighted" else 1 for t in candidates
        )
        self.reservations[jid] = chosen.id
        return chosen.id

    def release(self, jid):
        self.reservations.pop(jid, None)

    def failed(self, tid, code, retry_after=0):
        # Final responses only. An unanswered INVITE is not duplicated on another carrier.
        if code in {408, 502, 503, 504}:
            delay = max(30, min(86400, retry_after))
            self.cooldown[tid] = time.monotonic() + delay
            self.ops.trunk_event(
                tid, "cooldown", f"SIP {code}; pausa de ruta durante {delay} segundos"
            )

    async def pace(self, tid):
        await asyncio.sleep(max(0, self.next_dial.get(tid, 0) - time.monotonic()))
        self.next_dial[tid] = time.monotonic() + 1 / self.profiles[tid].calls_per_second

    def snapshot(self):
        states = getattr(self.phone, "trunk_states", {})
        return [
            {
                **t.model_dump(exclude={"sip"}),
                "sip": t.sip.model_dump(),
                "has_password": bool(t.sip.password),
                "available": self.ready(t.id),
                "reserved_channels": self.used(t.id),
                "status": states.get(t.id, {}).get("status", self.phone.status),
                "cooldown_seconds": max(0, round(self.cooldown.get(t.id, 0) - time.monotonic())),
            }
            for t in self.profiles.values()
        ]
