"""Opt in with BLASTER_NATIVE_TEST=1. Uses localhost UDP only, never a trunk."""

import asyncio
import math
import os
import socket
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

import pytest

from blaster.amd import detect
from blaster.config import AMDSettings, Settings, SIPSettings, TrunkSettings
from blaster.telephony.base import CallEnded
from blaster.telephony.pjsua import PJSUATelephony
from blaster.tts import write_tone

pytestmark = pytest.mark.skipif(
    os.environ.get("BLASTER_NATIVE_TEST") != "1", reason="Prueba SIP nativa optativa"
)


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0.02)


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def frequency_power(samples, rate, frequency):
    real = sum(x * math.cos(2 * math.pi * frequency * i / rate) for i, x in enumerate(samples))
    imag = sum(x * math.sin(2 * math.pi * frequency * i / rate) for i, x in enumerate(samples))
    return real * real + imag * imag


async def test_native_immediate_480_preserves_response_before_leg_is_closed(tmp_path, caplog):
    import logging

    peer_port = free_port()
    settings = Settings(sip=SIPSettings(
        domain=f"127.0.0.1:{peer_port}", username="blaster",
        registration_enabled=False, bind_address="127.0.0.1", local_port=free_port(),
        rtp_port=18000,
    ))
    driver = PJSUATelephony(settings)
    evidence = []
    driver.on_leg = lambda leg: setattr(leg, "observer", evidence.append)
    caplog.set_level(logging.INFO, logger="blaster.telephony.pjsua")
    with (tmp_path / "peer.log").open("w") as logfile:
        peer = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("sip_peer.py")),
             str(tmp_path), str(peer_port)], stdout=logfile, stderr=subprocess.STDOUT,
        )
        try:
            await until(lambda: (tmp_path / "ready").exists() or peer.poll() is not None)
            assert peer.poll() is None, (tmp_path / "peer.log").read_text()
            await driver.start()
            for number in ("480", "4800"):
                evidence.clear()
                leg = await driver.dial(number, "customer")
                with pytest.raises(CallEnded) as error:
                    await leg.wait_ready(5)
                assert error.value.code == 480
                responses = [e for e in evidence if e.kind == "response" and e.data["code"] == 480]
                assert len(responses) == 1
                response = responses[0]
                assert response.data["reason_causes"] == (
                    [{"protocol": "Q.850", "cause": 20}] if number == "480" else []
                )
                assert response.data["retry_after"] == (120 if number == "480" else 0)
                assert response.data["source"] == f"127.0.0.1:{peer_port}"
                invite = next(event for event in evidence if event.kind == "invite_sent")
                assert invite.data["target_uri"] == f"sip:{number}@127.0.0.1:{peer_port}"
                assert invite.data["from_uri"] == f"sip:blaster@127.0.0.1:{peer_port}"
                assert evidence.index(response) < next(
                    i for i, event in enumerate(evidence) if event.kind == "closed"
                )
                assert not leg.ready.is_set()
                assert driver.available  # A destination rejection does not unregister the trunk.
                assert leg.id not in driver.legs
            assert "Reason=Q.850 causa=20" in caplog.text
            assert "Reason=no informado" in caplog.text
        finally:
            await driver.stop()
            (tmp_path / "stop").touch()
            try:
                await asyncio.to_thread(peer.wait, 5)
            except subprocess.TimeoutExpired:
                peer.kill()
                await asyncio.to_thread(peer.wait)


