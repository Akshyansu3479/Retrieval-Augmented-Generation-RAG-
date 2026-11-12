"""Parse uploaded document versions and persist extraction metadata."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.database.models import Document, DocumentVersion
from app.ingestion.cleaner import CleaningStats, TextCleaner
from app.ingestion.loader import DocumentLoader
from app.ingestion.metadata import MetadataExtractor
from app.ingestion.parser import DocumentParser
from app.ingestion.types import ParsedDocument
from app.schemas.parse import (
    CleaningStatsResponse,
    DocumentMetadataResponse,
    ParseDocumentResponse,
    ParsedSectionResponse,
    ParsedTableResponse,
)

logger = get_logger(__name__)


class ParseService:
    """Load, parse, clean, and enrich a document version."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.loader = DocumentLoader(self.settings)
        self.parser = DocumentParser(self.settings)
        self.cleaner = TextCleaner(self.settings)
        self.metadata_extractor = MetadataExtractor(self.settings)

    async def parse_document(
        self,
        document_id: UUID,
        *,
        version_number: int | None = None,
        include_full_text: bool = True,
        persist: bool = True,
        clean: bool | None = None,
        enrich_metadata: bool | None = None,
    ) -> ParseDocumentResponse:
        document, version = await self._get_document_and_version(
            document_id,
            version_number=version_number,
        )
        loaded = self.loader.load_version(version)
        parsed = self.parser.parse(loaded)
        parsed.document_id = document.id
        parsed.document_version_id = version.id
        parsed.finalize()

        apply_clean = (
            self.settings.cleaner_enabled if clean is None else clean
        )
        apply_enrich = (
            self.settings.metadata_enrichment_enabled
            if enrich_metadata is None
            else enrich_metadata
        )

        cleaning_stats: CleaningStats | None = None
        if apply_clean:
            parsed, cleaning_stats = self.cleaner.clean_document(parsed)
        if apply_enrich:
            parsed = self.metadata_extractor.enrich(parsed)
            # Keep top-level document meta in sync with enrichment.
            document.meta = {
                **(document.meta or {}),
                "title": parsed.metadata.title,
                "language": parsed.metadata.language,
                "keywords": (parsed.metadata.extra or {}).get("keywords", []),
                "headings": (parsed.metadata.extra or {}).get("headings", []),
            }

        if persist:
            await self._persist_extraction(
                document,
                version,
                parsed,
                cleaning_stats=cleaning_stats,
                cleaned=apply_clean,
                enriched=apply_enrich,
            )

        logger.info(
            "document_parsed",
            document_id=str(document.id),
            document_version_id=str(version.id),
            parser_name=parsed.parser_name,
            char_count=parsed.char_count,
            table_count=len(parsed.tables),
            ocr_used=parsed.ocr_used,
            cleaned=apply_clean,
            metadata_enriched=apply_enrich,
        )
        return self._to_response(
            parsed,
            include_full_text=include_full_text,
            cleaned=apply_clean,
            metadata_enriched=apply_enrich,
            cleaning_stats=cleaning_stats,
        )

    async def _get_document_and_version(
        self,
        document_id: UUID,
        *,
        version_number: int | None,
    ) -> tuple[Document, DocumentVersion]:
        stmt = (
            select(Document)
            .where(Document.id == document_id)
            .options(selectinload(Document.versions))
        )
        document = (await self.session.execute(stmt)).scalar_one_or_none()
        if document is None or document.deleted_at is not None:
            raise NotFoundError(
                f"Document '{document_id}' not found",
                details={"document_id": str(document_id)},
            )
        if not document.versions:
            raise ValidationError(
                "Document has no versions to parse",
                details={"document_id": str(document_id)},
            )

        if version_number is None:
            version = max(document.versions, key=lambda item: item.version_number)
        else:
            version = next(
                (
                    item
                    for item in document.versions
                    if item.version_number == version_number
                ),
                None,
            )
            if version is None:
                raise NotFoundError(
                    f"Version {version_number} not found for document '{document_id}'",
                    details={
                        "document_id": str(document_id),
                        "version_number": version_number,
                    },
                )
        return document, version

    async def _persist_extraction(
        self,
        document: Document,
        version: DocumentVersion,
        parsed: ParsedDocument,
        *,
        cleaning_stats: CleaningStats | None,
        cleaned: bool,
        enriched: bool,
    ) -> None:
        meta = deepcopy(version.meta or {})
        extraction: dict[str, Any] = {
            "status": "parsed",
            "parser_name": parsed.parser_name,
            "parsed_at": parsed.parsed_at.isoformat(),
            "cleaned": cleaned,
            "metadata_enriched": enriched,
            "char_count": parsed.char_count,
            "word_count": parsed.word_count,
            "table_count": len(parsed.tables),
            "section_count": len(parsed.sections),
            "ocr_used": parsed.ocr_used,
            "warnings": parsed.warnings,
            "metadata": parsed.metadata.model_dump(),
            "text_preview": parsed.text[:2000],
            "cleaning_stats": (
                cleaning_stats.to_dict() if cleaning_stats is not None else None
            ),
            "tables": [
                {
                    "page_number": table.page_number,
                    "section_name": table.section_name,
                    "headers": table.headers,
                    "row_count": table.row_count,
                    "markdown": table.markdown[:5000],
                }
                for table in parsed.tables
            ],
            "sections": [
                {
                    "page_number": section.page_number,
                    "section_name": section.section_name,
                    "char_count": len(section.text),
                    "text_preview": section.text[:1000],
                }
                for section in parsed.sections
            ],
        }
        if self.settings.parser_store_full_text:
            extraction["text"] = parsed.text

        meta["extraction"] = extraction
        version.meta = meta
        version.parser_name = parsed.parser_name
        version.page_count = parsed.metadata.page_count
        version.updated_at = datetime.now(UTC)
        await self.session.commit()

    def _to_response(
        self,
        parsed: ParsedDocument,
        *,
        include_full_text: bool,
        cleaned: bool,
        metadata_enriched: bool,
        cleaning_stats: CleaningStats | None,
    ) -> ParseDocumentResponse:
        assert parsed.document_id is not None
        assert parsed.document_version_id is not None
        return ParseDocumentResponse(
            document_id=parsed.document_id,
            document_version_id=parsed.document_version_id,
            filename=parsed.filename,
            extension=parsed.extension,
            parser_name=parsed.parser_name,
            ocr_used=parsed.ocr_used,
            cleaned=cleaned,
            metadata_enriched=metadata_enriched,
            char_count=parsed.char_count,
            word_count=parsed.word_count,
            page_count=parsed.metadata.page_count,
            table_count=len(parsed.tables),
            section_count=len(parsed.sections),
            text_preview=parsed.text[:2000],
            text=parsed.text if include_full_text else None,
            sections=[
                ParsedSectionResponse(
                    page_number=section.page_number,
                    section_name=section.section_name,
                    text=section.text,
                    char_count=len(section.text),
                )
                for section in parsed.sections
            ],
            tables=[
                ParsedTableResponse(
                    page_number=table.page_number,
                    section_name=table.section_name,
                    headers=table.headers,
                    row_count=table.row_count,
                    markdown=table.markdown,
                )
                for table in parsed.tables
            ],
            metadata=DocumentMetadataResponse(**parsed.metadata.model_dump()),
            cleaning_stats=(
                CleaningStatsResponse(**cleaning_stats.to_dict())
                if cleaning_stats is not None
                else None
            ),
            warnings=parsed.warnings,
            parsed_at=parsed.parsed_at,
        )
