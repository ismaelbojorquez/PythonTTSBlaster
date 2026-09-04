"""Exercise the manual checker against a loopback registrar, never the user's trunk."""

import fcntl
import hashlib
import importlib.util
import re
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_sip.py"
PASSWORD = "test-secret$42"
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pjsua2") is None, reason="Necesita PJSUA2 local"
)


def make_config(directory, server_port):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.bind(("127.0.0.1", 0))
        local_port = client.getsockname()[1]
    config = directory / "config.toml"
    config.write_text(
        'data_dir = "state"\n'
        "[sip]\n"
        f'domain = "127.0.0.1:{server_port}"\n'
        'username = "probe"\n'
        f'password = "{PASSWORD}"\n'
        'bind_address = "127.0.0.1"\n'
        f"local_port = {local_port}\n",
        encoding="utf-8",
    )
    return config


def execute(config):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(config)],
        capture_output=True,
        text=True,
        timeout=12,
    )


@pytest.mark.parametrize("final_code", [200, 403, 408])
def test_manual_registration_and_response_origin(tmp_path, final_code):
    requests = []
    errors = []
    stop = threading.Event()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.1)
    config = make_config(tmp_path, sock.getsockname()[1])

    def serve():
        try:
            while not stop.is_set():
                try:
                    raw, address = sock.recvfrom(16000)
                except TimeoutError:
                    continue
                lines = raw.decode().split("\r\n")
                method = lines[0].split()[0]
                headers = dict(
                    (key.lower(), value.strip())
                    for key, value in (line.split(":", 1) for line in lines[1:] if ":" in line)
                )
                unregister = headers.get("expires") == "0"
                auth = headers.get("authorization", "")
                requests.append((method, unregister, bool(auth)))
                assert method == "REGISTER"
                response_code = final_code
                extra = []
                if final_code == 200:
                    if not auth:
                        response_code = 401
                        extra.append(
                            'WWW-Authenticate: Digest realm="local-test", nonce="one", '
                            'algorithm=MD5, qop="auth"'
                        )
                    else:
                        values = {
                            match[1]: match[2] or match[3]
                            for match in re.finditer(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', auth)
                        }

                        def md5(text):
                            return hashlib.md5(text.encode()).hexdigest()

                        ha1 = md5(f"probe:local-test:{PASSWORD}")
                        ha2 = md5(f"REGISTER:{values['uri']}")
                        expected = md5(f"{ha1}:one:{values['nc']}:{values['cnonce']}:auth:{ha2}")
                        assert values["response"] == expected
                        expires = "0" if unregister else "300"
                        extra.extend([f"Contact: {headers['contact']}", f"Expires: {expires}"])
                response = [f"SIP/2.0 {response_code} Test"]
                response.extend(
                    f"{key}: {headers[key.lower()]}"
                    for key in ("Via", "From", "To", "Call-ID", "CSeq")
                )
                response.extend([*extra, "Content-Length: 0", "", ""])
                sock.sendto("\r\n".join(response).encode(), address)
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        result = execute(config)
    finally:
        stop.set()
        thread.join(timeout=2)
        sock.close()
    assert not errors, errors
    output = result.stdout + result.stderr
    assert result.returncode == (0 if final_code == 200 else 1), output
    assert f"RX {final_code}" in output
    assert "respuesta recibida del servidor" in output
    assert PASSWORD not in output
    assert "Authorization:" not in output
    assert "response=" not in output
    if final_code == 200:
        assert "RX 401" in output
        assert "REGISTRO CORRECTO" in output
        assert any(unregister and authenticated for _, unregister, authenticated in requests)
    else:
        assert "REGISTRO CORRECTO" not in output


def test_running_panel_prevents_a_second_registration(tmp_path):
    config = make_config(tmp_path, 59999)
    state = tmp_path / "state"
    state.mkdir()
    with (state / "app.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = execute(config)
    assert result.returncode == 2
    assert "Detén el panel con Ctrl+C" in result.stderr
    assert "TX REGISTER" not in result.stdout
