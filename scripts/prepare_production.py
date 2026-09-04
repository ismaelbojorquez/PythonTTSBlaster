"""Prepare a private server TOML without overwriting existing configuration."""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from pathlib import Path

import tomlkit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from blaster.config import Settings, load_settings  # noqa: E402

PUBLIC_URL = "https://tts.example.com"
DATA_DIR = Path("/var/lib/pythonblastertts")


def prepare(source: Path, destination: Path, data_dir: Path = DATA_DIR) -> bool:
    if destination.exists():
        load_settings(destination)
        return False
    doc = tomlkit.parse(source.read_text(encoding="utf-8"))
    model_name = Path(doc.get("voice_model", "es_MX-claude-high.onnx")).name
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.onnx", model_name):
        raise ValueError("El modelo de voz debe ser un archivo .onnx con nombre simple")
    doc["mode"] = "sip"
    doc["web_public_url"] = doc.get("web_public_url") or PUBLIC_URL
    doc["data_dir"] = str(data_dir)
    doc["voice_model"] = str(data_dir / "voices" / model_name)
    auth = doc.setdefault("auth", tomlkit.table())
    auth["enabled"] = True
    if not auth.get("bootstrap_username") and not auth.get("bootstrap_password"):
        auth["bootstrap_username"] = "admin"
        auth["bootstrap_password"] = secrets.token_urlsafe(32)
        auth["bootstrap_display_name"] = "Administrador"
    Settings.model_validate(doc.unwrap())
    content = tomlkit.dumps(doc)
    # Exclusive creation protects an existing installation, including its secrets.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        created = prepare(args.source, args.destination)
    except (ValueError, OSError) as error:
        parser.exit(2, f"No se pudo preparar la configuración: {error}\n")
    print(
        "TOML privado creado; contraseña inicial guardada en [auth]."
        if created
        else "Se conserva el TOML existente, incluidas sus credenciales."
    )


if __name__ == "__main__":
    main()