@pytest.mark.parametrize("calibrated", [False, True])
async def test_native_amd_concurrent_human_beep_and_silence(tmp_path, calibrated):
    from amd_samples import signal, silence

    from blaster.config import load_settings
    from blaster.engine import Engine
    from blaster.models import CampaignInput, Contact
    from blaster.store import Store
    from blaster.tts import SimulatedSpeech

    # Artificial sources exercise the entire SIP/PCMU/capture/decision/campaign path.
    for number, pcm in {
        "110": silence(400) + signal(2800 if calibrated else 400) + silence(3000),
        "111": silence(400) + signal(1000, (1000,)),
        "112": silence(4000),
    }.items():
        with wave.open(str(tmp_path / f"source-{number}.wav"), "wb") as wav:
            wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            wav.writeframes(pcm)
    peer_port = free_port()
    settings = Settings(
        mode="sip",
        data_dir=tmp_path,
        concurrency=3,
        trunk_channels=6,
        calls_per_second=20,
        choice_timeout=0.05,
        max_call_seconds=12,
        amd=(load_settings(Path(__file__).resolve().parents[1] / "config.example.toml").amd
             if calibrated else AMDSettings(enabled=True)),
        sip=SIPSettings(
            domain=f"127.0.0.1:{peer_port}",
            username="blaster",
            registration_enabled=False,
            bind_address="127.0.0.1",
            local_port=free_port(),
            rtp_port=16000,
        ),
    )
    store = Store(tmp_path / "amd.sqlite3")
    speech = SimulatedSpeech()
    synthesized = []
    original = speech.synthesize

    async def synthesize(text, path):
        synthesized.append(text)
        return await original(text, path)

    speech.synthesize = synthesize
    engine = Engine(settings, store, PJSUATelephony(settings), speech)
    with (tmp_path / "peer.log").open("w") as logfile:
        peer = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("sip_peer.py")),
                str(tmp_path),
                str(peer_port),
            ],
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )
        try:
            await until(lambda: (tmp_path / "ready").exists() or peer.poll() is not None)
            assert peer.poll() is None, (tmp_path / "peer.log").read_text()
            await engine.start()
            cid = store.create_campaign(
                CampaignInput(
                    name="AMD local",
                    template="Prueba {nombre}",
                    agent_number="200",
                    contacts=[
                        Contact(phone=n, credit_id=f"CRED-{n}", variables={"nombre": n})
                        for n in ("110", "111", "112")
                    ],
                ),
                mode="sip",
            )
            engine.start_campaign(cid)
            await until(lambda: engine.active_campaign is None)
            assert [j["status"] for j in store.jobs(cid)] == ["no_input", "machine", "amd_unknown"]
            assert len(synthesized) == 1 and "110" in synthesized[0]
            assert not engine.telephony.legs
            assert not (tmp_path / "invite-200").exists()
            assert not list(engine.work_dir.glob("call-*"))
            for number in ("111", "112"):
                await until(lambda number=number: (tmp_path / f"closed-{number}").exists())
        finally:
            await engine.close()
            store.close()
            (tmp_path / "stop").touch()
            try:
                await asyncio.to_thread(peer.wait, 5)
            except subprocess.TimeoutExpired:
                peer.kill()
                await asyncio.to_thread(peer.wait)

    # The two rejected legs heard no TTS or waiting tone.
    for number in ("111", "112"):
        with wave.open(str(tmp_path / f"received-{number}.wav")) as wav:
            data = wav.readframes(wav.getnframes())
        values = struct.unpack(f"<{len(data) // 2}h", data)
        assert values and max(map(abs, values)) < 100


