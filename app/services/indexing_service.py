"""Index embedded chunks into Qdrant."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

from qdrant_client.http import models as qmodels
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.database import qdrant as qdrant_store
from app.database.models import Chunk, Document, DocumentVersion
from app.ingestion.embeddings import get_embedding_provider
from app.schemas.indexing import (
    IndexDeleteResponse,
    IndexDocumentResponse,
    IndexedChunkResult,
    IndexSearchHit,
    IndexSearchResponse,
    IndexStatusResponse,
)
from app.services.embedding_service import EmbeddingService

logger = get_logger(__name__)


class IndexingService:
    """Upsert chunk embeddings into Qdrant and track point IDs on chunks."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.embedding_service = EmbeddingService(
            session=session,
            settings=self.settings,
        )

    async def index_document(
        self,
        document_id: UUID,
        *,
        version_number: int | None = None,
        replace_existing: bool = True,
        ensure_embeddings: bool = True,
    ) -> IndexDocumentResponse:
        document, version = await self._get_document_and_version(
            document_id,
            version_number=version_number,
        )
        chunks = await self._load_chunks(version.id)
        if not chunks:
            raise ValidationError(
                "No chunks found. Run /chunk (and /embed) before indexing.",
                details={"document_id": str(document_id)},
            )

        if ensure_embeddings:
            pending = [
                chunk
                for chunk in chunks
                if not (chunk.meta or {}).get("embedding_ready")
            ]
            if pending:
                await self.embedding_service.embed_document(
                    document_id,
                    version_number=version.version_number,
                    force=False,
                )
                await self.session.refresh(version)
                chunks = await self._load_chunks(version.id)

        missing_ready = [
            chunk
            for chunk in chunks
            if not (chunk.meta or {}).get("embedding_ready")
        ]
        if missing_ready:
            raise ValidationError(
                "Some chunks are missing embeddings. Run /embed first.",
                details={"missing_chunks": len(missing_ready)},
            )

        deleted_previous = False
        if replace_existing:
            qdrant_store.delete_by_document_version_id(
                version.id,
                settings=self.settings,
            )
            deleted_previous = True
            for chunk in chunks:
                chunk.qdrant_point_id = None

        vectors = await self.embedding_service.get_vectors_for_chunks(chunks)
        batch_size = max(1, self.settings.qdrant_upsert_batch_size)
        results: list[IndexedChunkResult] = []
        points_batch: list[qmodels.PointStruct] = []

        for chunk in chunks:
            vector = vectors.get(chunk.id)
            if vector is None:
                raise ValidationError(
                    f"Missing embedding vector for chunk {chunk.id}"
                )
            point_id = chunk.qdrant_point_id or uuid4()
            reindexed = chunk.qdrant_point_id is not None
            payload = {
                "document_id": str(document.id),
                "document_version_id": str(version.id),
                "chunk_id": str(chunk.id),
                "chunk_index": chunk.chunk_index,
                "page_number": chunk.page_number,
                "section_name": chunk.section_name,
                "source_filename": chunk.source_filename,
                "document_version": chunk.document_version,
                "chunk_strategy": chunk.chunk_strategy,
                "content": chunk.content,
                "content_preview": chunk.content[:500],
                "token_count": chunk.token_count,
                "embedding_model": chunk.embedding_model,
                "embedding_version": chunk.embedding_version,
            }
            points_batch.append(
                qmodels.PointStruct(
                    id=str(point_id),
                    vector=vector,
                    payload=payload,
                )
            )
            chunk.qdrant_point_id = point_id
            meta = deepcopy(chunk.meta or {})
            meta["qdrant_indexed"] = True
            meta["qdrant_collection"] = self.settings.qdrant_collection
            chunk.meta = meta
            results.append(
                IndexedChunkResult(
                    chunk_id=chunk.id,
                    chunk_index=chunk.chunk_index,
                    qdrant_point_id=point_id,
                    reindexed=reindexed,
                )
            )

            if len(points_batch) >= batch_size:
                qdrant_store.upsert_points(
                    points_batch,
                    settings=self.settings,
                )
                points_batch = []

        if points_batch:
            qdrant_store.upsert_points(points_batch, settings=self.settings)

        await self._persist_index_summary(
            document,
            version,
            indexed=len(results),
            total=len(chunks),
        )
        # Mark document indexed when all chunks are in Qdrant.
        from app.core.constants import DocumentStatus

        document.status = DocumentStatus.INDEXED.value
        await self.session.commit()

        logger.info(
            "document_indexed",
            document_id=str(document.id),
            document_version_id=str(version.id),
            indexed=len(results),
            collection=self.settings.qdrant_collection,
        )
        return IndexDocumentResponse(
            document_id=document.id,
            document_version_id=version.id,
            collection=self.settings.qdrant_collection,
            dimension=self.settings.embedding_dimension,
            total_chunks=len(chunks),
            indexed_chunks=len(results),
            deleted_previous=deleted_previous,
            items=results,
        )

    async def get_status(
        self,
        document_id: UUID,
        *,
        version_number: int | None = None,
    ) -> IndexStatusResponse:
        document, version = await self._get_document_and_version(
            document_id,
            version_number=version_number,
        )
        chunks = await self._load_chunks(version.id)
        indexed = sum(1 for chunk in chunks if chunk.qdrant_point_id is not None)
        qdrant_points = qdrant_store.count_points_for_document(
            document.id,
            settings=self.settings,
        )
        model = chunks[0].embedding_model if chunks else None
        return IndexStatusResponse(
            document_id=document.id,
            document_version_id=version.id,
            collection=self.settings.qdrant_collection,
            total_chunks=len(chunks),
            indexed_chunks=indexed,
            qdrant_points=qdrant_points,
            ready=bool(chunks) and indexed == len(chunks) and qdrant_points >= indexed,
            embedding_model=model,
        )

    async def delete_index(
        self,
        document_id: UUID,
        *,
        version_number: int | None = None,
    ) -> IndexDeleteResponse:
        document, version = await self._get_document_and_version(
            document_id,
            version_number=version_number,
        )
        chunks = await self._load_chunks(version.id)
        qdrant_store.delete_by_document_version_id(
            version.id,
            settings=self.settings,
        )
        cleared = 0
        for chunk in chunks:
            if chunk.qdrant_point_id is not None:
                cleared += 1
            chunk.qdrant_point_id = None
            meta = deepcopy(chunk.meta or {})
            meta["qdrant_indexed"] = False
            chunk.meta = meta

        meta = deepcopy(version.meta or {})
        meta["indexing"] = {
            "status": "deleted",
            "collection": self.settings.qdrant_collection,
        }
        version.meta = meta
        from app.core.constants import DocumentStatus

        if document.status == DocumentStatus.INDEXED.value:
            document.status = DocumentStatus.UPLOADED.value
        await self.session.commit()
        return IndexDeleteResponse(
            document_id=document.id,
            deleted_qdrant_points=True,
            cleared_chunk_point_ids=cleared,
        )

    async def search(
        self,
        query: str,
        *,
        document_id: UUID | None = None,
        limit: int | None = None,
    ) -> IndexSearchResponse:
        """Smoke-test / helper semantic search against indexed points."""
        if not query.strip():
            raise ValidationError("query must not be empty")
        provider = get_embedding_provider(self.settings)
        vector = provider.embed_query(query)
        doc_ids = [str(document_id)] if document_id else None
        hits = qdrant_store.similarity_search(
            vector,
            limit=limit,
            document_ids=doc_ids,
            settings=self.settings,
        )
        return IndexSearchResponse(
            query=query,
            collection=self.settings.qdrant_collection,
            hits=[
                IndexSearchHit(
                    chunk_id=(hit.payload or {}).get("chunk_id"),
                    document_id=(hit.payload or {}).get("document_id"),
                    score=float(hit.score),
                    page_number=(hit.payload or {}).get("page_number"),
                    section_name=(hit.payload or {}).get("section_name"),
                    source_filename=(hit.payload or {}).get("source_filename"),
                    content_preview=(hit.payload or {}).get("content_preview"),
                )
                for hit in hits
            ],
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
            raise ValidationError("Document has no versions")
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
                    f"Version {version_number} not found for document '{document_id}'"
                )
        return document, version

    async def _load_chunks(self, document_version_id: UUID) -> list[Chunk]:
        stmt = (
            select(Chunk)
            .where(Chunk.document_version_id == document_version_id)
            .order_by(Chunk.chunk_index.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def _persist_index_summary(
        self,
        document: Document,
        version: DocumentVersion,
        *,
        indexed: int,
        total: int,
    ) -> None:
        meta = deepcopy(version.meta or {})
        meta["indexing"] = {
            "status": "indexed",
            "collection": self.settings.qdrant_collection,
            "indexed_chunks": indexed,
            "total_chunks": total,
            "dimension": self.settings.embedding_dimension,
        }
        version.meta = meta
        doc_meta = deepcopy(document.meta or {})
        doc_meta["indexed_version"] = version.version_number
        document.meta = doc_meta
