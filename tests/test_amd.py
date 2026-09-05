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
    result = classify(signal(80, (1000,)) + silence(5200))
    assert result.verdict == "unknown"


def test_initial_silence_noise_clicks_and_dc_are_not_proof_of_voicemail():
    import numpy as np

    signals = [
        silence(5200),
        signal(5200, amplitude=20),
        (signal(20) + silence(100)) * 44,
        np.full(41600, 1500, dtype=np.int16).tobytes(),
    ]
    for pcm in signals:
        result = classify(pcm)
        assert (result.verdict, result.reason) == ("unknown", "initial_silence")


def test_analysis_time_is_bounded_when_neither_pattern_wins():
    result = classify((signal(100) + silence(700)) * 9, maximum_words=20)
    assert (result.verdict, result.reason) == ("unknown", "analysis_timeout")
    assert result.audio_ms == 6500


def test_independent_detectors_and_arbitrary_pcm_chunk_boundaries():
    pcm = signal(400) + silence(1400)
    expected = classify(pcm)
    human, machine = Detector(AMDSettings()), Detector(AMDSettings())
    for index in range(0, len(pcm), 117):
        human.feed(pcm[index:index + 117])
        machine.feed(signal(20, (1000,)))
    assert human.result == expected
    assert machine.result.reason == "beep"


def test_rejected_clicks_do_not_turn_later_human_greeting_into_machine():
    pcm = (signal(80) + silence(60)) * 35 + signal(400) + silence(1400)
    result = classify(pcm, initial_silence_ms=6000, total_analysis_ms=10000)
    assert (result.verdict, result.reason) == ("human", "short_greeting")
    assert result.voiced_ms == 400


def test_clicks_in_pause_do_not_restart_the_human_silence_clock():
    result = classify(signal(400) + (silence(280) + signal(20)) * 6)
    assert result.verdict == "human"
    assert result.audio_ms == 1400
    assert result.voiced_ms == 400


def test_a_single_short_qualified_burst_is_not_enough_to_accept_human():
    result = classify(signal(120) + silence(6400))
    assert result.verdict == "unknown"
    assert result.voiced_ms == 120


def test_a_greeting_starting_just_before_initial_deadline_can_finish():
    result = classify(silence(2440) + signal(400) + silence(1400))
    assert result.verdict == "human"
    assert result.voiced_ms == 400


def test_tone_below_beep_duration_is_not_accepted_as_human_speech():
    result = classify(signal(280, (1000,)) + silence(5200), beep_min_ms=360)
    assert result.verdict == "unknown"
    assert result.voiced_ms == 0


def test_calibrated_example_handles_long_human_and_machine_with_internal_pause():
    from pathlib import Path

    profile = load_settings(Path(__file__).resolve().parents[1] / "config.example.toml").amd
    options = profile.model_dump()
    assert options["total_analysis_ms"] == 6500
    assert options["unknown_action"] == "hangup"
    human = classify(signal(2800) + silence(1800), **options)
    assert human.verdict == "human"
    paused_machine = classify(signal(800) + silence(1200) + signal(3000), **options)
    assert (paused_machine.verdict, paused_machine.reason) == ("machine", "long_greeting")
    fragmented_human = classify((signal(180) + silence(120)) * 7 + silence(1500), **options)
    assert fragmented_human.verdict == "human"
    late_human = classify(silence(4640) + signal(400) + silence(1600), **options)
    assert late_human.verdict == "human"
    assert classify(signal(600, (1000,)), **options).reason == "beep"


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
    assert AMDSettings().unknown_action == "hangup"
    assert not Settings().amd.enabled
    for bad in (
        {"unknown_action": "guess"}, {"total_analysis_ms": 999},
        {"beep_min_hz": 2000, "beep_max_hz": 600},
        {"total_analysis_ms": 2000}, {"minimum_word_ms": 0},
        {"silence_threshold": -1}, {"beep_purity": 0.5},
        {"after_greeting_silence_ms": 400, "between_words_silence_ms": 400},
        {"enabledd": True},
        {"minimum_human_speech_ms": 0},
        {"greeting_speech_ms": 500, "minimum_human_speech_ms": 600},
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
