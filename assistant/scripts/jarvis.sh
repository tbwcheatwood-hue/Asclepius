#!/usr/bin/env bash
# Personal Jarvis from a local clone (default: ~/Downloads/PersonalJarvis-main).
# Upstream: https://github.com/tbckdev/PersonalJarvis.git
set -euo pipefail

JARVIS_ROOT="${JARVIS_ROOT:-$HOME/Downloads/PersonalJarvis-main}"
ASSISTANT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ASSISTANT_ROOT/jarvis-venv"
PORT="${JARVIS_PORT:-47821}"
ACTION="${1:-status}"

python_bin() {
  if [[ -x "$VENV/bin/python" ]]; then
    echo "$VENV/bin/python"
  else
    echo "python3"
  fi
}

jarvis_cli() {
  if [[ -x "$VENV/bin/jarvis" ]]; then
    echo "$VENV/bin/jarvis"
  elif [[ -x "$VENV/bin/python" ]]; then
    echo "$VENV/bin/python -m jarvis"
  else
    echo ""
  fi
}

case "$ACTION" in
  status)
    if [[ ! -d "$JARVIS_ROOT" ]]; then
      echo "JARVIS_ROOT missing: $JARVIS_ROOT" >&2
      exit 1
    fi
    echo "JARVIS_ROOT=$JARVIS_ROOT"
    echo "JARVIS_VENV=$VENV"
    if curl -sf "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
      echo "JARVIS: running on http://127.0.0.1:${PORT}"
    else
      echo "JARVIS: not running (assistant/scripts/jarvis.sh start)"
    fi
    ;;
  install)
    if [[ ! -d "$JARVIS_ROOT" ]]; then
      echo "JARVIS_ROOT missing: $JARVIS_ROOT" >&2
      echo "Clone: git clone https://github.com/tbckdev/PersonalJarvis.git \"$JARVIS_ROOT\"" >&2
      exit 1
    fi
    if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      echo "Personal Jarvis requires Python 3.11 or newer." >&2
      exit 1
    fi
    if [[ ! -d "$VENV" ]]; then
      python3 -m venv "$VENV"
    fi
    "$VENV/bin/pip" install -U pip wheel
    echo "Installing Personal Jarvis (editable) — this can take several minutes…" >&2
    "$VENV/bin/pip" install -e "$JARVIS_ROOT"
    echo "Done. Run: assistant/scripts/jarvis.sh start"
    ;;
  start)
    if [[ ! -d "$JARVIS_ROOT" ]]; then
      echo "JARVIS_ROOT missing: $JARVIS_ROOT" >&2
      exit 1
    fi
    if [[ ! -x "$VENV/bin/python" ]]; then
      echo "Run $0 install first." >&2
      exit 1
    fi
    if ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
      echo "Port ${PORT} already in use; JARVIS may already be running."
      exit 0
    fi
    echo "Starting JARVIS (headless) on http://127.0.0.1:${PORT} …" >&2
    if [[ -x "$VENV/bin/jarvis" ]]; then
      exec "$VENV/bin/jarvis" serve
    fi
    exec "$VENV/bin/python" -m jarvis.ui.web.launcher --headless
    ;;
  link-assistant)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
    exec bash "$SCRIPT_DIR/jarvis-link-assistant.sh"
    ;;
  wire-locals)
    if [[ ! -x "$VENV/bin/python" ]]; then
      echo "Run $0 install first." >&2
      exit 1
    fi
    exec "$VENV/bin/python" "$(cd "$(dirname "$0")" && pwd)/jarvis-wire-locals.py" "$@"
    ;;
  *)
    echo "Usage: $0 {status|install|start|wire-locals|link-assistant}" >&2
    exit 1
    ;;
esac
