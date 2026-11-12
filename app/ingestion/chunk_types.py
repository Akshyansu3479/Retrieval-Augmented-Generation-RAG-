"""Chunk draft types produced by the chunking engine."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ChunkDraft(BaseModel):
    """In-memory chunk before PostgreSQL persistence."""

    content: str
    chunk_index: int = 0
    page_number: int | None = None
    section_name: str | None = None
    token_count: int = 0
    strategy: str
    parent_index: int | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ChunkingResult(BaseModel):
    """Result of chunking one parsed document version."""

    document_id: UUID | None = None
    document_version_id: UUID | None = None
    strategy: str
    chunk_size: int
    chunk_overlap: int
    chunks: list[ChunkDraft] = Field(default_factory=list)

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)
