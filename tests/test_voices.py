import json
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from blaster.config import load_settings
from blaster.tts import write_tone
from blaster.voices import VoiceManager, recommendation
from blaster.web import create_app


def voice_files(root, name, *, quality="medium"):
    model = root / "voices" / f"{name}.onnx"
    model.parent.mkdir(exist_ok=True)
    model.write_bytes(b"model")
    Path(str(model) + ".json").write_text(
        json.dumps(
            {
                "dataset": name,
                "language": {"code": "es_MX", "name_native": "Español"},
                "audio": {"quality": quality, "sample_rate": 22050},
            }
        ),
        encoding="utf-8",
    )
    return model


def test_voice_catalog_is_bounded_to_local_models_and_rates_latency(tmp_path):
    active = voice_files(tmp_path, "claude", quality="high")
    voice_files(tmp_path, "ald")
    settings = load_settings(
        _config(tmp_path, "voices/claude.onnx")
    )
    manager = VoiceManager(settings)
    catalog = manager.catalog()
    assert [item["id"] for item in catalog["items"]] == ["ald.onnx", "claude.onnx"]
    selected = next(item for item in catalog["items"] if item["active"])
    assert selected["quality_label"] == "Alta" and selected["language_code"] == "es-MX"
    assert manager.resolve("claude.onnx") == active.resolve()
    for invalid in ("../outside.onnx", "/tmp/outside.onnx", "voice.txt"):
        try:
            manager.resolve(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Se aceptó una ruta de voz insegura: {invalid}")
    assert recommendation(1000, 4)["code"] == "recommended"
    assert recommendation(5000, 6)["code"] == "acceptable"
    assert recommendation(7000, 10)["code"] == "not_recommended"


def _config(tmp_path, voice):
    path = tmp_path / "config.toml"
    path.write_text(
        f'mode = "simulation"\ndata_dir = "data"\nvoice_model = "{voice}"\n',
        encoding="utf-8",
    )
    return path


def test_voice_benchmark_selection_persistence_and_preview_metrics(tmp_path, monkeypatch):
    voice_files(tmp_path, "claude", quality="high")
    selected = voice_files(tmp_path, "ald")
    config = _config(tmp_path, "voices/claude.onnx")

    class Voice:
        def __init__(self, model, workers):
            self.model, self.workers = model, workers

        async def start(self):
            pass

        async def synthesize(self, text, target):
            write_tone(target, 0.2)
            return target

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
        assert setup.status_code == 200, setup.text
        voices = client.get("/api/manage/voices").json()
        assert len(voices["items"]) == 2

        benchmark = client.post(
            "/api/manage/voices/benchmark", json={"model": "ald.onnx"}
        )
        assert benchmark.status_code == 200, benchmark.text
        measurement = benchmark.json()["benchmark"]
        assert measurement["generation_ms"] >= 0
        assert measurement["audio_seconds"] == 0.2
        assert measurement["recommendation"]["code"] == "recommended"
        assert benchmark.json()["audio_base64"]
        measured = client.get("/api/manage/voices").json()["items"]
        assert next(item for item in measured if item["id"] == "ald.onnx")["benchmark"]

        app.state.engine.active_campaign = "busy"
        assert client.post(
            "/api/manage/voices/select", json={"model": "ald.onnx"}
        ).status_code == 409
        app.state.engine.active_campaign = None

        changed = client.post("/api/manage/voices/select", json={"model": "ald.onnx"})
        assert changed.status_code == 200, changed.text
        assert changed.json()["active"] is True
        assert app.state.engine.settings.voice_model == selected.resolve()
        assert tomllib.loads(config.read_text())["voice_model"] == "voices/ald.onnx"

        preview = client.post("/api/preview/audio", json={"template": "Hola"})
        assert preview.status_code == 200, preview.text
        assert preview.json()["voice"] == "ald"
        assert preview.json()["audio_seconds"] == 0.2
        assert preview.json()["recommendation"]["code"] == "recommended"
        assert client.post(
            "/api/manage/voices/benchmark", json={"model": "../outside.onnx"}
        ).status_code == 422
