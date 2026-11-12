"""Schemas for document parse responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ParsedTableResponse(BaseModel):
    page_number: int | None = None
    section_name: str | None = None
    headers: list[str] = Field(default_factory=list)
    row_count: int = 0
    markdown: str = ""


class ParsedSectionResponse(BaseModel):
    page_number: int | None = None
    section_name: str | None = None
    text: str = ""
    char_count: int = 0


class DocumentMetadataResponse(BaseModel):
    title: str | None = None
    author: str | None = None
    created: str | None = None
    modified: str | None = None
    page_count: int | None = None
    language: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class CleaningStatsResponse(BaseModel):
    original_char_count: int = 0
    cleaned_char_count: int = 0
    characters_removed: int = 0
    hyphen_breaks_fixed: int = 0
    control_chars_removed: int = 0
    blank_lines_collapsed: int = 0
    sections_cleaned: int = 0
    tables_cleaned: int = 0
    operations: list[str] = Field(default_factory=list)


class ParseDocumentResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    filename: str
    extension: str
    parser_name: str
    ocr_used: bool = False
    cleaned: bool = False
    metadata_enriched: bool = False
    char_count: int = 0
    word_count: int = 0
    page_count: int | None = None
    table_count: int = 0
    section_count: int = 0
    text_preview: str = ""
    text: str | None = None
    sections: list[ParsedSectionResponse] = Field(default_factory=list)
    tables: list[ParsedTableResponse] = Field(default_factory=list)
    metadata: DocumentMetadataResponse
    cleaning_stats: CleaningStatsResponse | None = None
    warnings: list[str] = Field(default_factory=list)
    parsed_at: datetime
