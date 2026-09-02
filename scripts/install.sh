#!/usr/bin/env bash
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}

if [ "$(uname -s)" != "Linux" ]; then
  echo "This MVP currently supports Linux only." >&2
  exit 1
fi

if [ -r /etc/os-release ]; then
  . /etc/os-release
  echo "Detected Linux distribution: ${PRETTY_NAME:-${ID:-unknown}}"
else
  echo "Detected Linux (distribution unknown)"
fi

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10 or newer is required")
print(f"Python {sys.version.split()[0]} is supported")
PY

if [ ! -d "$PROJECT_ROOT/.venv" ]; then
  "$PYTHON_BIN" -m venv "$PROJECT_ROOT/.venv"
fi

"$PROJECT_ROOT/.venv/bin/python" -m pip install -e "$PROJECT_ROOT"

CONFIG_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/local-assistant
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
  cp "$PROJECT_ROOT/config/default.yaml" "$CONFIG_DIR/config.yaml"
fi

"$PROJECT_ROOT/scripts/healthcheck.sh"

echo
echo "Installation complete. Starting Local Assistant..."
cd "$PROJECT_ROOT"
exec "$PROJECT_ROOT/.venv/bin/python" -m app.main

