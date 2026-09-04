import asyncio
from contextlib import asynccontextmanager

import pytest
from amd_samples import signal, silence

from blaster.amd import Detector, detect
from blaster.config import AMDSettings, Settings, load_settings
from blaster.telephony.base import AudioStream, CallEnded
from blaster.telephony.simulated import SimulatedTelephony


def classify(pcm, **options):
    detector = Detector(AMDSettings(**options))
    result = detector.feed(pcm)
    assert result is not None
    return result


def test_brief_greeting_and_pause_vs_long_greeting():
    human = classify(silence(200) + signal(400) + silence(1400))
    assert (human.verdict, human.reason) == ("human", "short_greeting")
    assert human.audio_ms == 1600
    assert human.words == 1
    machine = classify(signal(3000))
    assert (machine.verdict, machine.reason) == ("machine", "long_greeting")
    assert machine.audio_ms == 2400


def test_segment_count_instead_of_speech_recognition():
    result = classify((signal(160) + silence(160)) * 7)
    assert (result.verdict, result.reason, result.words) == ("machine", "many_words", 6)


@pytest.mark.parametrize("frequency", [600, 975, 1000, 1425, 2000])
def test_stable_beeps_are_detected_quickly(frequency):
    result = classify(signal(500, (frequency,)))
    assert (result.verdict, result.reason) == ("machine", "beep")
    assert result.audio_ms <= 300


@pytest.mark.parametrize("frequencies", [(350, 440), (697, 1209), (440,), (2800,)])
def test_dual_tones_dtmf_and_out_of_band_tones_are_not_beeps(frequencies):
    result = classify(signal(400, frequencies) + silence(1400))
    assert result.reason != "beep"


def test_short_tone_does_not_satisfy_beep_duration():
    result = classify(signal(80, (1000,)) + silence(2700))
    assert result.verdict == "unknown"


def test_initial_silence_noise_clicks_and_dc_are_not_proof_of_voicemail():
    import numpy as np

    signals = [
        silence(3000),
        signal(3000, amplitude=20),
        (signal(20) + silence(100)) * 25,
        np.full(24000, 1500, dtype=np.int16).tobytes(),
    ]
    for pcm in signals:
        result = classify(pcm)
        assert (result.verdict, result.reason) == ("unknown", "initial_silence")


def test_analysis_time_is_bounded_when_neither_pattern_wins():
    result = classify((signal(100) + silence(700)) * 8, maximum_words=20)
    assert (result.verdict, result.reason) == ("unknown", "analysis_timeout")
    assert result.audio_ms == 5000


def test_independent_detectors_and_arbitrary_pcm_chunk_boundaries():
    pcm = signal(400) + silence(1400)
    expected = classify(pcm)
    human, machine = Detector(AMDSettings()), Detector(AMDSettings())
    for index in range(0, len(pcm), 117):
        human.feed(pcm[index:index + 117])
        machine.feed(signal(20, (1000,)))
    assert human.result == expected
    assert machine.result.reason == "beep"


async def test_capture_is_bounded_and_overflow_is_not_classified_as_human():
    stream = AudioStream()
    for _ in range(51):
        stream.push(bytes(320))
    assert stream.frames.qsize() == 50
    assert stream.error == "audio_overflow"
    assert await stream.read() == b""
    stream.stop()
    assert stream.frames.empty()


async def test_invalid_capture_frames_and_stopped_stream():
    stream = AudioStream()
    stream.push(bytes(321))
    assert stream.error == "invalid_audio"
    stream.stop()
    with pytest.raises(CallEnded):
        await stream.read()


async def test_live_deadline_without_any_frames_cleans_capture():
    leg = await SimulatedTelephony(answer_delay=0).dial("100", "customer")
    stream = AudioStream()

    @asynccontextmanager
    async def empty_capture():
        try:
            yield stream
        finally:
            stream.stop()

    leg.capture_audio = empty_capture
    try:
        result = await detect(leg, AMDSettings(
            total_analysis_ms=1000, initial_silence_ms=500,
            greeting_speech_ms=800, after_greeting_silence_ms=400,
        ))
        assert (result.verdict, result.reason) == ("unknown", "no_audio")
        assert 900 <= result.elapsed_ms < 1500
        assert stream.stopped
    finally:
        await leg.hangup()


async def test_live_hangup_and_cancellation_stop_capture():
    for cancel in (False, True):
        phone = SimulatedTelephony(answer_delay=0, audio_speed=1)
        phone.amd_audio["100"] = silence(5000)
        leg = await phone.dial("100", "customer")
        task = asyncio.create_task(detect(leg, AMDSettings()))
        await asyncio.sleep(0.05)
        assert leg.capturing
        if cancel:
            task.cancel()
        else:
            await leg.hangup()
        with pytest.raises(asyncio.CancelledError if cancel else CallEnded):
            await task
        assert not leg.capturing
        await leg.hangup()


def test_amd_toml_and_validation(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[amd]\nenabled = true\nunknown_action = "continue"\n')
    assert load_settings(path).amd.unknown_action == "continue"
    assert not Settings().amd.enabled
    for bad in (
        {"unknown_action": "guess"}, {"total_analysis_ms": 999},
        {"beep_min_hz": 2000, "beep_max_hz": 600},
        {"total_analysis_ms": 2000}, {"minimum_word_ms": 0},
        {"silence_threshold": -1}, {"beep_purity": 0.5},
        {"after_greeting_silence_ms": 400, "between_words_silence_ms": 400},
        {"enabledd": True},
    ):
        with pytest.raises(ValueError):
            AMDSettings(**bad)


def test_offline_wav_tool_classifies_and_does_not_invent_trailing_silence(tmp_path):
    import subprocess
    import sys
    import wave
    from pathlib import Path

    config = tmp_path / "config.toml"
    config.write_text('[amd]\nenabled = true\n')
    wav_path = tmp_path / "sample.wav"
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_amd.py"
    for pcm, reason in (
        (signal(400) + silence(1400), "short_greeting"),
        (signal(100), "insufficient_audio"),
    ):
        with wave.open(str(wav_path), "wb") as wav:
            wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            wav.writeframes(pcm)
        process = subprocess.run(
            [sys.executable, str(script), "--config", str(config), "--wav", str(wav_path)],
            capture_output=True, text=True, timeout=5,
        )
        assert process.returncode == 0, process.stderr
        assert f'"reason": "{reason}"' in process.stdout
        assert "no se abrió la troncal" in process.stdout
