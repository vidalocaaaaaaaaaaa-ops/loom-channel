#!/usr/bin/env bash
# Build one short video per style and check every gate. Prints SELFTEST PASSED.
set -euo pipefail
SKILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SKILL"
[ -f .env ] && source .env
[ -d .venv ] && source .venv/bin/activate
export LOOM_MODEL_DIR="${LOOM_MODEL_DIR:-$HOME/.cache/loom/models}"
python -m loom.selftest "$@"
