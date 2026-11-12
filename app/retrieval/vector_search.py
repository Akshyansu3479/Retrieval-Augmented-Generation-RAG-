"""Semantic (dense) retrieval via Qdrant."""

from __future__ import annotations

from uuid import UUID

from app.config import Settings, get_settings
from app.database import qdrant as qdrant_store
from app.ingestion.embeddings import get_embedding_provider
from app.retrieval.types import RetrievalHit


class VectorSearch:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.provider = get_embedding_provider(self.settings)

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        document_ids: list[str | UUID] | None = None,
        score_threshold: float | None = None,
    ) -> list[RetrievalHit]:
        vector = self.provider.embed_query(query)
        docs = [str(d) for d in document_ids] if document_ids else None
        points = qdrant_store.similarity_search(
            vector,
            limit=top_k or self.settings.retrieval_top_k,
            score_threshold=score_threshold,
            document_ids=docs,
            settings=self.settings,
        )
        hits: list[RetrievalHit] = []
        for point in points:
            payload = point.payload or {}
            hits.append(
                RetrievalHit(
                    chunk_id=payload.get("chunk_id"),
                    document_id=payload.get("document_id"),
                    document_version_id=payload.get("document_version_id"),
                    content=payload.get("content")
                    or payload.get("content_preview")
                    or "",
                    score=float(point.score),
                    page_number=payload.get("page_number"),
                    section_name=payload.get("section_name"),
                    source_filename=payload.get("source_filename"),
                    chunk_index=payload.get("chunk_index"),
                    meta={"channel": "semantic"},
                )
            )
        return hits
