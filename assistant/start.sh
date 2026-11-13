#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/ports.sh
source "$ROOT/scripts/ports.sh"
export VOLTA_HOME="${VOLTA_HOME:-$HOME/.volta}"
[[ -x "$VOLTA_HOME/bin/volta" ]] && export PATH="$VOLTA_HOME/bin:$PATH"
if [[ "${JARVIS_AUTO_START:-0}" == "1" ]]; then
  "$ROOT/scripts/jarvis.sh" start &
fi
if [[ "${MEDTRACKER_AUTO_START:-1}" == "1" ]]; then
  "$ROOT/scripts/medtracker.sh" start &
fi
if ss -ltn | grep -q ":${ASSISTANT_UI_PORT} "; then
  echo "Port ${ASSISTANT_UI_PORT} is already in use. Stop the other server first." >&2
  exit 1
fi
cd "$ROOT/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
LAN_ON="$("$ROOT/backend/.venv/bin/python" -c "from app import lan_access, db; c=db.connect(); print('1' if lan_access.lan_enabled(c) else '0'); c.close()" 2>/dev/null || echo 0)"
BIND_HOST="127.0.0.1"
VITE_HOST="127.0.0.1"
if [[ "$LAN_ON" == "1" ]]; then
  BIND_HOST="0.0.0.0"
  VITE_HOST="0.0.0.0"
  echo "LAN access enabled — listening on all interfaces (local network only)." >&2
fi
if ss -ltn 2>/dev/null | grep -q ":${ASSISTANT_API_PORT} "; then
  echo "Port ${ASSISTANT_API_PORT} in use — stopping previous Assistant API so routes stay up to date…" >&2
  pkill -f 'uvicorn app.main:app --host' 2>/dev/null || true
  sleep 1
fi
.venv/bin/uvicorn app.main:app --host "$BIND_HOST" --port "$ASSISTANT_API_PORT" &
API_PID=$!
cd "$ROOT/web"
if [[ ! -d node_modules ]]; then
  npm install
fi
trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM
npm run dev -- --host "$VITE_HOST"
