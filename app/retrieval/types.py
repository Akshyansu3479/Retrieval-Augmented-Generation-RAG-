"""Shared retrieval result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class RetrievalHit:
    chunk_id: str | None
    document_id: str | None
    content: str
    score: float
    page_number: int | None = None
    section_name: str | None = None
    source_filename: str | None = None
    document_version_id: str | None = None
    chunk_index: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def chunk_uuid(self) -> UUID | None:
        if not self.chunk_id:
            return None
        try:
            return UUID(self.chunk_id)
        except ValueError:
            return None
