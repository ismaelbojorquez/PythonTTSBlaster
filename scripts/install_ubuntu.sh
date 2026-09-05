#!/usr/bin/env bash
# Install from a checkout on the server. Never run this on the development Mac.
set -euo pipefail
# Code/virtualenv must be readable by the service account; the TOML is created 600.
umask 022

BLASTER_SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
BLASTER_APP=/opt/pythonblastertts
BLASTER_CONFIG=/etc/pythonblastertts/config.toml
BLASTER_STATE=/var/lib/pythonblastertts
BLASTER_INPUT=""
BLASTER_PREPARE_ONLY=false

usage() {
    printf '%s\n' 'Uso: sudo bash scripts/install_ubuntu.sh [--config /ruta/config.production.toml] [--prepare-only]'
}
fail() { printf '%s\n' "$*" >&2; exit 1; }
while (($#)); do
    case "$1" in
        --config) (($# >= 2)) || { usage; exit 2; }; BLASTER_INPUT="$2"; shift 2 ;;
        --prepare-only) BLASTER_PREPARE_ONLY=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; exit 2 ;;
    esac
done
[[ "$(uname -s)" == Linux ]] || fail 'Este instalador se ejecuta en el servidor Ubuntu.'
[[ $EUID -eq 0 ]] || fail 'Ejecuta el instalador con sudo.'
[[ -d /run/systemd/system ]] || fail 'Se necesita Ubuntu con systemd como gestor de servicios.'
[[ -f /etc/os-release ]] || fail 'No se pudo identificar Ubuntu.'
[[ "$(. /etc/os-release; printf '%s' "$ID")" == ubuntu ]] || fail 'Este instalador está preparado para Ubuntu.'
case "$(systemctl show blaster.service --property=ActiveState --value 2>/dev/null || true)" in
    active|activating|reloading|deactivating)
        fail 'Blaster está activo o reiniciándose. Finaliza las llamadas y ejecuta sudo systemctl stop blaster antes de actualizar.' ;;
esac
if [[ -z "$BLASTER_INPUT" ]]; then
    if [[ -f "$BLASTER_SOURCE/config.production.toml" ]]; then
        BLASTER_INPUT="$BLASTER_SOURCE/config.production.toml"
    else
        BLASTER_INPUT="$BLASTER_SOURCE/deploy/config.example.toml"
    fi
fi
[[ -f "$BLASTER_INPUT" ]] || fail "No existe el TOML: $BLASTER_INPUT"
BLASTER_INPUT="$(realpath -- "$BLASTER_INPUT")"

# Ubuntu 24.04 supplies Python 3.12. Reuse 3.12/3.13 when already installed.
BLASTER_PYTHON=""
for BLASTER_CANDIDATE in "$BLASTER_APP/.venv/bin/python" python3.12 python3.13 python3; do
    if command -v "$BLASTER_CANDIDATE" >/dev/null 2>&1 && \
       "$BLASTER_CANDIDATE" -c 'import sys; sys.exit(not ((3,12) <= sys.version_info[:2] < (3,14)))'; then
        BLASTER_PYTHON="$(command -v "$BLASTER_CANDIDATE")"
        break
    fi
done
[[ -n "$BLASTER_PYTHON" ]] || fail 'Instala Python 3.12 o 3.13 con sus paquetes -venv y -dev. Ubuntu 24.04 usa 3.12; Python 3.10/3.14 no sirven para este despliegue.'
BLASTER_PYTHON_VERSION="$("$BLASTER_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
apt-get update
apt-get install -y build-essential pkg-config swig rsync ca-certificates \
    "python${BLASTER_PYTHON_VERSION}-venv" "python${BLASTER_PYTHON_VERSION}-dev" \
    libsndfile1 libopus-dev

if ! id blaster >/dev/null 2>&1; then
    useradd --system --user-group --home-dir "$BLASTER_STATE" --shell /usr/sbin/nologin blaster
fi
install -d -o root -g root -m 0755 "$BLASTER_APP"
install -d -o blaster -g blaster -m 0750 /etc/pythonblastertts "$BLASTER_STATE" "$BLASTER_STATE/voices"
if [[ "$BLASTER_SOURCE" != "$BLASTER_APP" ]]; then
    for BLASTER_DIR in src scripts deploy docs; do
        install -d -m 0755 "$BLASTER_APP/$BLASTER_DIR"
        rsync -a --delete --chown=root:root --chmod=D755,F644 \
            --exclude='__pycache__/' --exclude='*.egg-info/' \
            "$BLASTER_SOURCE/$BLASTER_DIR/" "$BLASTER_APP/$BLASTER_DIR/"
    done
    for BLASTER_FILE in pyproject.toml constraints.txt config.example.toml run.py \
        README.md INSTALL.md CONTRIBUTING.md SECURITY.md PRODUCT.md DESIGN.md \
        LICENSE THIRD_PARTY.md; do
        install -o root -g root -m 0644 "$BLASTER_SOURCE/$BLASTER_FILE" "$BLASTER_APP/$BLASTER_FILE"
    done
fi
cd -- "$BLASTER_APP"
if [[ ! -x .venv/bin/python ]]; then
    "$BLASTER_PYTHON" -m venv .venv
fi
.venv/bin/python -c 'import sys; sys.exit(not ((3,12) <= sys.version_info[:2] < (3,14)))' || \
    fail 'El entorno .venv del servidor debe usar Python 3.12 o 3.13.'
.venv/bin/python -m pip install -c constraints.txt '.[voice]' setuptools wheel
.venv/bin/python scripts/build_pjsua2.py
.venv/bin/python scripts/prepare_production.py --source "$BLASTER_INPUT" --destination "$BLASTER_CONFIG"
chown blaster:blaster "$BLASTER_CONFIG"
chmod 0600 "$BLASTER_CONFIG"

BLASTER_VOICE="$(.venv/bin/python - "$BLASTER_CONFIG" <<'PY'
import sys, tomllib
from pathlib import Path
with open(sys.argv[1], 'rb') as source:
    settings = tomllib.load(source)
voice = Path(settings['voice_model'])
if voice.parent != Path('/var/lib/pythonblastertts/voices') or voice.suffix != '.onnx':
    raise SystemExit('voice_model debe estar en /var/lib/pythonblastertts/voices y terminar en .onnx')
print(voice.stem)
PY
)"
if [[ ! -s "$BLASTER_STATE/voices/$BLASTER_VOICE.onnx" || ! -s "$BLASTER_STATE/voices/$BLASTER_VOICE.onnx.json" ]]; then
    .venv/bin/python -m piper.download_voices "$BLASTER_VOICE" --download-dir "$BLASTER_STATE/voices" --force-redownload
