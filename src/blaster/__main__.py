from __future__ import annotations

import argparse
import importlib.util
import logging
from pathlib import Path

import uvicorn

from blaster.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Python Blaster TTS · panel local y motor SIP")
    parser.add_argument("--config", type=Path, help="Archivo TOML; sin él se usa simulación")
    parser.add_argument("--check", action="store_true", help="Valida la configuración sin llamar")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        settings = load_settings(args.config)
        if settings.mode == "sip":
            settings.validate_live()
            modules = ["pjsua2"]
            if settings.tts_engine == "piper":
                modules.append("piper")
            for module in modules:
                if importlib.util.find_spec(module) is None:
                    raise ValueError(f"Falta el módulo {module}. Consulta README.md")
        if args.check:
            print(f"Configuración válida. Modo: {settings.mode}. No se han iniciado llamadas.")
            if settings.amd.enabled:
                print(
                    f"AMD local sin IA: activo; máximo {settings.amd.total_analysis_ms} ms; "
                    f"inciertos: {settings.amd.unknown_action}."
                )
            return
        from blaster.web import create_app

        # One process owns the SIP endpoint and SQLite. Never use reload or workers > 1.
        uvicorn.run(
            create_app(settings),
            host="127.0.0.1",
            port=settings.web_port,
            log_level="info",
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1,::1",
            timeout_graceful_shutdown=30,
        )
    except (ValueError, OSError) as error:
        parser.exit(2, f"No se pudo iniciar: {error}\n")


if __name__ == "__main__":
    main()
