#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DB_USER="${VANGUARD_DB_USER:-vanguard_user}"
DB_NAME="${VANGUARD_DB_NAME:-vanguard}"
DB_HOST="${VANGUARD_DB_HOST:-localhost}"
DB_PORT="${VANGUARD_DB_PORT:-5432}"
ENV_FILE="$ROOT_DIR/.env"

log() {
  printf '[BOOTSTRAP] %s\n' "$1"
}

fail() {
  printf '[BOOTSTRAP][ERROR] %s\n' "$1" >&2
  exit 1
}

install_hint() {
  cat <<'EOF'
PostgreSQL client/server commands not found.
Install PostgreSQL first, then rerun this script.

Common install commands:
  Ubuntu/Debian: sudo apt update && sudo apt install -y postgresql postgresql-contrib
  Fedora/RHEL:   sudo dnf install -y postgresql-server postgresql-contrib
  Arch:          sudo pacman -S postgresql
  macOS (brew):  brew install postgresql@15
EOF
}

run_as_postgres() {
  local sql="$1"
  if command -v sudo >/dev/null 2>&1; then
    sudo -u postgres psql -v ON_ERROR_STOP=1 -Atqc "$sql"
  elif [[ "${USER:-}" == "postgres" ]]; then
    psql -v ON_ERROR_STOP=1 -Atqc "$sql"
  else
    fail "sudo not available and current user is not postgres. Run as postgres user."
  fi
}

start_postgres_service() {
  # If server is listening, don't force service management.
  if command -v pg_isready >/dev/null 2>&1 && pg_isready -h "$DB_HOST" -p "$DB_PORT" >/dev/null 2>&1; then
    log "PostgreSQL listener is already up on ${DB_HOST}:${DB_PORT}; skipping service start."
    return
  fi

  # If DB is already reachable as postgres superuser, skip service management.
  if run_as_postgres "SELECT 1;" >/dev/null 2>&1; then
    log "PostgreSQL is already reachable; skipping service start."
    return
  fi

  if command -v systemctl >/dev/null 2>&1; then
    if ! sudo systemctl start postgresql >/dev/null 2>&1; then
      if ! sudo systemctl start postgresql@15-main >/dev/null 2>&1; then
        fail "Unable to start PostgreSQL via systemctl. Start it manually and retry."
      fi
    fi
    log "PostgreSQL service started (systemctl)."
    return
  fi

  if command -v service >/dev/null 2>&1; then
    if service postgresql start >/dev/null 2>&1 || sudo service postgresql start >/dev/null 2>&1; then
      log "PostgreSQL service started (service)."
      return
    fi
  fi

  fail "Could not start PostgreSQL service automatically. Start service manually and retry."
}

ensure_env_file() {
  if [[ -f "$ENV_FILE" ]]; then
    return
  fi
  if [[ -f "$ROOT_DIR/.env.example" ]]; then
    cp "$ROOT_DIR/.env.example" "$ENV_FILE"
    log "Created .env from .env.example"
    return
  fi
  touch "$ENV_FILE"
  log "Created empty .env"
}

update_env_database_url() {
  local db_url="$1"
  if grep -q '^DATABASE_URL=' "$ENV_FILE"; then
    sed -i "s|^DATABASE_URL=.*|DATABASE_URL=${db_url}|" "$ENV_FILE"
  else
    printf '\nDATABASE_URL=%s\n' "$db_url" >> "$ENV_FILE"
  fi
}

main() {
  if ! command -v psql >/dev/null 2>&1; then
    install_hint
    exit 1
  fi

  log "Starting PostgreSQL service..."
  start_postgres_service

  if ! run_as_postgres "SELECT 1;" >/dev/null 2>&1; then
    fail "Cannot connect as postgres superuser. Check local PostgreSQL auth/service."
  fi

  local db_password="${VANGUARD_DB_PASSWORD:-}"
  if [[ -z "$db_password" ]]; then
    # Avoid pipefail/SIGPIPE issues from tr|head pipelines under strict mode.
    db_password="$(python3 - <<'PY'
import secrets
import string
alphabet = string.ascii_letters + string.digits
print("".join(secrets.choice(alphabet) for _ in range(24)))
PY
)"
  fi

  log "Ensuring role '$DB_USER' exists..."
  run_as_postgres "DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN PASSWORD '${db_password}';
  ELSE
    ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${db_password}';
  END IF;
END
\$\$;"

  log "Ensuring database '$DB_NAME' exists..."
  if [[ "$(run_as_postgres "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}';")" != "1" ]]; then
    run_as_postgres "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
  fi

  run_as_postgres "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"

  ensure_env_file
  local db_url="postgresql://${DB_USER}:${db_password}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
  update_env_database_url "$db_url"

  log "PostgreSQL bootstrap complete."
  log "Updated .env DATABASE_URL for user '${DB_USER}' and database '${DB_NAME}'."
  log "Next: run ./launch_vanguard.sh"
}

main "$@"
