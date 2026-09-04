"""Check service prerequisites or wait for its HTTP health endpoint; never dial."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from blaster.config import load_settings  # noqa: E402

DATA_DIR = Path("/var/lib/pythonblastertts")
CONFIG_DIR = Path("/etc/pythonblastertts")


def check_layout(settings, *, data_dir=DATA_DIR, config_dir=CONFIG_DIR):
    if settings.mode != "sip":
        raise ValueError('Producción requiere mode = "sip"')
    if not settings.web_public_url or not settings.auth.enabled:
        raise ValueError("Configura web_public_url y auth.enabled = true")
    if settings.data_dir.resolve() != data_dir.resolve():
        raise ValueError(f"Este servicio requiere data_dir = {str(data_dir)!r}")
    if settings.config_path.parent.resolve() != config_dir.resolve():
        raise ValueError(f"El TOML de este servicio debe estar en {config_dir}")
    if not settings.voice_model.resolve().is_relative_to(data_dir.resolve() / "voices"):
        raise ValueError(f"La voz de este servicio debe estar en {data_dir / 'voices'}")
    if settings.config_path.stat().st_mode & 0o077:
        raise ValueError("El TOML contiene contraseñas: aplica chmod 600 al archivo")
    if not os.access(settings.config_path, os.R_OK | os.W_OK):
        raise ValueError("El usuario del servicio necesita leer y guardar el TOML")
    for directory in (config_dir, data_dir):
        # Configuration updates use atomic replacement, requiring directory write access.
        with tempfile.TemporaryFile(dir=directory):
            pass
    db_path = data_dir / "blaster.sqlite3"
    has_admin = False
    has_users = False
    if db_path.exists():
        with sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone():
                has_users = bool(db.execute("SELECT 1 FROM users LIMIT 1").fetchone())
                has_admin = bool(
                    db.execute(
                        "SELECT 1 FROM users WHERE role='admin' AND enabled=1 LIMIT 1"
                    ).fetchone()
                )
    if has_users and not has_admin:
        raise ValueError(
            "La base existente necesita un administrador habilitado; no se reemplazan sus usuarios"
        )
    if not has_users and not settings.auth.bootstrap_username:
        raise ValueError("Configura el administrador inicial en auth.bootstrap_username/password")


def check(settings):
    check_layout(settings)
    settings.validate_live()
    for name in ("pjsua2", "piper", "soundfile"):
        try:
            importlib.import_module(name)
        except (ImportError, OSError) as error:
            raise ValueError(
                f"No se puede cargar {name}; revisa la instalación del servidor"
            ) from error
    import soundfile

    if settings.recordings.enabled and not soundfile.check_format("OGG", "OPUS"):
        raise ValueError("libsndfile no admite Ogg Opus; revisa SoundFile y libopus")


def wait_ready(port, timeout):
    deadline = time.monotonic() + timeout
    # Ignore proxy environment variables: this is strictly a loopback probe.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with opener.open(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
                if response.status == 200 and json.load(response) == {"status": "ok"}:
                    return
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise ValueError(
        "El panel no respondió a /healthz dentro del plazo; revisa journalctl -u blaster"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--wait", type=int, metavar="SECONDS", default=0)
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
        if args.wait:
            wait_ready(settings.web_port, args.wait)
        else:
            check(settings)
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(2, f"Verificación fallida: {error}\n")
    print(
        "Panel HTTP disponible." if args.wait else "Requisitos de producción válidos. Sin llamadas."
    )


if __name__ == "__main__":
    main()
