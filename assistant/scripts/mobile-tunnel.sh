#!/usr/bin/env bash
# Assistant UI on :9241 — separate ngrok from NOMAD (:8080, reserved domain).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=ports.sh
source "$ROOT/scripts/ports.sh"
ENV_FILE="${ASSISTANT_TUNNEL_ENV:-$ROOT/secrets/mobile-tunnel.env}"
EXAMPLE="$ROOT/config/mobile-tunnel.env.example"
SECRETS_DIR="$ROOT/secrets"

mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR" 2>/dev/null || true
[[ -f "$ENV_FILE" ]] || { cp "$EXAMPLE" "$ENV_FILE"; chmod 600 "$ENV_FILE"; }
# shellcheck disable=SC1090
source "$ENV_FILE"

# NOMAD keeps this URL → localhost:8080 (do not steal it).
NOMAD_NGROK_URL="${NOMAD_NGROK_URL:-}"
NOMAD_LOCAL_PORT="${NOMAD_LOCAL_PORT:-8080}"
# Assistant: optional reserved URL; leave empty for a new random *.ngrok-free.dev URL.
NGROK_URL="${NGROK_URL:-}"
TP_REL="${NGROK_TRAFFIC_POLICY_FILE:-config/tp.yml}"
TP_FILE="$ROOT/$TP_REL"
[[ -f "$TP_FILE" ]] || { echo "Missing traffic policy: $TP_FILE" >&2; exit 1; }

if [[ -n "${NGROK_URL}" ]] && [[ "${NGROK_URL%/}" == "${NOMAD_NGROK_URL%/}" ]]; then
  echo "NGROK_URL must not be NOMAD's domain (${NOMAD_NGROK_URL})." >&2
  echo "Clear NGROK_URL in $ENV_FILE or set a second reserved domain from ngrok dashboard." >&2
  exit 1
fi

if [[ -n "${TUNNEL_OAUTH_EMAIL:-}" ]] && [[ "$TP_FILE" == "$ROOT/config/tp.yml" ]]; then
  TP_FILE="$SECRETS_DIR/tp.local.yml"
  sed "s/you@example.com/${TUNNEL_OAUTH_EMAIL}/g" "$ROOT/config/tp.yml" >"$TP_FILE"
  chmod 600 "$TP_FILE"
fi

if [[ -z "${NGROK_AUTHTOKEN:-}" ]] && [[ -f "${HOME}/.config/ngrok/ngrok.yml" ]]; then
  NGROK_AUTHTOKEN="$(python3 - <<'PY' 2>/dev/null || true
import pathlib, re
text = pathlib.Path.home().joinpath(".config/ngrok/ngrok.yml").read_text()
m = re.search(r"^\s*authtoken:\s*(\S+)\s*$", text, re.M)
print(m.group(1) if m else "", end="")
PY
)"
  export NGROK_AUTHTOKEN
fi
[[ -n "${NGROK_AUTHTOKEN:-}" ]] || { echo "Set NGROK_AUTHTOKEN in $ENV_FILE or: ngrok config add-authtoken <token>" >&2; exit 1; }
command -v ngrok >/dev/null 2>&1 || { echo "Install ngrok: sudo snap install ngrok" >&2; exit 1; }

export VOLTA_HOME="${VOLTA_HOME:-$HOME/.volta}"
[[ -x "$VOLTA_HOME/bin/volta" ]] && export PATH="$VOLTA_HOME/bin:$PATH"
export ASSISTANT_TUNNEL_MODE=1
export NGROK_AUTHTOKEN
export VITE_HOST=127.0.0.1

pick_ngrok_web_port() {
  local body
  body="$(curl -fsS "http://127.0.0.1:4040/api/tunnels" 2>/dev/null || true)"
  if [[ -z "$body" ]]; then
    echo "4040"
    return
  fi
  local is_nomad
  is_nomad="$(
    BODY="$body" NOMAD_URL="${NOMAD_NGROK_URL%/}" NOMAD_PORT="$NOMAD_LOCAL_PORT" python3 <<'PY'
import json, os
data = json.loads(os.environ["BODY"])
nomad_url = os.environ["NOMAD_URL"]
port = f":{os.environ['NOMAD_PORT']}"
for t in data.get("tunnels") or []:
    pub = (t.get("public_url") or "").rstrip("/")
    addr = (t.get("config") or {}).get("addr", "")
    if pub == nomad_url and port in addr:
        print("yes")
        raise SystemExit
print("no")
PY
  )"
  if [[ "$is_nomad" == yes ]]; then
    echo "NOMAD stays on ${NOMAD_NGROK_URL} → :${NOMAD_LOCAL_PORT}; Assistant ngrok uses web UI :4041." >&2
    echo "4041"
  else
    echo "4040"
  fi
}

NGROK_WEB_PORT="${NGROK_WEB_PORT:-$(pick_ngrok_web_port)}"
NGROK_API="http://127.0.0.1:${NGROK_WEB_PORT}/api/tunnels"

API_PID=""
VITE_PID=""
NGROK_PID=""

