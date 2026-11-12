"""Initialize / tear down shared clients inside Celery worker processes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import TypeVar

from app.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.database.postgres import close_postgres, init_postgres
from app.database.qdrant import close_qdrant, ensure_collection, init_qdrant
from app.database.redis import close_redis, init_redis
from app.storage.file_storage import close_minio, ensure_bucket, init_minio

logger = get_logger(__name__)
T = TypeVar("T")
_initialized = False


def init_worker_runtime() -> None:
    global _initialized
    settings = get_settings()
    configure_logging(settings)
    init_postgres(settings)
    init_redis(settings)
    init_qdrant(settings)
    ensure_collection(settings=settings)
    init_minio(settings)
    ensure_bucket(settings=settings)
    _initialized = True
    logger.info("celery_worker_runtime_ready")


def shutdown_worker_runtime() -> None:
    global _initialized
    if not _initialized:
        return

    async def _close() -> None:
        await close_redis()
        await close_postgres()

    try:
        asyncio.run(_close())
    except RuntimeError:
        # Event loop may already be closed during hard shutdown.
        pass
    close_qdrant()
    close_minio()
    _initialized = False
    logger.info("celery_worker_runtime_closed")


def run_async(coro: Coroutine[object, object, T] | Awaitable[T]) -> T:
    """Run an async coroutine from a sync Celery task."""
    return asyncio.run(coro)  # type: ignore[arg-type]
