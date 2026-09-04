import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blaster.config import Settings, load_settings
from blaster.management import settings_data
from blaster.web import create_app
from scripts.check_production import check_layout
from scripts.prepare_production import prepare

ORIGIN = "https://tts.example.com"
PASSWORD = "ClaveDePrueba-2026-local"


def public_settings(tmp_path):
    return Settings(
        data_dir=tmp_path,
        web_public_url=ORIGIN,
        auth={"bootstrap_username": "admin", "bootstrap_password": PASSWORD},
        automation={"enabled": False},
    )


def test_tunnel_login_origin_hosts_cookies_and_bootstrap(tmp_path):
    settings = public_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert not client.get("/api/auth/status").json()["setup_required"]
        assert client.get("/api/status").status_code == 401
        credentials = {"username": "admin", "password": PASSWORD}
        # cloudflared can retain the public Host or replace it with localhost.
        response = client.post(
            "/api/auth/login",
            json=credentials,
            headers={"Origin": ORIGIN, "Host": "127.0.0.1:8765"},
        )
        assert response.status_code == 200, response.text
        cookie = response.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
        for forbidden in ("https://evil.example", "https://example.com", "null"):
            assert (
                client.post(
                    "/api/auth/login", json=credentials, headers={"Origin": forbidden}
                ).status_code
                == 403
            )
        assert client.get("/healthz", headers={"Host": "evil.example"}).status_code == 400
        assert (
            client.post(
                "/api/auth/login",
                json=credentials,
                headers={"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"},
            ).status_code
            == 403
        )
        # A browser-facing login saves the host-scoped secure session.
        assert (
            client.post("/api/auth/login", json=credentials, headers={"Origin": ORIGIN}).status_code
            == 200
        )
        assert client.get("/api/campaigns").json() == []
        assert PASSWORD not in client.get("/api/manage/config").text
        assert PASSWORD not in client.get("/api/manage/audit").text
        assert "bootstrap_password" not in settings.model_dump()["auth"]
        assert PASSWORD not in repr(settings)
        assert Settings.model_validate(settings_data(settings)).auth.bootstrap_password == PASSWORD
    # Restarting never replaces an existing user's password with the TOML seed.
    settings.auth.bootstrap_password = "OtraClaveDePrueba-2026"
    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        assert client.post("/api/auth/login", json=credentials).status_code == 200
        audit = client.get("/api/manage/audit").json()
        assert sum(item["action"] == "auth.bootstrap" for item in audit) == 1


def test_public_access_cannot_offer_unclaimed_admin_setup(tmp_path):
    with pytest.raises(ValueError, match="auth.bootstrap_username"):
        with TestClient(create_app(Settings(data_dir=tmp_path, web_public_url=ORIGIN))):
            pass
    with pytest.raises(ValueError, match="auth.enabled"):
        Settings(web_public_url=ORIGIN, auth={"enabled": False})


@pytest.mark.parametrize(
    "url",
    [
        "*",
        "https://*.example.com",
        "https://admin:secret@example.com",
        "https://example.com/path",
        "https://example.com?q=1",
        "https://example.com#frag",
        "https://example.com:99999",
        "ftp://example.com",
        "https://example.com bad",
        "//example.com",
    ],
)
def test_public_url_validation(url):
    with pytest.raises(ValueError):
        Settings(web_public_url=url)


def test_public_url_normalization():
    assert Settings(web_public_url="https://TTS.example.com:443/").web_public_url == ORIGIN
    assert Settings(web_public_url="http://tts.example.test:8080").web_public_url.endswith(":8080")


def test_prepare_private_toml_preserves_source_and_existing_destination(tmp_path):
    source, destination = tmp_path / "source.toml", tmp_path / "config.toml"
    source.write_text('mode="simulation"\n# conservar comentario\n[sip]\npassword="test-only"\n')
    original = source.read_bytes()
    data = tmp_path / "state"
    assert prepare(source, destination, data)
    settings = load_settings(destination)
    assert settings.mode == "sip" and settings.web_public_url == ORIGIN
    assert settings.data_dir == data
    assert settings.voice_model == data / "voices/es_MX-claude-high.onnx"
    assert settings.sip.password == "test-only"
    assert len(settings.auth.bootstrap_password) >= 32
    assert destination.stat().st_mode & 0o777 == 0o600
    assert "# conservar comentario" in destination.read_text()
    assert source.read_bytes() == original
    saved = destination.read_bytes()
    assert not prepare(source, destination, data)
    assert destination.read_bytes() == saved


def test_preflight_checks_writable_layout_and_private_config(tmp_path):
    source, config_dir, data = tmp_path / "source.toml", tmp_path / "etc", tmp_path / "state"
    config_dir.mkdir()
    data.mkdir()
    source.write_text('mode="simulation"\n')
    destination = config_dir / "config.toml"
    prepare(source, destination, data)
    settings = load_settings(destination)
    check_layout(settings, data_dir=data, config_dir=config_dir)
    destination.chmod(0o644)
    with pytest.raises(ValueError, match="chmod 600"):
        check_layout(settings, data_dir=data, config_dir=config_dir)
    destination.chmod(0o600)
    settings.voice_model = tmp_path / "outside.onnx"
    with pytest.raises(ValueError, match="La voz"):
        check_layout(settings, data_dir=data, config_dir=config_dir)
    settings.voice_model = data / "voices/test.onnx"
    with sqlite3.connect(data / "blaster.sqlite3") as db:
        db.execute("CREATE TABLE users (role TEXT, enabled INTEGER)")
        db.execute("INSERT INTO users VALUES ('operator', 1)")
    with pytest.raises(ValueError, match="administrador habilitado"):
        check_layout(settings, data_dir=data, config_dir=config_dir)


def test_http_process_forwarding_and_sigterm_shutdown(tmp_path):
    # The actual Uvicorn entry point, with simulation so no trunk is opened.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = tmp_path / "config.toml"
    config.write_text(
        f'web_port={port}\nweb_public_url="{ORIGIN}"\ndata_dir="data"\n'
        f'[auth]\nbootstrap_username="admin"\nbootstrap_password="{PASSWORD}"\n'
        "[automation]\nenabled=false\n"
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    root = Path(__file__).resolve().parents[1]
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, "-B", "-u", str(root / "run.py"), "--config", str(config)],
            cwd=root,
            stdout=log,
            stderr=log,
            env={**os.environ, "PYTHONPATH": str(root / "src")},
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    with opener.open(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
                        assert json.load(response) == {"status": "ok"}
                    break
                except OSError:
                    if process.poll() is not None:
                        log.seek(0)
                        pytest.fail(log.read())
                    time.sleep(0.1)
            else:
                pytest.fail("El servidor HTTP no quedó disponible")
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/auth/login",
                data=json.dumps({"username": "admin", "password": PASSWORD}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Origin": ORIGIN,
                    "Host": "tts.example.com",
                    "X-Forwarded-Proto": "https",
                },
            )
            with opener.open(request, timeout=3) as response:
                assert response.status == 200
                assert "Secure" in response.headers["Set-Cookie"]
            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=15) in {0, -signal.SIGTERM}
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        log.seek(0)
        assert "Application shutdown complete" in log.read()
