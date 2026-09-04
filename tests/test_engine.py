import asyncio

import pytest
from conftest import campaign

from blaster.models import TERMINAL


async def until(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.002)


async def menu(engine, cid):
    jid = engine.store.jobs(cid)[0]["id"]
    await until(lambda: jid in engine.sessions and engine.sessions[jid].state == "menu")
    return jid


async def test_repeat_then_agent_bridge_and_both_legs_close(engine):
    cid = campaign(engine)
    engine.start_campaign(cid)
    jid = await menu(engine, cid)
    engine.simulate(jid, "1")
    await until(lambda: len([e for e in engine.store.events(jid) if e["status"] == "playing"]) == 2)
    await until(lambda: engine.sessions[jid].state == "menu")
    engine.simulate(jid, "2")
    # Repeated digits must not spawn multiple agent legs.
    engine.sessions[jid].customer.receive_digit("2")
    await until(lambda: engine.sessions[jid].state == "bridged")
    assert len(engine.telephony.legs) == 2
    assert len(engine.telephony.bridges) == 1
    assert engine.snapshot()["channels_in_use"] == 2
    engine.simulate(jid, "agent_hangup")
    await until(lambda: not engine.sessions)
    assert not engine.telephony.legs
    assert engine.store.jobs(cid)[0]["status"] == "completed"
    assert not list(engine.work_dir.glob("call-*"))


async def test_capacity_is_global_and_reserves_agent_channels(engine):
    cid = campaign(engine, count=6)
    engine.start_campaign(cid)
    await until(lambda: len(engine.sessions) == 2)
    assert sum(j["status"] == "queued" for j in engine.store.jobs(cid)) == 4
    await until(lambda: engine.active_campaign is None)
    assert engine.telephony.max_live_legs <= 2
    assert all(j["status"] == "no_input" for j in engine.store.jobs(cid))


async def test_busy_contact_is_recorded_and_capacity_released(engine):
    cid = campaign(engine)
    engine.telephony.outcomes[engine.store.jobs(cid)[0]["phone"]] = 486
    engine.start_campaign(cid)
    await until(lambda: engine.active_campaign is None)
    assert engine.store.jobs(cid)[0]["status"] == "busy"
    assert not engine.telephony.legs


async def test_rejection_reason_reaches_job_and_history(engine):
    cid = campaign(engine)
    job = engine.store.jobs(cid)[0]
    engine.telephony.outcomes[job["phone"]] = 403
    original_dial = engine.telephony.dial

    async def dial_with_reason(number, role):
        leg = await original_dial(number, role)
        leg.reason = "Forbidden: outbound route denied"
        return leg

    engine.telephony.dial = dial_with_reason
    engine.start_campaign(cid)
    await until(lambda: engine.active_campaign is None)
    expected = "Respuesta SIP 403: Forbidden: outbound route denied"
    assert engine.store.jobs(cid)[0]["detail"] == expected
    assert engine.store.events(job["id"])[0]["detail"] == expected
    assert not engine.telephony.legs


async def test_registration_loss_preserves_pending_contacts(engine):
    cid = campaign(engine)
    engine.start_campaign(cid)
    engine.telephony.available = False
    await asyncio.sleep(0.03)
    assert not engine.sessions
    assert engine.store.jobs(cid)[0]["status"] == "queued"
    engine.telephony.available = True
    engine.wakeup.set()
    await until(lambda: bool(engine.sessions))
    await engine.stop_campaign(cid)


async def test_agent_timeout_plays_fallback_and_releases_both_legs(engine):
    cid = campaign(engine)
    engine.start_campaign(cid)
    jid = await menu(engine, cid)
    engine.telephony.answer_delay = 0.4
    engine.simulate(jid, "2")
    await until(lambda: not engine.sessions)
    assert engine.store.jobs(cid)[0]["status"] == "failed"
    assert "agente" in engine.store.jobs(cid)[0]["detail"]
    assert not engine.telephony.legs


async def test_hangup_during_agent_ringing_cancels_agent(engine):
    cid = campaign(engine)
    engine.start_campaign(cid)
    jid = await menu(engine, cid)
    engine.telephony.answer_delay = 1
    engine.simulate(jid, "2")
    await until(lambda: engine.sessions[jid].agent is not None)
    engine.simulate(jid, "hangup")
    await until(lambda: not engine.sessions)
    assert not engine.telephony.legs
    assert not engine.telephony.bridges


async def test_pause_allows_active_to_finish_stop_cancels_rest(engine):
    cid = campaign(engine, count=5)
    engine.start_campaign(cid)
    await until(lambda: len(engine.sessions) == 2)
    engine.pause_campaign(cid)
    await until(lambda: not engine.sessions)
    assert len([j for j in engine.store.jobs(cid) if j["status"] == "queued"]) == 3
    engine.start_campaign(cid)
    await until(lambda: bool(engine.sessions))
    await engine.stop_campaign(cid)
    assert not engine.sessions
    assert not engine.telephony.legs
    assert all(j["status"] in TERMINAL for j in engine.store.jobs(cid))


async def test_speech_is_generated_only_after_answer(engine):
    cid = campaign(engine)
    engine.telephony.answer_delay = 0.5
    engine.settings.ring_timeout = 0.025
    calls = []

    async def synthesize(text, path):
        calls.append(text)

    engine.speech.synthesize = synthesize
    engine.start_campaign(cid)
    await until(lambda: engine.active_campaign is None)
    assert engine.store.jobs(cid)[0]["status"] == "no_answer"
    assert calls == []


async def test_audio_failure_records_the_stage_and_cause_without_password(engine, caplog):
    cid = campaign(engine)
    engine.settings.sip.password = "test-password-123"

    async def synthesize(text, path):
        raise RuntimeError("Modelo de voz no disponible; test-password-123")

    engine.speech.synthesize = synthesize
    engine.start_campaign(cid)
    await until(lambda: engine.active_campaign is None)
    job = engine.store.jobs(cid)[0]
    assert job["status"] == "failed"
    assert "generar la voz" in job["detail"]
    assert "Modelo de voz no disponible" in job["detail"]
    assert "test-password-123" not in job["detail"] + caplog.text
    assert job["detail"] == engine.store.events(job["id"])[0]["detail"]
    assert not engine.telephony.legs
    assert not list(engine.work_dir.glob("call-*"))


async def test_decreasing_concurrency_does_not_kill_existing_calls(engine):
    cid = campaign(engine, count=4)
    engine.start_campaign(cid)
    await until(lambda: len(engine.sessions) == 2)
    engine.configure_concurrency(1)
    assert len(engine.sessions) == 2
    with pytest.raises(ValueError):
        engine.configure_concurrency(3)
    await engine.stop_campaign(cid)


async def test_modes_cannot_reuse_campaigns_and_double_start_is_idempotent(engine):
    cid = campaign(engine, mode="sip")
    with pytest.raises(ValueError, match="aisladas"):
        engine.start_campaign(cid)
    cid = campaign(engine)
    engine.start_campaign(cid)
    engine.start_campaign(cid)
    await until(lambda: bool(engine.sessions))
    assert len(engine.sessions) == 1
