#!/usr/bin/env bash
# loom setup — idempotent. Installs the python env, the ffmpeg binary and the voice model.
set -euo pipefail
SKILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export LOOM_MODEL_DIR="${LOOM_MODEL_DIR:-$HOME/.cache/loom/models}"
mkdir -p "$LOOM_MODEL_DIR"
cd "$SKILL"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "1/4  python + venv"
PY=${PYTHON:-python3}
$PY -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' || {
  echo "need python 3.9+"; exit 1; }
if [ ! -d .venv ]; then $PY -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q --upgrade pip

say "2/4  dependencies"
python -m pip install -q -r requirements.txt || {
  echo "core install failed — retry with: python -m pip install -r requirements.txt"; exit 1; }
python -m pip install -q scipy 2>/dev/null && echo "  + scipy (fast filters)" || echo "  - scipy (numpy fallback)"

say "3/4  voice model (Kokoro-82M, Apache-2.0, ~350 MB)"
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  if [ ! -f "$LOOM_MODEL_DIR/$f" ]; then
    echo "  downloading $f"
    curl -L --fail --progress-bar "$BASE/$f" -o "$LOOM_MODEL_DIR/$f"
  else
    echo "  $f present"
  fi
done

say "4/4  doctor"
cat > "$SKILL/.env" <<ENV
export LOOM_MODEL_DIR="$LOOM_MODEL_DIR"
ENV
python -m loom.cli doctor
python -m loom.cli doctor | grep -q READY && echo -e "\n\033[1;32mAll set\033[0m  (models in $LOOM_MODEL_DIR)" || {
  echo "NOT READY — see the lines above"; exit 1; }
echo "next:  bash scripts/selftest.sh"
