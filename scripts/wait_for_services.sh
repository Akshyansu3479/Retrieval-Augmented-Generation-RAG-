#!/usr/bin/env sh
# Optional helper for local scripting — waits until /health responds.
set -eu

HOST="${1:-http://localhost:8000}"
RETRIES="${2:-60}"

echo "Waiting for ${HOST}/health ..."
i=0
while [ "$i" -lt "$RETRIES" ]; do
  if curl -fsS "${HOST}/health" >/dev/null 2>&1; then
    echo "API is healthy."
    exit 0
  fi
  i=$((i + 1))
  sleep 2
done

echo "Timed out waiting for API health." >&2
exit 1
