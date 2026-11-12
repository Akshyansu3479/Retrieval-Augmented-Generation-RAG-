"""Schemas for embedding APIs."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class EmbedChunkResult(BaseModel):
    chunk_id: UUID
    chunk_index: int
    token_count: int | None = None
    dimension: int
    cached: bool = False


class EmbedDocumentResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    provider: str
    model: str
    embedding_version: str
    dimension: int
    batch_size: int
    total_chunks: int
    embedded_chunks: int
    skipped_chunks: int = 0
    items: list[EmbedChunkResult] = Field(default_factory=list)


class EmbeddingStatusResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    total_chunks: int
    embedded_chunks: int
    pending_chunks: int
    provider: str | None = None
    model: str | None = None
    embedding_version: str | None = None
    dimension: int | None = None
    ready: bool = False
