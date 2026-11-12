"""Schemas for chunking APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ChunkResponse(BaseModel):
    id: UUID
    document_id: UUID
    document_version_id: UUID
    chunk_index: int
    content: str
    content_hash: str
    token_count: int | None = None
    page_number: int | None = None
    section_name: str | None = None
    source_filename: str
    document_version: int
    parent_chunk_id: UUID | None = None
    chunk_strategy: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChunkListResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    strategy: str
    chunk_size: int
    chunk_overlap: int
    total: int
    items: list[ChunkResponse]


class ChunkDocumentResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    strategy: str
    chunk_size: int
    chunk_overlap: int
    replaced_existing: bool
    total: int
    items: list[ChunkResponse]
