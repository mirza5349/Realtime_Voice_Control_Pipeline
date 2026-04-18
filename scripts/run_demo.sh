#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

UV_BIN="${UV_BIN:-uv}"
APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-8000}"
RELOAD_ENABLED="${RELOAD_ENABLED:-false}"

if [[ ! -f .env ]]; then
  echo "[run_demo] .env not found, copying from .env.example"
  cp .env.example .env
fi

mkdir -p .data/audio .data/demo_assets

if [[ -x scripts/prepare_demo_assets.sh ]]; then
  scripts/prepare_demo_assets.sh || true
fi

echo "[run_demo] starting FastAPI server at http://${APP_HOST}:${APP_PORT}"
echo "[run_demo] demo UI available at http://${APP_HOST}:${APP_PORT}/demo"

RELOAD_ARGS=()
if [[ "${RELOAD_ENABLED}" == "true" ]]; then
  RELOAD_ARGS=(--reload --reload-dir src)
fi

exec "${UV_BIN}" run uvicorn app.main:app \
  --host "${APP_HOST}" \
  --port "${APP_PORT}" \
  "${RELOAD_ARGS[@]}"
