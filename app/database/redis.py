"""Async Redis client for caching and job infrastructure."""

from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends

from app.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis_client: redis.Redis | None = None


def init_redis(settings: Settings | None = None) -> redis.Redis:
    """Create and cache the shared async Redis client."""
    global _redis_client
    cfg = settings or get_settings()
    if _redis_client is None:
        _redis_client = redis.from_url(
            cfg.redis_url,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        logger.info("redis_initialized", url=cfg.redis_url)
    return _redis_client


def get_redis() -> redis.Redis:
    if _redis_client is None:
        raise RuntimeError("Redis client is not initialized")
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        logger.info("redis_closed")
    _redis_client = None


async def check_redis() -> None:
    client = get_redis()
    pong = await client.ping()
    if pong is not True:
        raise RuntimeError(f"Unexpected Redis PING response: {pong}")


RedisClient = Annotated[redis.Redis, Depends(get_redis)]
