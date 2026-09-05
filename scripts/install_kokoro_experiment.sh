#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3.13}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python3.12"
fi

"$PYTHON_BIN" -m venv .venv-kokoro
.venv-kokoro/bin/python -m pip install --upgrade 'pip<27'
.venv-kokoro/bin/python -m pip install 'kokoro-onnx==0.6.1' 'soundfile==0.13.1'

mkdir -p .cache/kokoro/models .cache/kokoro/benchmarks
curl -fL --retry 3 -o .cache/kokoro/models/kokoro-v1.0.onnx \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx
curl -fL --retry 3 -o .cache/kokoro/models/voices-v1.0.bin \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin

.venv-kokoro/bin/python - <<'PY'
import hashlib
from pathlib import Path

expected = {
    "kokoro-v1.0.onnx": "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
root = Path(".cache/kokoro/models")
for name, wanted in expected.items():
    received = hashlib.sha256((root / name).read_bytes()).hexdigest()
    if received != wanted:
        raise SystemExit(f"El archivo {name} no coincide con la publicación oficial")
PY

echo "Kokoro quedó instalado de forma aislada. Piper continúa disponible."
