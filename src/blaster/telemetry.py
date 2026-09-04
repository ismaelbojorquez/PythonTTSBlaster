"""Call evidence: wall-clock timestamps for reports, monotonic clocks for durations."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class CallEvent:
    kind: str
    data: dict = field(default_factory=dict)
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    tick: float = field(default_factory=time.monotonic)


class CallTrace:
    """Runs on the engine loop. No SQLite or Python reporting on media threads."""

    def __init__(self, store, jid: str, amd_enabled: bool):
        self.store, self.jid = store, jid
        self.start = time.monotonic()
        self.bridge_tick = None
        self.end = None
        self.legs = {}
        store.begin_call(jid, amd_enabled)

    def event(self, kind: str, **data):
        event = CallEvent(kind, data)
        self.store.call_event(self.jid, None, event)
        return event

    def attach(self, leg):
        self.legs[leg.id] = {"role": leg.role, "ticks": {}}
        self.store.add_leg(self.jid, leg)
        leg.observer = lambda event: self.receive(leg, event)
        leg.emit("created")

    def receive(self, leg, event):
        state = self.legs[leg.id]
        ticks = state["ticks"]
        fields = {}
        key = {
            "invite_sent": "invite_at",
            "ringing": "ringing_at",
            "answered": "answered_at",
            "media_ready": "media_at",
            "closed": "ended_at",
        }.get(event.kind)
        if key and key not in ticks:
            ticks[key] = event.tick
            fields[key] = event.at
        if event.kind == "identity":
            fields["call_id"] = event.data["call_id"]
        if event.kind == "response":
            fields["sip_code"] = event.data["code"]
        if event.kind == "termination" and "termination" not in ticks:
            ticks["termination"] = event.tick
            fields.update(
                end_actor=event.data["actor"],
                end_reason=event.data["reason"],
                end_evidence=event.data["evidence"],
            )
            # An unavailable agent does not end the customer's session.
            if leg.role == "customer" or self.bridge_tick is not None:
                self.terminate(
                    event.data["actor"], event.data["reason"], event.data["evidence"], event
                )
        if event.kind == "closed":
            fields.update(
                sip_code=event.data.get("code", leg.code), sip_reason=event.data.get("reason", "")
            )
            if "invite_at" in ticks:
                fields["total_seconds"] = max(0, event.tick - ticks["invite_at"])
            if "answered_at" in ticks:
                fields["connected_seconds"] = max(0, event.tick - ticks["answered_at"])
            if self.bridge_tick is not None:
                self.finish_bridge(event)
        if event.kind == "answered" and "invite_at" in ticks:
            fields["setup_seconds"] = max(0, event.tick - ticks["invite_at"])
        if event.kind == "ringing" and "invite_at" in ticks:
            fields["pdd_seconds"] = max(0, event.tick - ticks["invite_at"])
        self.store.call_event(self.jid, leg.id, event, fields)

    def terminate(self, actor, reason, evidence, event=None):
        if self.end is not None:
            return
        event = event or self.event("session_end", actor=actor, reason=reason, evidence=evidence)
        self.end = event
        self.store.update_call(self.jid, end_actor=actor, end_reason=reason, end_evidence=evidence)

    def bridge(self):
        event = self.event("bridged", actor="system")
        self.bridge_tick = event.tick
        self.store.update_call(self.jid, bridged_at=event.at)

    def finish_bridge(self, event):
        if self.bridge_tick is None:
            return
        self.store.update_call(
            self.jid, bridge_ended_at=event.at, bridge_seconds=max(0, event.tick - self.bridge_tick)
        )
        self.bridge_tick = None

    def finish(self):
        event = self.event("finalized")
        # A crash or failed cleanup does not supply a known media end time.
        self.store.update_call(
            self.jid, finalized_at=event.at, processing_seconds=max(0, event.tick - self.start)
        )