async def test_native_sip_play_dtmf_bridge_and_remote_bye(tmp_path, caplog):
    peer_port, local_port = free_port(), free_port()
    settings = Settings(
        concurrency=2,
        trunk_channels=4,
        sip=SIPSettings(
            domain=f"127.0.0.1:{peer_port}",
            username="blaster",
            registration_enabled=False,
            bind_address="127.0.0.1",
            local_port=local_port,
            rtp_port=14000,
        ),
    )
    settings.trunks = [
        TrunkSettings(
            id="a",
            name="Principal",
            channels=2,
            sip=settings.sip.model_copy(update={"username": "blaster-a"}),
        ),
        TrunkSettings(
            id="b",
            name="Segunda",
            channels=2,
            sip=settings.sip.model_copy(update={"username": "blaster-b", "rtp_port": 14400}),
        ),
    ]
    logfile = (tmp_path / "peer.log").open("w")
    peer = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).with_name("sip_peer.py")),
            str(tmp_path),
            str(peer_port),
        ],
        stdout=logfile,
        stderr=subprocess.STDOUT,
    )
    driver = PJSUATelephony(settings)
    customer = agent = None
    try:
        await until(lambda: (tmp_path / "ready").exists() or peer.poll() is not None)
        assert peer.poll() is None, (tmp_path / "peer.log").read_text()
        await driver.start()
        rejected = await driver.dial("403", "customer")
        with pytest.raises(CallEnded) as error:
            await rejected.wait_ready(5)
        assert error.value.code == 403
        assert error.value.reason == "Forbidden: outbound route denied"
        await rejected.hangup()
        assert "Call-ID=" in caplog.text
        customer = await driver.dial("100", "customer")
        await customer.wait_ready(5)
        await until(lambda: (tmp_path / "ready-100").exists())
        # Real PCMU RTP -> native PCM sink -> DSP. The peer sends a steady 600 Hz tone.
        result = await detect(customer, AMDSettings())
        assert (result.verdict, result.reason) == ("machine", "beep")
        assert driver.trunk_states["a"]["available"] and driver.trunk_states["b"]["available"]
        mixed = tmp_path / "mixed.wav"
        await driver.start_recording(customer, mixed)
        # Reusing this same call proves sink cleanup does not break playback/bridge.
        tone = tmp_path / "play.wav"
        write_tone(tone, seconds=0.3)
        await asyncio.wait_for(customer.play(tone), 5)
        waiting = asyncio.create_task(customer.play(tone, loop=True))
        # A repeating waiting tone must survive several EOF callbacks.
        await asyncio.sleep(0.85)
        assert not waiting.done(), "El tono en bucle terminó al llegar al primer EOF"
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        with pytest.raises(RuntimeError) as playback_error:
            await customer.play(tmp_path / "missing.wav")
        assert "La operación SIP play falló" in str(playback_error.value)
        assert "pjsua_player_create" in str(playback_error.value)
        # A failed player must be cleaned up so the next playback can succeed.
        await asyncio.wait_for(customer.play(tone), 5)
        (tmp_path / "send-digit").write_text("100:1")
        assert await asyncio.wait_for(customer.digits.get(), 5) == "1"
        agent = await driver.dial_on("200", "agent", "b")
        assert customer.trunk_id == "a" and agent.trunk_id == "b"
        await agent.wait_ready(5)
        await until(lambda: (tmp_path / "ready-200").exists())
        await driver.bridge(customer, agent)
        # Give RTP enough samples to prove audio in both directions after the bridge.
        await asyncio.sleep(1.2)
        (tmp_path / "send-digit").write_text("100:5")
        await until(lambda: (tmp_path / "digit-200").exists())
        assert (tmp_path / "digit-200").read_text() == "5"
        (tmp_path / "hangup").write_text("200")
        await asyncio.wait_for(agent.closed.wait(), 5)
        await customer.hangup()
        await driver.stop_recording(customer)
        with wave.open(str(mixed)) as recording:
            samples = struct.unpack(
                f"<{recording.getnframes()}h", recording.readframes(recording.getnframes())
            )
            rate = recording.getframerate()
        assert frequency_power(samples, rate, 600) > frequency_power(samples, rate, 1300) * 10
        assert frequency_power(samples, rate, 900) > frequency_power(samples, rate, 1300) * 10
        await until(lambda: (tmp_path / "closed-100").exists())
        for name, wanted, unwanted in [("100", 900, 600), ("200", 600, 900)]:
            with wave.open(str(tmp_path / f"received-{name}.wav")) as wav:
                data = wav.readframes(wav.getnframes())
                rate = wav.getframerate()
                samples = struct.unpack(f"<{len(data) // 2}h", data)
            assert len(samples) > rate // 2
            assert frequency_power(samples, rate, wanted) > 10 * frequency_power(
                samples, rate, unwanted
            ), f"El extremo {name} no recibió el audio del otro extremo"
    finally:
        for leg in (customer, agent):
            if leg:
                await leg.hangup()
        await driver.stop()
        (tmp_path / "stop").touch()
        try:
            await asyncio.to_thread(peer.wait, 5)
        except subprocess.TimeoutExpired:
            peer.kill()
            await asyncio.to_thread(peer.wait)
        logfile.close()


