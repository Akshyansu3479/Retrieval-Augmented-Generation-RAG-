"""Pipeline flow logging helpers (honours Settings.log_enabled via root logger)."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

logger = get_logger("rag.flow")


def flow(stage: str, message: str, **fields: Any) -> None:
    """
    Log a named pipeline stage.

    Example stages: chat.start, retrieve.query, retrieve.hybrid,
    context.build, llm.generate, ingest.parse, ingest.done
    """
    logger.info(message, flow_stage=stage, **fields)
