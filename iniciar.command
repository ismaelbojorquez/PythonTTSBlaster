#!/bin/bash
# Arranque desde la carpeta del proyecto, también con doble clic en macOS.
set -euo pipefail

BLASTER_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$BLASTER_ROOT"

if [[ ! -x .venv/bin/python ]]; then
    printf '%s\n' 'Falta .venv/bin/python. Consulta docs/local.md para preparar el entorno.' >&2
    exit 1
fi
if [[ ! -f config.toml ]]; then
    printf '%s\n' 'Falta config.toml. Copia config.example.toml y configura la troncal.' >&2
    exit 1
fi

exec .venv/bin/python -B run.py --config config.toml "$@"