async def test_native_piper_wait_repeat_and_agent_flow(tmp_path):
    pytest.importorskip("piper")
    model = Path(__file__).resolve().parents[1] / "voices/es_MX-claude-high.onnx"
    if not model.is_file():
        pytest.skip("Instala la voz local para probar Piper con SIP")

    from blaster.engine import Engine
    from blaster.models import CampaignInput, Contact
    from blaster.store import Store
    from blaster.tts import PiperSpeech

    class DelayedSpeech(PiperSpeech):
        async def synthesize(self, text, path):
            # The first two-second waiting-tone iteration must not end the call.
            await asyncio.sleep(2.5)
            return await super().synthesize(text, path)

    peer_port = free_port()
    settings = Settings(
        mode="sip",
        data_dir=tmp_path / "data",
        concurrency=1,
        trunk_channels=2,
        ring_timeout=5,
        agent_timeout=5,
        max_call_seconds=60,
        voice_model=model,
        sip=SIPSettings(
            domain=f"127.0.0.1:{peer_port}",
            username="local-test",
            registration_enabled=False,
            bind_address="127.0.0.1",
            local_port=free_port(),
            rtp_port=16000,
        ),
    )
    settings.data_dir.mkdir()
    (tmp_path / "agent-answer-delay").write_text("1.2")
    store = Store(settings.data_dir / "blaster.sqlite3")
    engine = Engine(settings, store, PJSUATelephony(settings), DelayedSpeech(model, 1))
    logfile = (tmp_path / "peer.log").open("w")
    peer = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).with_name("sip_peer.py")),
            str(tmp_path),
            str(peer_port),
        ],
        stdout=logfile,
        stderr=subprocess.STDOUT,
    )
    try:
        await until(lambda: (tmp_path / "ready").exists() or peer.poll() is not None)
        assert peer.poll() is None, (tmp_path / "peer.log").read_text()
        await engine.start()
        cid = store.create_campaign(
            CampaignInput(
                name="Voz local",
                template="Hola. Esta es una prueba de voz personalizada.",
                agent_number="200",
                contacts=[Contact(phone="100", credit_id="CRED-100")],
            ),
            mode="sip",
        )
        jid = store.jobs(cid)[0]["id"]
        engine.start_campaign(cid)
        await until(lambda: store.jobs(cid)[0]["status"] in {"playing", "failed"})
        assert store.jobs(cid)[0]["status"] == "playing", store.jobs(cid)[0]["detail"]
        with wave.open(str(next(engine.work_dir.glob("call-*/message.wav")))) as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 22050)
        await asyncio.sleep(1.2)
        (tmp_path / "send-digit").write_text("100:1")
        await until(lambda: sum(e["status"] == "playing" for e in store.events(jid)) >= 2)
        await asyncio.sleep(1.2)
        agent_requested_at = time.monotonic()
        (tmp_path / "send-digit").write_text("100:2")
        await until(lambda: (tmp_path / "invite-200").exists())
        agent_launch_seconds = time.monotonic() - agent_requested_at
        print(f"DTMF 2 → agente SIP local: {agent_launch_seconds:.3f} s")
        assert agent_launch_seconds < 1.0
        await until(lambda: store.jobs(cid)[0]["status"] in {"bridged", "failed"})
        assert store.jobs(cid)[0]["status"] == "bridged", store.jobs(cid)[0]["detail"]
        details = [event["detail"] for event in store.events(jid)]
        assert any("INVITE del agente enviado" in detail for detail in details)
        assert any("SIP 180" in detail for detail in details)
        assert any("SIP 200" in detail for detail in details)
        await asyncio.sleep(0.4)
        (tmp_path / "hangup").write_text("200")
        await until(lambda: not engine.sessions)
        assert store.jobs(cid)[0]["status"] == "completed"
        record = store.db.execute(
            "SELECT end_actor,transfer_actor,bridge_seconds FROM call_records WHERE job_id=?",
            (jid,),
        ).fetchone()
        assert record["end_actor"] == "agent"
        assert record["transfer_actor"] == "customer"
        assert record["bridge_seconds"] is not None
        recording = dict(
            store.db.execute("SELECT * FROM recordings WHERE job_id=?", (jid,)).fetchone()
        )
        assert recording["status"] == "ready", recording
        import soundfile as sf

        pcm, rate = sf.read(engine.recordings.directory / recording["filename"])
        assert len(pcm) > rate and max(abs(pcm)) > 0.01
        assert recording["size_bytes"] < len(pcm) * 2 * 0.5
        assert not list(engine.recordings.directory.glob("*.wav"))
        legs = store.db.execute(
            "SELECT role,answered_at,call_id FROM call_legs WHERE job_id=? ORDER BY role", (jid,)
        ).fetchall()
        assert len(legs) == 2 and all(row["answered_at"] and row["call_id"] for row in legs)
        assert not list(engine.work_dir.glob("call-*"))
    finally:
        await engine.close()
        store.close()
        (tmp_path / "stop").touch()
        try:
            await asyncio.to_thread(peer.wait, 5)
        except subprocess.TimeoutExpired:
            peer.kill()
            await asyncio.to_thread(peer.wait)
        logfile.close()
    # Closing the peer flushes its recorder and finalizes the WAV header.
    with wave.open(str(tmp_path / "received-100.wav")) as wav:
        rate = wav.getframerate()
        samples = struct.unpack(f"<{wav.getnframes()}h", wav.readframes(wav.getnframes()))
        assert len(samples) > rate * 3
        assert max(abs(sample) for sample in samples) > 100
