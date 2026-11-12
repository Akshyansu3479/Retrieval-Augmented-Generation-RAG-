"""High-level retriever composing query processing, hybrid search, and rerank."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.flow_log import flow
from app.retrieval.hybrid_search import HybridSearch
from app.retrieval.query_processor import ProcessedQuery, QueryProcessor
from app.retrieval.reranker import Reranker
from app.retrieval.types import RetrievalHit


@dataclass
class RetrievalResult:
    query: ProcessedQuery
    hits: list[RetrievalHit]
    mode: str


class Retriever:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.query_processor = QueryProcessor(self.settings)
        self.hybrid = HybridSearch(session=session, settings=self.settings)
        self.reranker = Reranker(self.settings)

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        rerank_top_k: int | None = None,
        document_ids: list[UUID] | None = None,
        mode: str | None = None,
        rerank: bool | None = None,
    ) -> RetrievalResult:
        processed = self.query_processor.process(query)
        mode_value = (mode or self.settings.retrieval_mode).lower()
        candidate_k = top_k or self.settings.retrieval_top_k
        flow(
            "retrieve.query",
            "Query processed",
            original=processed.original[:200],
            rewritten=processed.rewritten[:200],
            keywords=processed.keywords[:12],
            mode=mode_value,
            top_k=candidate_k,
            document_ids=[str(d) for d in (document_ids or [])],
        )
        hits = await self.hybrid.search(
            processed.rewritten,
            top_k=candidate_k,
            document_ids=document_ids,
            mode=mode_value,
        )
        flow(
            "retrieve.search",
            "Candidate hits ready",
            mode=mode_value,
            hit_count=len(hits),
            top_scores=[round(h.score, 4) for h in hits[:5]],
        )
        do_rerank = self.settings.rerank_enabled if rerank is None else rerank
        if do_rerank and mode_value != "bm25":
            before = len(hits)
            hits = self.reranker.rerank(
                processed.rewritten,
                hits,
                top_k=rerank_top_k or self.settings.rerank_top_k,
            )
            flow(
                "retrieve.rerank",
                "Rerank complete",
                before=before,
                after=len(hits),
                top_scores=[round(h.score, 4) for h in hits[:5]],
            )
        else:
            hits = hits[: (rerank_top_k or self.settings.rerank_top_k)]
            flow(
                "retrieve.trim",
                "Skipped rerank; trimmed candidates",
                hit_count=len(hits),
            )
        return RetrievalResult(query=processed, hits=hits, mode=mode_value)