cleanup() {
  [[ -n "$NGROK_PID" ]] && kill "$NGROK_PID" 2>/dev/null || true
  [[ -n "$VITE_PID" ]] && kill "$VITE_PID" 2>/dev/null || true
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [[ "${ASSISTANT_TUNNEL_REUSE:-0}" != "1" ]]; then
  echo "Assistant UI :${ASSISTANT_UI_PORT}, API :${ASSISTANT_API_PORT} (local only)." >&2
  pkill -f 'uvicorn app.main:app --host' 2>/dev/null || true
  fuser -k "${ASSISTANT_UI_PORT}/tcp" 2>/dev/null || true
  fuser -k "${ASSISTANT_API_PORT}/tcp" 2>/dev/null || true
  fuser -k "${NGROK_WEB_PORT}/tcp" 2>/dev/null || true
  sleep 1
fi

cd "$ROOT/backend"
[[ -d .venv ]] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -q; }

PAIR_CODE="$(
  .venv/bin/python - <<'PY'
from app import db, lan_access
conn = db.connect()
try:
    db.migrate(conn)
    lan_access.cleanup_expired(conn)
    print(lan_access.enable_lan(conn)["pairing_code"])
    conn.commit()
finally:
    conn.close()
PY
)"

.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$ASSISTANT_API_PORT" &
API_PID=$!

cd "$ROOT/web"
[[ -d node_modules ]] || npm install --silent
npm run dev -- --host 127.0.0.1 --port "$ASSISTANT_UI_PORT" &
VITE_PID=$!
sleep 2

if ! curl -fsS "http://127.0.0.1:${ASSISTANT_UI_PORT}/" >/dev/null 2>&1; then
  echo "UI not responding on 127.0.0.1:${ASSISTANT_UI_PORT}." >&2
  exit 1
fi

NGROK_CMD=(ngrok http "127.0.0.1:${ASSISTANT_UI_PORT}" --traffic-policy-file="$TP_FILE" --web-addr="127.0.0.1:${NGROK_WEB_PORT}" --log=stdout)
if [[ -n "${NGROK_URL}" ]]; then
  NGROK_CMD+=(--url="${NGROK_URL}")
  echo "Reserved Assistant URL: ${NGROK_URL}" >&2
else
  echo "Assistant gets a new random ngrok URL (NOMAD keeps ${NOMAD_NGROK_URL})." >&2
fi

"${NGROK_CMD[@]}" &
NGROK_PID=$!

PUBLIC_URL=""
for _ in $(seq 1 60); do
  sleep 1
  kill -0 "$NGROK_PID" 2>/dev/null || { echo "Assistant ngrok exited." >&2; exit 1; }
  BODY="$(curl -fsS "$NGROK_API" 2>/dev/null || true)"
  [[ -z "$BODY" ]] && continue
  PUBLIC_URL="$(
    BODY="$BODY" WANT_PORT="$ASSISTANT_UI_PORT" python3 <<'PY'
import json, os
data = json.loads(os.environ["BODY"])
want = f":{os.environ['WANT_PORT']}"
for t in data.get("tunnels") or []:
    addr = (t.get("config") or {}).get("addr", "")
    pub = (t.get("public_url") or "")
    if want in addr and pub.startswith("https"):
        print(pub.rstrip("/"))
        break
PY
  )"
  [[ -n "$PUBLIC_URL" ]] && break
done

[[ -n "$PUBLIC_URL" ]] || { echo "Timed out waiting for Assistant tunnel URL (inspect http://127.0.0.1:${NGROK_WEB_PORT})." >&2; exit 1; }

export ASSISTANT_TUNNEL_ORIGIN="$PUBLIC_URL"
export ASSISTANT_TUNNEL_HOST="$(python3 -c "from urllib.parse import urlparse; print(urlparse('$PUBLIC_URL').hostname or '')")"

kill "$API_PID" 2>/dev/null || true
wait "$API_PID" 2>/dev/null || true
cd "$ROOT/backend"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$ASSISTANT_API_PORT" &
API_PID=$!

cat <<EOF

══════════════════════════════════════════════════════════════════════
 NOMAD (unchanged)     ${NOMAD_NGROK_URL}  →  :${NOMAD_LOCAL_PORT}
 ASSISTANT (phone)     ${PUBLIC_URL}  →  :${ASSISTANT_UI_PORT}
 Pair code:             ${PAIR_CODE}
══════════════════════════════════════════════════════════════════════
 PHONE: cellular/other Wi‑Fi → open ASSISTANT URL above (not NOMAD URL)
        → Google sign-in → Pair this device → enter ${PAIR_CODE}
 Ctrl+C here stops Assistant tunnel only (NOMAD ngrok on :4040 keeps running).
══════════════════════════════════════════════════════════════════════
EOF

if command -v qrencode >/dev/null 2>&1; then
  qrencode -t ANSIUTF8 "$PUBLIC_URL" 2>/dev/null || qrencode -t UTF8 "$PUBLIC_URL"
fi

wait "$NGROK_PID"
