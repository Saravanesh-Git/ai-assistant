#!/usr/bin/env bash
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VENV="$PROJECT_ROOT/.venv"

if [ -d "$VENV" ] && [ -f "$VENV/pyvenv.cfg" ]; then
  rm -rf -- "$VENV"
  echo "Removed the project virtual environment: $VENV"
else
  echo "No project virtual environment found."
fi

echo "Source files and user configuration were preserved."

