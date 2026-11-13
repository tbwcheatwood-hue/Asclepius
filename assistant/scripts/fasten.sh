#!/usr/bin/env bash
# Fasten Health on-prem — https://github.com/fastenhealth/fasten-onprem
# Serves the official image on https://127.0.0.1:9090 (container port 8080).
set -euo pipefail
LAB_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DATA="$LAB_ROOT/vendor/fasten-onprem"
IMAGE="${FASTEN_IMAGE:-ghcr.io/fastenhealth/fasten-onprem:main}"
PORT="${FASTEN_PORT:-9090}"
NAME="${FASTEN_CONTAINER:-fasten-onprem}"
ACTION="${1:-start}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required to run Fasten Health on-prem." >&2
  exit 1
fi

case "$ACTION" in
  start)
    if ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
      echo "Fasten already listening on https://127.0.0.1:${PORT}"
      exit 0
    fi
    mkdir -p "$DATA/db" "$DATA/cache" "$DATA/certs"
    if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
      docker start "$NAME"
    else
      docker run -d --name "$NAME" \
        -p "${PORT}:8080" \
        -e "HOST_PORT=${PORT}" \
        -v "$DATA/db:/opt/fasten/db" \
        -v "$DATA/cache:/opt/fasten/cache" \
        -v "$DATA/certs:/opt/fasten/certs/shared" \
        "$IMAGE"
    fi
    if ! ss -ltn 2>/dev/null | grep -q ':9091 '; then
      nohup python3 "$(dirname "$0")/fasten-http-proxy.py" >/tmp/fasten-http-proxy.log 2>&1 &
    fi
    echo "Fasten Health on-prem: http://127.0.0.1:9091"
    echo "The container itself is HTTPS on port ${PORT}. The Assistant embeds the local HTTP proxy."
    ;;
  *)
    echo "Usage: $0 start" >&2
    exit 1
    ;;
esac
