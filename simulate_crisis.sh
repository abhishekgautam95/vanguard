#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -d "$ROOT_DIR/.venv" ]]; then
  echo "[SIMULATE] .venv not found. Run ./scripts/setup_env.sh first."
  exit 1
fi

source "$ROOT_DIR/.venv/bin/activate"
python -m src.vanguard.simulate_crisis "$@"
