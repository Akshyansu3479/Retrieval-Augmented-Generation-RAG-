"""Structured logging setup using structlog."""

import logging
import sys
from typing import Any

import structlog

from app.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure stdlib logging and structlog processors.

    When ``settings.log_enabled`` is False, application logs are silenced
    (only critical+ would pass, and no stream handler is attached).
    """
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    if not settings.log_enabled:
        root_logger.addHandler(logging.NullHandler())
        root_logger.setLevel(logging.CRITICAL + 1)
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.processors.UnicodeDecoder(),
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
        return

    log_level = getattr(logging, settings.log_level, logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.log_json:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Quiet noisy third-party loggers unless DEBUG
    noisy_level = logging.DEBUG if log_level <= logging.DEBUG else logging.WARNING
    for noisy in ("uvicorn.access", "httpx", "httpcore", "celery", "amqp"):
        logging.getLogger(noisy).setLevel(noisy_level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
