#!/usr/bin/env sh
set -eu

echo "Running database migrations..."
alembic upgrade head

echo "Starting API..."
exec uvicorn app.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}"
