#!/usr/bin/env bash
# Runs the core service and the frontend dev server together, killing
# both on Ctrl+C. A plain bash script rather than inline Makefile
# recipe logic: `trap ... ; cmd & cmd & wait` inside a Makefile recipe
# reliably shuts both processes down but has been observed to make the
# `make` process itself crash on exit (still stops everything, just
# noisy), so this runs standalone and the Makefile just execs it.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

trap 'kill 0' EXIT INT TERM

echo "core:     http://localhost:8000"
echo "frontend: http://localhost:5173"

(cd "$ROOT_DIR/backend" && PYTHONPATH=. .venv/bin/uvicorn services.core.app:app --host 0.0.0.0 --port 8000 --reload) &
(cd "$ROOT_DIR/frontend" && npm run dev) &

wait
