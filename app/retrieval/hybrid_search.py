"""Hybrid retrieval with Reciprocal Rank Fusion and deduplication."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.flow_log import flow
from app.retrieval.bm25_search import BM25Search
from app.retrieval.types import RetrievalHit
from app.retrieval.vector_search import VectorSearch


def reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievalHit]],
    *,
    k: int = 60,
) -> list[RetrievalHit]:
    """Fuse multiple ranked lists via RRF; keep best payload per chunk_id."""
    scores: dict[str, float] = defaultdict(float)
    payloads: dict[str, RetrievalHit] = {}

    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            key = hit.chunk_id or f"anon:{id(hit)}"
            scores[key] += 1.0 / (k + rank)
            existing = payloads.get(key)
            if existing is None or hit.score > existing.score:
                payloads[key] = hit

    fused: list[RetrievalHit] = []
    for key, rrf_score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        hit = payloads[key]
        fused.append(
            RetrievalHit(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                document_version_id=hit.document_version_id,
                content=hit.content,
                score=float(rrf_score),
                page_number=hit.page_number,
                section_name=hit.section_name,
                source_filename=hit.source_filename,
                chunk_index=hit.chunk_index,
                meta={**hit.meta, "rrf_score": float(rrf_score), "channel": "hybrid"},
            )
        )
    return fused


def dedupe_hits(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    seen: set[str] = set()
    unique: list[RetrievalHit] = []
    for hit in hits:
        key = hit.chunk_id or hit.content[:80]
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


class HybridSearch:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.vector = VectorSearch(settings=self.settings)
        self.bm25 = BM25Search(session=session, settings=self.settings)

    async def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        document_ids: list[UUID] | None = None,
        mode: str | None = None,
    ) -> list[RetrievalHit]:
        limit = top_k or self.settings.retrieval_top_k
        mode_value = (mode or self.settings.retrieval_mode).lower()
        doc_strs = [str(d) for d in document_ids] if document_ids else None

        if mode_value == "semantic":
            hits = dedupe_hits(
                self.vector.search(query, top_k=limit, document_ids=doc_strs)
            )[:limit]
            flow("retrieve.semantic", "Semantic search done", hits=len(hits))
            return hits
        if mode_value == "bm25":
            hits = dedupe_hits(
                await self.bm25.search(query, top_k=limit, document_ids=document_ids)
            )[:limit]
            flow("retrieve.bm25", "BM25 search done", hits=len(hits))
            return hits

        semantic_hits = self.vector.search(
            query,
            top_k=limit,
            document_ids=doc_strs,
        )
        bm25_hits = await self.bm25.search(
            query,
            top_k=limit,
            document_ids=document_ids,
        )
        flow(
            "retrieve.hybrid",
            "Hybrid channels collected",
            semantic_hits=len(semantic_hits),
            bm25_hits=len(bm25_hits),
            rrf_k=self.settings.rrf_k,
        )
        fused = reciprocal_rank_fusion(
            [semantic_hits, bm25_hits],
            k=self.settings.rrf_k,
        )
        return dedupe_hits(fused)[:limit]
