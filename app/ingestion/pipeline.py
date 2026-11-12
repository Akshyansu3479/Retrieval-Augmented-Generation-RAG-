"""End-to-end document ingestion orchestration (parse → chunk → embed → index)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.flow_log import flow
from app.core.logging import get_logger
from app.services.chunk_service import ChunkService
from app.services.embedding_service import EmbeddingService
from app.services.indexing_service import IndexingService
from app.services.parse_service import ParseService

logger = get_logger(__name__)


@dataclass
class IngestionPipelineResult:
    document_id: UUID
    document_version_id: UUID
    stages: dict[str, Any]


class IngestionPipeline:
    """Run the full synchronous (within a job) ingestion stages."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.parse_service = ParseService(session=session, settings=self.settings)
        self.chunk_service = ChunkService(session=session, settings=self.settings)
        self.embedding_service = EmbeddingService(
            session=session,
            settings=self.settings,
        )
        self.indexing_service = IndexingService(
            session=session,
            settings=self.settings,
        )

    async def run(
        self,
        document_id: UUID,
        *,
        version_number: int | None = None,
        progress_callback: Any | None = None,
    ) -> IngestionPipelineResult:
        async def _progress(pct: float, stage: str) -> None:
            if progress_callback is not None:
                await progress_callback(pct, stage)

        flow("ingest.start", "Ingestion pipeline started", document_id=str(document_id))

        await _progress(5.0, "parse")
        flow("ingest.parse", "Parsing document", document_id=str(document_id))
        parsed = await self.parse_service.parse_document(
            document_id,
            version_number=version_number,
            persist=True,
        )
        version_id = parsed.document_version_id
        version_number = None  # use latest after parse
        flow(
            "ingest.parse.done",
            "Parse complete",
            parser=parsed.parser_name,
            pages=parsed.page_count,
            sections=len(parsed.sections),
        )

        await _progress(30.0, "chunk")
        flow("ingest.chunk", "Chunking document", document_id=str(document_id))
        chunked = await self.chunk_service.chunk_document(
            document_id,
            version_number=version_number,
            replace_existing=True,
        )
        flow(
            "ingest.chunk.done",
            "Chunking complete",
            total_chunks=chunked.total,
            strategy=chunked.strategy,
        )

        await _progress(55.0, "embed")
        flow("ingest.embed", "Embedding chunks", document_id=str(document_id))
        embedded = await self.embedding_service.embed_document(
            document_id,
            version_number=version_number,
            force=False,
        )
        flow(
            "ingest.embed.done",
            "Embedding complete",
            embedded=embedded.embedded_chunks,
            total=embedded.total_chunks,
            model=embedded.model,
        )

        await _progress(80.0, "index")
        flow("ingest.index", "Indexing into Qdrant", document_id=str(document_id))
        indexed = await self.indexing_service.index_document(
            document_id,
            version_number=version_number,
            replace_existing=True,
            ensure_embeddings=False,
        )
        flow(
            "ingest.index.done",
            "Qdrant index complete",
            indexed=indexed.indexed_chunks,
            collection=indexed.collection,
        )

        await _progress(100.0, "done")
        result = IngestionPipelineResult(
            document_id=document_id,
            document_version_id=version_id,
            stages={
                "parse": {
                    "parser_name": parsed.parser_name,
                    "page_count": parsed.page_count,
                    "section_count": len(parsed.sections),
                },
                "chunk": {
                    "total_chunks": chunked.total,
                    "strategy": chunked.strategy,
                },
                "embed": {
                    "embedded_chunks": embedded.embedded_chunks,
                    "total_chunks": embedded.total_chunks,
                    "embedding_model": embedded.model,
                },
                "index": {
                    "indexed_chunks": indexed.indexed_chunks,
                    "collection": indexed.collection,
                },
            },
        )
        flow(
            "ingest.done",
            "Ingestion pipeline finished",
            document_id=str(document_id),
            stages=list(result.stages.keys()),
        )
        logger.info(
            "ingestion_pipeline_complete",
            document_id=str(document_id),
            stages=list(result.stages.keys()),
        )
        return result
