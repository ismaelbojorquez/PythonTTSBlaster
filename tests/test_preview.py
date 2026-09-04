import asyncio
import base64
import io
import wave

from fastapi.testclient import TestClient

from blaster.config import Settings
from blaster.models import MENU
from blaster.tts import write_tone
from blaster.web import create_app


def test_preview_uses_first_contact_menu_and_real_voice_path_without_creating_calls(
    tmp_path, monkeypatch
):
    model = tmp_path / "voice.onnx"
    model.touch()
    model.with_suffix(".onnx.json").touch()
    captured, paths, loads = [], [], []

    class Voice:
        def __init__(self, path, workers):
            assert path == model and workers == 1

        async def start(self):
            loads.append(True)

        async def synthesize(self, text, path):
            captured.append(text)
            paths.append(path)
            write_tone(path, 0.1)

    monkeypatch.setattr("blaster.preview.PiperSpeech", Voice)
    app = create_app(Settings(data_dir=tmp_path, voice_model=model, auth={"enabled": False}))
    with TestClient(app) as client:
        response = client.post(
            "/api/preview/audio",
            json={
                "template": "Hola {nombre}, tu número es {telefono}.",
                "csv_text": "telefono,nombre\n+525550000101,Ana\n525550000102,Luis",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["message"] == "Hola Ana, tu número es 525550000101."
        assert data["phone"] == "525550000101"
        assert captured == [data["message"] + "\n" + MENU]
        with wave.open(io.BytesIO(base64.b64decode(data["audio_base64"]))) as wav:
            assert wav.getnframes() > 0 and any(wav.readframes(wav.getnframes()))
        # No campaign name, agent number, registration, campaign, or call is needed.
        assert client.post("/api/preview/audio", json={"template": "Buen día"}).status_code == 200
        assert len(loads) == 1
        assert client.get("/api/campaigns").json() == []
        assert client.get("/api/status").json()["active_sessions"] == 0
        missing_contact = client.post("/api/preview/audio", json={"template": "Hola {nombre}"})
        assert missing_contact.status_code == 422
        assert "Agrega un contacto con la columna nombre" in missing_contact.json()["detail"]
        assert "reemplaza {nombre} por texto" in missing_contact.json()["detail"]
        assert len(captured) == 2
        service = app.state.speech_preview
        client.portal.call(service.lock.acquire)
        try:
            assert client.post("/api/preview/audio", json={"template": "Hola"}).status_code == 429
        finally:
            client.portal.call(service.lock.release)
    assert all(not path.exists() and not path.parent.exists() for path in paths)


def test_preview_failure_timeout_and_access(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, tts_timeout=0.01))
    paths = []

    class FailedVoice:
        async def synthesize(self, text, path):
            paths.append(path)
            path.write_bytes(b"partial")
            raise RuntimeError("internal/private/error")

    class SlowVoice:
        async def synthesize(self, text, path):
            paths.append(path)
            path.write_bytes(b"partial")
            await asyncio.sleep(1)

    with TestClient(app) as client:
        assert client.post("/api/preview/audio", json={"template": "Hola"}).status_code == 401
        client.post(
            "/api/auth/setup",
            json={
                "username": "admin",
                "display_name": "Admin",
                "password": "UnaClaveDePrueba-123",
            },
        )
        app.state.speech_preview.speech = FailedVoice()
        result = client.post("/api/preview/audio", json={"template": "Hola"})
        assert result.status_code == 503 and "internal/private" not in result.text
        app.state.speech_preview.speech = SlowVoice()
        assert client.post("/api/preview/audio", json={"template": "Hola"}).status_code == 504
        assert not app.state.speech_preview.lock.locked()
        assert all(not path.parent.exists() for path in paths)
