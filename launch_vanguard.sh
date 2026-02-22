#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

LOG_DIR="$ROOT_DIR/logs"
RUN_DIR="$ROOT_DIR/run"
CRON_LOG="$LOG_DIR/vanguard_cron.log"
CRON_PID_FILE="$RUN_DIR/vanguard_cron.pid"

mkdir -p "$LOG_DIR" "$RUN_DIR"

# 1) Build environment and dependencies.
"$ROOT_DIR/scripts/setup_env.sh"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "[LAUNCH] Missing .env file. Create it from .env.example first."
  exit 1
fi

source "$ROOT_DIR/.venv/bin/activate"

# 2) Final startup checks (core env keys, DB, Gemini, optional SendGrid reachability).
python -m src.vanguard.health --check-only

# 3) Run database migrations / table updates.
python -m src.vanguard.migrate

# 4) Start autonomous agent loop in background if not already running.
if [[ -f "$CRON_PID_FILE" ]] && kill -0 "$(cat "$CRON_PID_FILE")" 2>/dev/null; then
  echo "[LAUNCH] cron.py already running with PID $(cat "$CRON_PID_FILE")"
else
  nohup python -m src.vanguard.cron >> "$CRON_LOG" 2>&1 &
  echo "$!" > "$CRON_PID_FILE"
  echo "[LAUNCH] started cron.py in background (PID $(cat "$CRON_PID_FILE"))"
fi

# 5) Launch dashboard in foreground.
DASHBOARD_PORT="${DASHBOARD_PORT:-8501}"
echo "[LAUNCH] starting Streamlit dashboard on port $DASHBOARD_PORT"
exec streamlit run src/vanguard/dashboard.py --server.port "$DASHBOARD_PORT"
