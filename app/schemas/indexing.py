"""Schemas for Qdrant indexing APIs."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class IndexedChunkResult(BaseModel):
    chunk_id: UUID
    chunk_index: int
    qdrant_point_id: UUID
    reindexed: bool = False


class IndexDocumentResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    collection: str
    dimension: int
    total_chunks: int
    indexed_chunks: int
    deleted_previous: bool = False
    items: list[IndexedChunkResult] = Field(default_factory=list)


class IndexStatusResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    collection: str
    total_chunks: int
    indexed_chunks: int
    qdrant_points: int
    ready: bool = False
    embedding_model: str | None = None


class IndexDeleteResponse(BaseModel):
    document_id: UUID
    deleted_qdrant_points: bool
    cleared_chunk_point_ids: int
    message: str = "Document vectors removed from Qdrant"


class IndexSearchHit(BaseModel):
    chunk_id: str | None = None
    document_id: str | None = None
    score: float
    page_number: int | None = None
    section_name: str | None = None
    source_filename: str | None = None
    content_preview: str | None = None


class IndexSearchResponse(BaseModel):
    query: str
    collection: str
    hits: list[IndexSearchHit] = Field(default_factory=list)
