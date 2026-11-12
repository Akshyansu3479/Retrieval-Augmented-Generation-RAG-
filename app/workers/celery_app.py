"""Celery application factory."""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "production_rag",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.ingestion_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    result_expires=86400,
    task_default_queue="ingestion",
    task_routes={
        "app.workers.ingestion_tasks.*": {"queue": "ingestion"},
    },
)


@worker_process_init.connect
def _init_worker_runtime(**_kwargs: object) -> None:
    from app.workers.runtime import init_worker_runtime

    init_worker_runtime()


@worker_process_shutdown.connect
def _shutdown_worker_runtime(**_kwargs: object) -> None:
    from app.workers.runtime import shutdown_worker_runtime

    shutdown_worker_runtime()
