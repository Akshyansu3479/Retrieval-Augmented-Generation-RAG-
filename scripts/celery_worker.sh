#!/usr/bin/env sh
set -eu

echo "Running database migrations (worker)..."
alembic upgrade head

echo "Starting Celery worker..."
exec celery -A app.workers.celery_app.celery_app worker \
  --loglevel="${LOG_LEVEL:-INFO}" \
  --queues=ingestion \
  --concurrency="${CELERY_CONCURRENCY:-2}" \
  --hostname="rag-worker@%h"
