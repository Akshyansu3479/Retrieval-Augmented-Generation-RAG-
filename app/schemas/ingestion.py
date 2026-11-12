"""Schemas for async ingestion jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IngestionEnqueueResponse(BaseModel):
    job_id: UUID
    document_id: UUID
    document_version_id: UUID
    status: str
    celery_task_id: str | None = None
    idempotency_key: str
    message: str = "Ingestion job queued"


class IngestionJobResponse(BaseModel):
    id: UUID
    document_id: UUID
    document_version_id: UUID
    celery_task_id: str | None = None
    status: str
    idempotency_key: str
    attempt_count: int
    progress_pct: float
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
