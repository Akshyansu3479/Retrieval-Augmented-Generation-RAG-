"""Chunk parsed documents and persist chunk rows."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.database.models import Chunk, Document, DocumentVersion
from app.ingestion.chunk_types import ChunkDraft, ChunkingResult
from app.ingestion.chunker import DocumentChunker, content_sha256, estimate_tokens
from app.ingestion.cleaner import TextCleaner
from app.ingestion.loader import DocumentLoader
from app.ingestion.metadata import MetadataExtractor
from app.ingestion.parser import DocumentParser
from app.ingestion.types import DocumentMetadata, ParsedDocument, ParsedSection, ParsedTable
from app.schemas.chunk import ChunkDocumentResponse, ChunkListResponse, ChunkResponse

logger = get_logger(__name__)


class ChunkService:
    """Create and list document chunks for a stored document version."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.chunker = DocumentChunker(self.settings)
        self.loader = DocumentLoader(self.settings)
        self.parser = DocumentParser(self.settings)
        self.cleaner = TextCleaner(self.settings)
        self.metadata_extractor = MetadataExtractor(self.settings)

    async def chunk_document(
        self,
        document_id: UUID,
        *,
        version_number: int | None = None,
        strategy: str | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        replace_existing: bool = True,
        reparse: bool = False,
    ) -> ChunkDocumentResponse:
        document, version = await self._get_document_and_version(
            document_id,
            version_number=version_number,
        )
        parsed = await self._load_parsed(
            document,
            version,
            reparse=reparse,
        )
        result = self.chunker.chunk(
            parsed,
            strategy=strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        existing_count = await self._count_chunks(version.id)
        if existing_count and not replace_existing:
            raise ValidationError(
                "Chunks already exist for this document version",
                details={
                    "document_version_id": str(version.id),
                    "existing_chunks": existing_count,
                },
            )

        if replace_existing and existing_count:
            await self.session.execute(
                delete(Chunk).where(Chunk.document_version_id == version.id)
            )

        saved = await self._persist_chunks(document, version, result)
        await self._persist_chunk_summary(version, result, saved)
        await self.session.commit()

        items = [ChunkResponse.model_validate(row) for row in saved]
        return ChunkDocumentResponse(
            document_id=document.id,
            document_version_id=version.id,
            strategy=result.strategy,
            chunk_size=result.chunk_size,
            chunk_overlap=result.chunk_overlap,
            replaced_existing=bool(existing_count and replace_existing),
            total=len(items),
            items=items,
        )

    async def list_chunks(
        self,
        document_id: UUID,
        *,
        version_number: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ChunkListResponse:
        document, version = await self._get_document_and_version(
            document_id,
            version_number=version_number,
        )
        limit = max(1, min(limit, 500))
        offset = max(0, offset)

        total_stmt = select(Chunk.id).where(Chunk.document_version_id == version.id)
        total = len((await self.session.execute(total_stmt)).all())

        stmt = (
            select(Chunk)
            .where(Chunk.document_version_id == version.id)
            .order_by(Chunk.chunk_index.asc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        strategy = rows[0].chunk_strategy if rows else self.settings.chunk_strategy
        extraction = (version.meta or {}).get("chunking") or {}
        return ChunkListResponse(
            document_id=document.id,
            document_version_id=version.id,
            strategy=str(extraction.get("strategy") or strategy or "unknown"),
            chunk_size=int(extraction.get("chunk_size") or self.settings.chunk_size),
            chunk_overlap=int(
                extraction.get("chunk_overlap") or self.settings.chunk_overlap
            ),
            total=total,
            items=[ChunkResponse.model_validate(row) for row in rows],
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
            raise ValidationError("Document has no versions to chunk")

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

    async def _count_chunks(self, document_version_id: UUID) -> int:
        stmt = select(Chunk.id).where(Chunk.document_version_id == document_version_id)
        return len((await self.session.execute(stmt)).all())

    async def _load_parsed(
        self,
        document: Document,
        version: DocumentVersion,
        *,
        reparse: bool,
    ) -> ParsedDocument:
        extraction = ((version.meta or {}).get("extraction") or {})
        has_text = bool(extraction.get("text") or extraction.get("text_preview"))
        if has_text and not reparse:
            return self._parsed_from_extraction(document, version, extraction)

        loaded = self.loader.load_version(version)
        parsed = self.parser.parse(loaded)
        parsed.document_id = document.id
        parsed.document_version_id = version.id
        parsed.finalize()
        if self.settings.cleaner_enabled:
            parsed, _ = self.cleaner.clean_document(parsed)
        if self.settings.metadata_enrichment_enabled:
            parsed = self.metadata_extractor.enrich(parsed)
        return parsed

    def _parsed_from_extraction(
        self,
        document: Document,
        version: DocumentVersion,
        extraction: dict[str, Any],
    ) -> ParsedDocument:
        text = extraction.get("text") or extraction.get("text_preview") or ""
        sections_raw = extraction.get("sections") or []
        tables_raw = extraction.get("tables") or []
        sections: list[ParsedSection] = []
        for item in sections_raw:
            if not isinstance(item, dict):
                continue
            # Prefer full section text; ignore preview-only rows to avoid truncation.
            section_text = item.get("text")
            if not section_text:
                continue
            sections.append(
                ParsedSection(
                    page_number=item.get("page_number"),
                    section_name=item.get("section_name"),
                    text=section_text,
                )
            )
        if not sections and text:
            sections = [ParsedSection(text=text, page_number=1)]

        tables = [
            ParsedTable(
                page_number=item.get("page_number"),
                section_name=item.get("section_name"),
                headers=item.get("headers") or [],
                rows=[],
                markdown=item.get("markdown") or "",
            )
            for item in tables_raw
            if isinstance(item, dict)
        ]
        metadata_raw = extraction.get("metadata") or {}
        parsed = ParsedDocument(
            document_id=document.id,
            document_version_id=version.id,
            filename=version.filename or document.filename,
            content_type=version.content_type or document.content_type,
            extension=(version.meta or {}).get("extension")
            or (document.meta or {}).get("extension")
            or "",
            parser_name=str(extraction.get("parser_name") or version.parser_name or "stored"),
            text=text,
            sections=sections,
            tables=tables,
            metadata=DocumentMetadata(**metadata_raw) if metadata_raw else DocumentMetadata(),
            ocr_used=bool(extraction.get("ocr_used")),
            warnings=list(extraction.get("warnings") or []),
        )
        return parsed.finalize()

    async def _persist_chunks(
        self,
        document: Document,
        version: DocumentVersion,
        result: ChunkingResult,
    ) -> list[Chunk]:
        parent_id_by_index: dict[int, UUID] = {}
        saved: list[Chunk] = []

        # First pass: parents (and non-parent-child chunks).
        pending_children: list[tuple[ChunkDraft, Chunk]] = []
        for draft in result.chunks:
            role = (draft.meta or {}).get("role")
            chunk_id = uuid4()
            content_hash = draft.meta.get("content_hash") or content_sha256(draft.content)
            row = Chunk(
                id=chunk_id,
                document_id=document.id,
                document_version_id=version.id,
                chunk_index=draft.chunk_index,
                content=draft.content,
                content_hash=content_hash,
                token_count=draft.token_count or estimate_tokens(draft.content),
                page_number=draft.page_number,
                section_name=draft.section_name,
                source_filename=version.filename or document.filename,
                document_version=version.version_number,
                parent_chunk_id=None,
                chunk_strategy=result.strategy,
                meta={
                    **draft.meta,
                    "document_id": str(document.id),
                    "document_version_id": str(version.id),
                    "document_version": version.version_number,
                    "source_filename": version.filename or document.filename,
                },
            )
            if role == "parent":
                parent_index = int(draft.meta.get("parent_index", draft.chunk_index))
                parent_id_by_index[parent_index] = chunk_id
                self.session.add(row)
                saved.append(row)
            elif role == "child" or draft.parent_index is not None:
                pending_children.append((draft, row))
            else:
                self.session.add(row)
                saved.append(row)

        await self.session.flush()

        for draft, row in pending_children:
            parent_index = (
                draft.parent_index
                if draft.parent_index is not None
                else draft.meta.get("parent_index")
            )
            if parent_index is not None:
                row.parent_chunk_id = parent_id_by_index.get(int(parent_index))
            self.session.add(row)
            saved.append(row)

        await self.session.flush()
        saved.sort(key=lambda item: item.chunk_index)
        logger.info(
            "chunks_persisted",
            document_id=str(document.id),
            document_version_id=str(version.id),
            count=len(saved),
            strategy=result.strategy,
        )
        return saved

    async def _persist_chunk_summary(
        self,
        version: DocumentVersion,
        result: ChunkingResult,
        saved: list[Chunk],
    ) -> None:
        meta = dict(version.meta or {})
        meta["chunking"] = {
            "status": "chunked",
            "strategy": result.strategy,
            "chunk_size": result.chunk_size,
            "chunk_overlap": result.chunk_overlap,
            "chunk_count": len(saved),
            "chunk_ids": [str(row.id) for row in saved[:50]],
        }
        version.meta = meta
