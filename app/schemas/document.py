"""Pydantic schemas for document APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentVersionResponse(BaseModel):
    """Serialized document version metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_number: int
    object_key: str
    bucket: str
    filename: str
    content_type: str | None = None
    size_bytes: int
    checksum_sha256: str
    page_count: int | None = None
    parser_name: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class DocumentResponse(BaseModel):
    """Serialized document with optional versions."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_type: str | None = None
    checksum_sha256: str | None = None
    status: str
    current_version: int
    source_uri: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    versions: list[DocumentVersionResponse] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    """Paginated document listing."""

    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int


class DocumentDeleteResponse(BaseModel):
    """Confirmation payload for soft-deleted documents."""

    id: UUID
    status: str
    deleted_at: datetime
    message: str = "Document deleted"
