# Assistant ports — source from other scripts; do not echo secrets.
# UI (Vite + React): phone/browser entry; proxies /api → API.
# API (FastAPI):     bound to loopback only; never expose via ngrok directly.
export ASSISTANT_UI_PORT="${ASSISTANT_UI_PORT:-9241}"
export ASSISTANT_API_PORT="${ASSISTANT_API_PORT:-9242}"
export MEDTRACKER_PORT="${MEDTRACKER_PORT:-9255}"
