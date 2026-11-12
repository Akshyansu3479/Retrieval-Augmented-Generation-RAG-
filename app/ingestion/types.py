"""Shared parsing result types."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ParsedTable(BaseModel):
    """Extracted table content."""

    page_number: int | None = None
    section_name: str | None = None
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    markdown: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)


class ParsedSection(BaseModel):
    """A logical text section / page fragment."""

    page_number: int | None = None
    section_name: str | None = None
    text: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class DocumentMetadata(BaseModel):
    """Normalized document-level metadata."""

    title: str | None = None
    author: str | None = None
    created: str | None = None
    modified: str | None = None
    page_count: int | None = None
    language: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    """Full parse output for one document version."""

    document_id: UUID | None = None
    document_version_id: UUID | None = None
    filename: str
    content_type: str | None = None
    extension: str
    parser_name: str
    text: str = ""
    sections: list[ParsedSection] = Field(default_factory=list)
    tables: list[ParsedTable] = Field(default_factory=list)
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    warnings: list[str] = Field(default_factory=list)
    ocr_used: bool = False
    parsed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    char_count: int = 0
    word_count: int = 0

    def finalize(self) -> ParsedDocument:
        """Recompute aggregate fields from sections/text."""
        if not self.text and self.sections:
            self.text = "\n\n".join(
                section.text.strip()
                for section in self.sections
                if section.text.strip()
            )
        self.char_count = len(self.text)
        self.word_count = len(self.text.split()) if self.text.strip() else 0
        if self.metadata.page_count is None:
            pages = {
                section.page_number
                for section in self.sections
                if section.page_number is not None
            }
            if pages:
                self.metadata.page_count = max(pages)
        return self