fi
chown -R blaster:blaster "$BLASTER_STATE"
install -o root -g root -m 0644 deploy/blaster.service /etc/systemd/system/blaster.service
systemd-analyze verify /etc/systemd/system/blaster.service
systemctl daemon-reload

if $BLASTER_PREPARE_ONLY; then
    printf '%s\n' 'Preparación terminada. Edita /etc/pythonblastertts/config.toml y ejecuta de nuevo el instalador sin --prepare-only.'
    exit 0
fi
runuser -u blaster -- .venv/bin/python scripts/check_production.py --config "$BLASTER_CONFIG"
systemctl enable --now blaster.service
if ! runuser -u blaster -- .venv/bin/python scripts/check_production.py --config "$BLASTER_CONFIG" --wait 120; then
    systemctl status blaster.service --no-pager || true
    fail 'Revisa sudo journalctl -u blaster -n 100 --no-pager antes de continuar.'
fi
printf '%s\n' 'Blaster está ejecutándose y habilitado al arrancar Ubuntu.' \
    'Consulta el administrador inicial en [auth] de /etc/pythonblastertts/config.toml.' \
    'Cloudflare Tunnel debe apuntar a HTTP 127.0.0.1 y al web_port del TOML (8765 por defecto). Consulta INSTALL.md.'
