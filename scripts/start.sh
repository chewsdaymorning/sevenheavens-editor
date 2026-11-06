#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  echo "Project environment missing. Run: uv sync --locked" >&2
  exit 1
fi
exec .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port "${SEVENHEAVENS_PORT:-8765}"
