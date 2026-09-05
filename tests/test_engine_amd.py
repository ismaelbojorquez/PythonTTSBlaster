import asyncio
import json
import wave

import pytest
from amd_samples import signal, silence
from conftest import campaign
from test_engine import menu, until

from blaster.config import AMDSettings
from blaster.models import TERMINAL


async def test_amd_machine_hangs_up_without_tts_or_agent(engine):
    engine.settings.amd = AMDSettings(enabled=True)
    cid = campaign(engine)
    job = engine.store.jobs(cid)[0]
    engine.telephony.amd_audio[job["phone"]] = signal(3000)

    async def never_synthesize(*args):
        pytest.fail("No debe generarse TTS para un buzón")

    engine.speech.synthesize = never_synthesize
    engine.start_campaign(cid)
    await until(lambda: engine.active_campaign is None)
    result = engine.store.jobs(cid)[0]
    assert result["status"] == "machine"
    assert result["ended_at"]
    assert result["status"] in TERMINAL
    assert "voz acumulada" in result["detail"]
    assert not engine.telephony.legs
    assert not engine.telephony.bridges
    assert not list(engine.work_dir.glob("call-*"))


async def test_amd_human_continues_and_agent_leg_is_not_screened(engine):
    engine.settings.amd = AMDSettings(enabled=True)
    cid = campaign(engine)
    engine.start_campaign(cid)
    jid = await menu(engine, cid)
    session = engine.sessions[jid]
    assert not session.customer.capturing
    assert any("Humano probable" in e["detail"] for e in engine.store.events(jid))
    engine.telephony.amd_audio["525550009999"] = signal(3000, (1000,))
    engine.simulate(jid, "2")
    await until(lambda: session.state == "bridged")
    assert not session.agent.capturing
    engine.simulate(jid, "agent_hangup")
    await until(lambda: not engine.sessions)
    assert engine.store.jobs(cid)[0]["status"] == "completed"


async def test_amd_calibration_saves_only_the_initial_analysis_audio(engine):
    engine.settings.amd = AMDSettings(
        enabled=True,
        calibration_capture_enabled=True,
        calibration_retention_days=14,
        calibration_max_samples=50,
    )
    cid = campaign(engine)
    engine.start_campaign(cid)
    jid = await menu(engine, cid)
    row = engine.store.db.execute(
        "SELECT * FROM amd_calibration_samples WHERE job_id=?", (jid,)
    ).fetchone()
    assert row is not None
    assert row["duration_ms"] <= engine.settings.amd.total_analysis_ms
    assert row["predicted_verdict"] == "human"
    assert row["label"] is None
    path = engine.amd_calibration.directory / row["filename"]
    assert path.is_file()
    with wave.open(str(path), "rb") as recording:
        assert recording.getparams()[:3] == (1, 2, 8000)
        assert recording.getnframes() * 1000 // recording.getframerate() == row["duration_ms"]
    event = engine.store.db.execute(
        "SELECT 1 FROM call_events WHERE job_id=? AND kind='amd_calibration_saved'", (jid,)
    ).fetchone()
    assert event
    engine.simulate(jid, "hangup")
    await until(lambda: not engine.sessions)


@pytest.mark.parametrize("action", ["hangup", "continue"])
async def test_amd_unknown_policy_and_history(engine, action):
    engine.settings.amd = AMDSettings(enabled=True, unknown_action=action)
    cid = campaign(engine)
    job = engine.store.jobs(cid)[0]
    engine.telephony.amd_audio[job["phone"]] = silence(3000)
    engine.start_campaign(cid)
    if action == "continue":
        jid = await menu(engine, cid)
        assert any("Incierto" in e["detail"] for e in engine.store.events(jid))
        engine.simulate(jid, "hangup")
        await until(lambda: not engine.sessions)
        recording = engine.store.db.execute(
            "SELECT evidence FROM recordings WHERE job_id=?", (job["id"],)
        ).fetchone()
        assert recording["evidence"] == "amd_inconclusive_continued"
    else:
        await until(lambda: engine.active_campaign is None)
        assert engine.store.jobs(cid)[0]["status"] == "amd_unknown"
        assert not any(e["status"] == "synthesizing" for e in engine.store.events(job["id"]))
    event = json.loads(engine.store.db.execute(
        "SELECT data FROM call_events WHERE job_id=? AND kind='amd'", (job["id"],)
    ).fetchone()[0])
    assert event["detector_version"] == "energy-timing-v2"
    assert event["parameters"] == engine.settings.amd.model_dump()
    assert event["parameters"]["unknown_action"] == action
    assert event["voiced_ms"] == 0


async def test_concurrent_amd_results_do_not_mix(engine):
    engine.settings.amd = AMDSettings(enabled=True, unknown_action="hangup")
    cid = campaign(engine, count=2)
    jobs = engine.store.jobs(cid)
    engine.telephony.amd_audio[jobs[0]["phone"]] = signal(3000, (1000,))
    engine.telephony.amd_audio[jobs[1]["phone"]] = silence(3000)
    engine.start_campaign(cid)
    await until(lambda: engine.active_campaign is None)
    assert [j["status"] for j in engine.store.jobs(cid)] == ["machine", "amd_unknown"]


async def test_campaign_stop_during_amd_releases_capture(engine):
    engine.settings.amd = AMDSettings(enabled=True)
    engine.telephony.audio_speed = 1
    cid = campaign(engine)
    engine.start_campaign(cid)
    await until(lambda: any(s.state == "detecting" for s in engine.sessions.values()))
    session = next(iter(engine.sessions.values()))
    await asyncio.sleep(0.03)
    await engine.stop_campaign(cid)
    assert not session.customer.capturing
    assert not engine.telephony.legs
    assert engine.store.jobs(cid)[0]["status"] == "cancelled"
