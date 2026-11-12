"""Async PostgreSQL engine and session management (SQLAlchemy 2.0)."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    """Create an async SQLAlchemy engine with connection pooling."""
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
    )


def init_postgres(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    """Initialize global engine and session factory."""
    global _engine, _session_factory

    cfg = settings or get_settings()
    if _engine is None:
        _engine = create_engine(cfg)
        _session_factory = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        logger.info("postgres_initialized", url_host=cfg.postgres_host)
    assert _session_factory is not None
    return _session_factory


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("PostgreSQL engine is not initialized")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("PostgreSQL session factory is not initialized")
    return _session_factory


async def close_postgres() -> None:
    """Dispose the async engine."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("postgres_closed")
    _engine = None
    _session_factory = None


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped async session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def check_postgres() -> None:
    """Execute a trivial query to verify connectivity."""
    from sqlalchemy import text

    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
