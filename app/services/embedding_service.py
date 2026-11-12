"""Generate and cache embeddings for persisted chunks."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID

import orjson
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.database.models import Chunk, Document, DocumentVersion
from app.database.redis import get_redis
from app.ingestion.embeddings import (
    EmbeddingProvider,
    embedding_cache_key,
    get_embedding_provider,
)
from app.schemas.embedding import (
    EmbedChunkResult,
    EmbedDocumentResponse,
    EmbeddingStatusResponse,
)

logger = get_logger(__name__)


class EmbeddingService:
    """Embed document chunks and store vectors in Redis for later indexing."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self._provider = provider

    @property
    def provider(self) -> EmbeddingProvider:
        if self._provider is None:
            self._provider = get_embedding_provider(self.settings)
        return self._provider

    async def embed_document(
        self,
        document_id: UUID,
        *,
        version_number: int | None = None,
        force: bool = False,
    ) -> EmbedDocumentResponse:
        document, version = await self._get_document_and_version(
            document_id,
            version_number=version_number,
        )
        chunks = await self._load_chunks(version.id)
        if not chunks:
            raise ValidationError(
                "No chunks found for document version. Run /chunk first.",
                details={"document_id": str(document_id)},
            )

        provider = self.provider
        redis = get_redis()
        batch_size = self.settings.embedding_batch_size
        results: list[EmbedChunkResult] = []
        embedded = 0
        skipped = 0

        pending: list[Chunk] = []
        for chunk in chunks:
            cache_key = embedding_cache_key(
                str(chunk.id),
                provider.model_name,
                provider.version,
            )
            already = (
                chunk.embedding_model == provider.model_name
                and chunk.embedding_version == provider.version
                and bool((chunk.meta or {}).get("embedding_ready"))
            )
            if already and not force and await redis.exists(cache_key):
                skipped += 1
                results.append(
                    EmbedChunkResult(
                        chunk_id=chunk.id,
                        chunk_index=chunk.chunk_index,
                        token_count=chunk.token_count,
                        dimension=provider.dimension,
                        cached=True,
                    )
                )
            else:
                pending.append(chunk)

        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            texts = [chunk.content for chunk in batch]
            vectors = self._embed_batch(texts)
            if len(vectors) != len(batch):
                raise ValidationError(
                    "Embedding provider returned unexpected vector count",
                    details={
                        "expected": len(batch),
                        "actual": len(vectors),
                    },
                )

            for chunk, vector in zip(batch, vectors, strict=True):
                if len(vector) != provider.dimension:
                    raise ValidationError(
                        "Embedding dimension mismatch",
                        details={
                            "expected": provider.dimension,
                            "actual": len(vector),
                        },
                    )
                cache_key = embedding_cache_key(
                    str(chunk.id),
                    provider.model_name,
                    provider.version,
                )
                await redis.set(
                    cache_key,
                    orjson.dumps(vector).decode("utf-8"),
                    ex=self.settings.embedding_cache_ttl_seconds,
                )
                meta = deepcopy(chunk.meta or {})
                meta.update(
                    {
                        "embedding_ready": True,
                        "embedding_dim": provider.dimension,
                        "embedding_provider": provider.provider_name,
                        "embedding_cache_key": cache_key,
                    }
                )
                chunk.meta = meta
                chunk.embedding_model = provider.model_name
                chunk.embedding_version = provider.version
                embedded += 1
                results.append(
                    EmbedChunkResult(
                        chunk_id=chunk.id,
                        chunk_index=chunk.chunk_index,
                        token_count=chunk.token_count,
                        dimension=provider.dimension,
                        cached=False,
                    )
                )

        await self._persist_embedding_summary(
            version,
            provider=provider,
            total=len(chunks),
            embedded=embedded,
            skipped=skipped,
        )
        await self.session.commit()

        results.sort(key=lambda item: item.chunk_index)
        logger.info(
            "document_embedded",
            document_id=str(document.id),
            document_version_id=str(version.id),
            provider=provider.provider_name,
            model=provider.model_name,
            embedded=embedded,
            skipped=skipped,
            dimension=provider.dimension,
        )
        return EmbedDocumentResponse(
            document_id=document.id,
            document_version_id=version.id,
            provider=provider.provider_name,
            model=provider.model_name,
            embedding_version=provider.version,
            dimension=provider.dimension,
            batch_size=batch_size,
            total_chunks=len(chunks),
            embedded_chunks=embedded,
            skipped_chunks=skipped,
            items=results,
        )

    async def get_status(
        self,
        document_id: UUID,
        *,
        version_number: int | None = None,
    ) -> EmbeddingStatusResponse:
        document, version = await self._get_document_and_version(
            document_id,
            version_number=version_number,
        )
        chunks = await self._load_chunks(version.id)
        embedded = sum(
            1
            for chunk in chunks
            if (chunk.meta or {}).get("embedding_ready") and chunk.embedding_model
        )
        summary = ((version.meta or {}).get("embeddings") or {})
        return EmbeddingStatusResponse(
            document_id=document.id,
            document_version_id=version.id,
            total_chunks=len(chunks),
            embedded_chunks=embedded,
            pending_chunks=max(0, len(chunks) - embedded),
            provider=summary.get("provider"),
            model=summary.get("model") or (chunks[0].embedding_model if chunks else None),
            embedding_version=summary.get("embedding_version")
            or (chunks[0].embedding_version if chunks else None),
            dimension=summary.get("dimension"),
            ready=bool(chunks) and embedded == len(chunks),
        )

    async def get_vectors_for_chunks(
        self,
        chunks: list[Chunk],
    ) -> dict[UUID, list[float]]:
        """Load cached vectors for chunks (used by Phase 8 indexing)."""
        provider = self.provider
        redis = get_redis()
        mapping: dict[UUID, list[float]] = {}
        missing: list[Chunk] = []
        for chunk in chunks:
            cache_key = embedding_cache_key(
                str(chunk.id),
                chunk.embedding_model or provider.model_name,
                chunk.embedding_version or provider.version,
            )
            raw = await redis.get(cache_key)
            if raw:
                mapping[chunk.id] = list(orjson.loads(raw))
            else:
                missing.append(chunk)
        if missing:
            vectors = self._embed_batch([chunk.content for chunk in missing])
            for chunk, vector in zip(missing, vectors, strict=True):
                cache_key = embedding_cache_key(
                    str(chunk.id),
                    provider.model_name,
                    provider.version,
                )
                await redis.set(
                    cache_key,
                    orjson.dumps(vector).decode("utf-8"),
                    ex=self.settings.embedding_cache_ttl_seconds,
                )
                mapping[chunk.id] = vector
        return mapping

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        attempts = max(1, self.settings.embedding_max_retries)

        @retry(
            reraise=True,
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=1, min=1, max=10),
        )
        def _call() -> list[list[float]]:
            return self.provider.embed_documents(texts)

        return _call()

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

    async def _persist_embedding_summary(
        self,
        version: DocumentVersion,
        *,
        provider: EmbeddingProvider,
        total: int,
        embedded: int,
        skipped: int,
    ) -> None:
        meta = deepcopy(version.meta or {})
        meta["embeddings"] = {
            "status": "embedded",
            "provider": provider.provider_name,
            "model": provider.model_name,
            "embedding_version": provider.version,
            "dimension": provider.dimension,
            "total_chunks": total,
            "embedded_chunks": embedded,
            "skipped_chunks": skipped,
        }
        version.meta = meta
