import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from blaster.analytics import Analytics, Filters
from blaster.automation import Automation, local_instant, next_report
from blaster.config import Settings, TrunkSettings
from blaster.engine import Engine
from blaster.models import CampaignInput, Contact
from blaster.operations import Operations
from blaster.routing import TrunkRouter
from blaster.store import Store, now
from blaster.telephony.simulated import SimulatedTelephony
from blaster.tts import SimulatedSpeech


def profiles():
    return [
        TrunkSettings(id="a", name="Principal", channels=4, weight=3, calls_per_second=20),
        TrunkSettings(id="b", name="Reparto", channels=4, weight=1, calls_per_second=20),
        TrunkSettings(id="c", name="Respaldo", channels=4, priority=20, calls_per_second=20),
    ]


def test_routing_weights_capacity_backup_single_and_cooldown(tmp_path):
    store = Store(tmp_path / "db")
    phone = SimulatedTelephony()
    phone.available = True
    router = TrunkRouter(Settings(trunks=profiles(), routing="weighted"), Operations(store), phone)
    chosen = []
    for i in range(40):
        chosen.append(router.reserve(str(i)))
        router.release(str(i))
    assert chosen.count("a") == 30 and chosen.count("b") == 10 and "c" not in chosen
    for i in range(6):
        assert router.reserve(str(i))
    assert router.reserve("full") is None
    assert all(router.used(t) == 4 for t in "abc")
    router.reservations.clear()
    router.failed("a", 503, 120)
    assert not router.ready("a") and router.snapshot()[0]["cooldown_seconds"] >= 119
    assert router.reserve("fallback") == "b"
    single = TrunkRouter(Settings(), Operations(store), phone)
    assert single.reserve("one") == "default"
    single.release("one")
    assert single.used("default") == 0
    store.close()


def test_timezones_and_next_report():
    assert local_instant("2026-09-04T09:00", "America/Mexico_City").hour == 15
    with pytest.raises(ValueError):
        local_instant("2026-03-08T02:30", "America/New_York")
    with pytest.raises(ValueError):
        local_instant("2026-11-01T01:30", "America/New_York")
    row = {
        "timezone": "America/Mexico_City",
        "local_time": "08:00",
        "cadence": "weekly",
        "weekday": 0,
    }
    assert next_report(row, datetime(2026, 9, 3, 12, tzinfo=UTC)).startswith("2026-09-07T14:00")


async def until(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(0.01)


def campaign(store):
    return store.create_campaign(
        CampaignInput(
            name="Local",
            template="Hola {nombre}",
            agent_number="200",
            contacts=[Contact(phone="100", credit_id="CRED-100", variables={"nombre": "Ana"})],
        )
    )


async def test_failover_persists_attempts_and_does_not_retry_busy(tmp_path):
    class FailingPhone(SimulatedTelephony):
        async def dial_on(self, number, role, trunk_id):
            self.outcomes[number] = 503 if trunk_id == "a" else 200
            return await super().dial_on(number, role, trunk_id)

    trunks = profiles()[:2]
    trunks[1].priority = 20
    settings = Settings(
        data_dir=tmp_path,
        concurrency=1,
        trunk_channels=4,
        calls_per_second=20,
        choice_timeout=0.01,
        trunks=trunks,
    )
    store = Store(tmp_path / "db")
    phone = FailingPhone(answer_delay=0.005, audio_speed=0.001)
    engine = Engine(settings, store, phone, SimulatedSpeech())
    await engine.start()
    try:
        cid = campaign(store)
        engine.start_campaign(cid)
        await until(lambda: engine.active_campaign is None)
        job = store.jobs(cid)[0]
        assert job["status"] == "no_input", job
        legs = store.db.execute("SELECT * FROM call_legs").fetchall()
        assert len(legs) == 2 and [r["trunk_id"] for r in legs] == ["a", "b"]
        assert legs[0]["role"].startswith("customer_attempt_")
        assert not engine.router.reservations
        rows, _, _ = Analytics(tmp_path / "db").report_data(Filters(mode="simulation"), 100)
        assert len(rows) == 1 and len(rows[0]["_legs"]) == 2
        assert rows[0]["customer_trunk_id"] == "b"
        assert rows[0]["end_actor"] == "system"  # final policy, not the failed first trunk
    finally:
        await engine.close()
        store.close()


async def test_schedule_dispatch_report_once_alerts_and_recording(engine):
    from conftest import campaign as create_campaign

    cid = create_campaign(engine)
    ops = engine.ops
    automation = Automation(
        engine.settings,
        engine,
        Analytics(engine.settings.data_dir / "test.sqlite3"),
        asyncio.Lock(),
    )
    due = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with ops.db:
        ops.db.execute(
            "INSERT INTO campaign_schedules "
            "(id,campaign_id,due_at,timezone,created_at) VALUES(?,?,?,?,?)",
            ("schedule", cid, due, "America/Mexico_City", now()),
        )
    await automation.tick()
    assert engine.active_campaign == cid
    await automation.tick()
    assert ops.db.execute("SELECT state FROM campaign_schedules").fetchone()[0] == "started"
    await until(lambda: any(s.state in {"playing", "menu"} for s in engine.sessions.values()))
    jid = next(iter(engine.sessions))
    engine.simulate(jid, "2")
    await until(lambda: engine.sessions[jid].state == "bridged")
    engine.simulate(jid, "agent_hangup")
    await until(lambda: not engine.sessions)
    record = dict(ops.db.execute("SELECT * FROM recordings WHERE job_id=?", (jid,)).fetchone())
    assert record["status"] == "ready" and record["evidence"] == "dtmf_interaction"
    assert (engine.recordings.directory / record["filename"]).read_bytes().startswith(b"OggS")
    assert not list(engine.recordings.directory.glob("*.wav"))
    with ops.db:
        ops.db.execute(
            "INSERT INTO report_schedules VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "report",
                "Diario",
                "daily",
                "08:00",
                0,
                "America/Mexico_City",
                "xlsx",
                1,
                "simulation",
                1,
                due,
                None,
                now(),
            ),
        )
    await automation.tick()
    await automation.report_task
    await automation.tick()
    assert ops.db.execute("SELECT COUNT(*) FROM report_runs").fetchone()[0] == 1
    run = dict(ops.db.execute("SELECT * FROM report_runs").fetchone())
    assert run["status"] == "ready", run
    assert (automation.report_dir / run["filename"]).read_bytes().startswith(b"PK")
    ops.alert("once", "Prueba", "Detalle")
    ops.alert("once", "Prueba", "Detalle")
    assert ops.db.execute("SELECT COUNT(*) FROM alerts WHERE dedupe_key='once'").fetchone()[0] == 1
    ops.resolve("once")
    ops.alert("once", "Prueba", "Nueva incidencia")
    assert ops.db.execute("SELECT COUNT(*) FROM alerts WHERE dedupe_key='once'").fetchone()[0] == 2
    # Purge audio by age without deleting its CDR.
    with ops.db:
        ops.db.execute("UPDATE recordings SET started_at='2000-01-01T00:00:00+00:00'")
    engine.recordings.prune()
    assert not (engine.recordings.directory / record["filename"]).exists()
    assert ops.db.execute("SELECT status FROM recordings").fetchone()[0] == "expired"
    assert engine.store.jobs(cid)
