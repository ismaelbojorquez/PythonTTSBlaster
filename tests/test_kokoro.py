import asyncio
import json
import sys
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from blaster.config import KokoroSettings, Settings, load_settings
from blaster.tts import KokoroSpeech, speech_for, write_tone
from blaster.voices import KOKORO_PREFIX, VoiceManager
from blaster.web import create_app


def files(root: Path):
    model = root / "kokoro.onnx"
    voices = root / "voices.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")
    return model, voices


def test_kokoro_worker_pool_stays_warm_and_closes(tmp_path):
    model, voices = files(tmp_path)
    worker = tmp_path / "worker.py"
    worker.write_text(
        """
import json, sys, wave
print(json.dumps({'event':'ready'}), flush=True)
for line in sys.stdin:
    request=json.loads(line)
    if request.get('action') == 'close': break
    with wave.open(request['path'],'wb') as audio:
        audio.setparams((1,2,24000,0,'NONE','not compressed'))
        audio.writeframes(b'\\0\\0' * 2400)
    result={'event':'generated','generation_ms':1,'audio_seconds':0.1,'real_time_factor':0.01}
    print(json.dumps(result), flush=True)
""",
        encoding="utf-8",
    )
    config = KokoroSettings(
        enabled=True,
        python=Path(sys.executable),
        model=model,
        voices=voices,
    )

    async def run():
        speech = KokoroSpeech(config, 2, worker_path=worker)
        await speech.start()
        first, second = tmp_path / "one.wav", tmp_path / "two.wav"
        await asyncio.gather(
            speech.synthesize("Hola Ana", first),
            speech.synthesize("Hola Luis", second),
        )
        pids = [process.process.pid for process in speech.processes]
        await speech.close()
        return speech, first, second, pids

    speech, first, second, pids = asyncio.run(run())
    assert first.is_file() and second.is_file()
    assert len(set(pids)) == 2
    assert speech.processes == []
    assert speech.last_metrics["generation_ms"] == 1
    selected = speech_for(Settings(tts_engine="kokoro", kokoro=config), 1)
    assert isinstance(selected, KokoroSpeech)


def test_catalog_exposes_commercial_spanish_voices_only_when_enabled(tmp_path):
    model, voices = files(tmp_path)
    voice_model = tmp_path / "voices" / "fallback.onnx"
    voice_model.parent.mkdir()
    voice_model.write_bytes(b"piper")
    Path(str(voice_model) + ".json").write_text(
        json.dumps({"language": {"code": "es_MX"}, "audio": {"sample_rate": 22050}})
    )
    settings = Settings(data_dir=tmp_path, voice_model=voice_model)
    assert len(VoiceManager(settings).catalog()["items"]) == 1

    settings.kokoro = KokoroSettings(
        enabled=True,
        python=Path(sys.executable),
        model=model,
        voices=voices,
    )
    manager = VoiceManager(settings)
    items = manager.catalog()["items"]
    kokoro = [item for item in items if item["id"].startswith(KOKORO_PREFIX)]
    assert [item["name"] for item in kokoro] == [
        "Kokoro Dora",
        "Kokoro Alex",
        "Kokoro Santa",
    ]
    assert all(item["commercial_use"] for item in kokoro)


def test_panel_can_measure_select_and_revert_kokoro(tmp_path, monkeypatch):
    model, voices = files(tmp_path)
    piper = tmp_path / "voices" / "fallback.onnx"
    piper.parent.mkdir()
    piper.write_bytes(b"piper")
    Path(str(piper) + ".json").write_text(
        json.dumps({"language": {"code": "es_MX"}, "audio": {"sample_rate": 22050}})
    )
    config = tmp_path / "config.toml"
    config.write_text(
        "\n".join(
            [
                'mode = "simulation"',
                'data_dir = "data"',
                'tts_engine = "piper"',
                'voice_model = "voices/fallback.onnx"',
                "[kokoro]",
                "enabled = true",
                f'python = "{sys.executable}"',
                'model = "kokoro.onnx"',
                'voices = "voices.bin"',
                'voice = "ef_dora"',
                'language = "es"',
                "speed = 1.0",
                "startup_timeout = 90.0",
            ]
        ),
        encoding="utf-8",
    )

    class Voice:
        def __init__(self, settings, workers):
            self.settings, self.workers = settings, workers

        async def start(self):
            pass

        async def synthesize(self, text, target):
            write_tone(target, 0.2)
            return target

        async def close(self):
            pass

    monkeypatch.setattr("blaster.voices.KokoroSpeech", Voice)
    monkeypatch.setattr("blaster.voices.PiperSpeech", Voice)
    app = create_app(load_settings(config))
    with TestClient(app) as client:
        setup = client.post(
            "/api/auth/setup",
            json={
                "username": "admin",
                "display_name": "Administración",
                "password": "UnaClaveDePrueba-123",
            },
        )
        assert setup.status_code == 200
        assert len(client.get("/api/manage/voices").json()["items"]) == 4
        selected = client.post(
            "/api/manage/voices/select", json={"model": "kokoro:em_alex"}
        )
        assert selected.status_code == 200, selected.text
        saved = tomllib.loads(config.read_text())
        assert saved["tts_engine"] == "kokoro"
        assert saved["kokoro"]["voice"] == "em_alex"
        assert app.state.engine.settings.kokoro.voice == "em_alex"
        assert client.post(
            "/api/manage/voices/benchmark", json={"model": "kokoro:em_santa"}
        ).status_code == 200

        reverted = client.post(
            "/api/manage/voices/select", json={"model": "fallback.onnx"}
        )
        assert reverted.status_code == 200, reverted.text
        assert tomllib.loads(config.read_text())["tts_engine"] == "piper"
