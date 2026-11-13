#!/usr/bin/env bash
# Medical Tracker tab — upstream https://github.com/terra-femme/MedTracker
# Serves the cloned app on loopback. Chatbot extras (LangGraph) stay optional.
set -euo pipefail
LAB_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP="$LAB_ROOT/vendor/MedTracker"
# shellcheck source=ports.sh
source "$(dirname "$0")/ports.sh"
PORT="${MEDTRACKER_PORT}"
ACTION="${1:-start}"

if [[ ! -f "$APP/main.py" ]]; then
  echo "MedTracker is missing at $APP" >&2
  echo "Clone: git clone https://github.com/terra-femme/MedTracker.git \"$APP\"" >&2
  exit 1
fi

ensure_venv() {
  if [[ ! -x "$APP/.venv/bin/uvicorn" ]]; then
    python3 -m venv "$APP/.venv"
    "$APP/.venv/bin/pip" install -q \
      'fastapi>=0.115' 'uvicorn>=0.32' 'sqlalchemy>=2.0' 'pydantic>=2.5' \
      'python-dotenv>=1.0' 'python-multipart>=0.0.6' 'python-jose[cryptography]>=3.3' \
      'bcrypt>=4.0.1' 'apscheduler>=3.10' 'requests>=2.32' 'python-dateutil>=2.8'
  fi
}

case "$ACTION" in
  start)
    if ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
      echo "Medical Tracker already listening on http://127.0.0.1:${PORT}"
      exit 0
    fi
    ensure_venv
    echo "Starting Medical Tracker on http://127.0.0.1:${PORT}" >&2
    cd "$APP"
    export DATABASE_URL="sqlite:///${APP}/medtracker.db"
    exec "$APP/.venv/bin/uvicorn" main:app --host 127.0.0.1 --port "$PORT"
    ;;
  *)
    echo "Usage: $0 start" >&2
    exit 1
    ;;
esac
