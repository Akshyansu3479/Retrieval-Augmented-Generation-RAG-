"""Cross-encoder reranking (BGE via FastEmbed when enabled)."""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.retrieval.types import RetrievalHit

logger = get_logger(__name__)


@lru_cache(maxsize=2)
def _load_cross_encoder(model_name: str):  # type: ignore[no-untyped-def]
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    logger.info("reranker_loading", model=model_name)
    return TextCrossEncoder(model_name=model_name)


class Reranker:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        *,
        top_k: int | None = None,
    ) -> list[RetrievalHit]:
        if not hits:
            return []
        limit = top_k or self.settings.rerank_top_k
        if not self.settings.rerank_enabled:
            return hits[:limit]

        try:
            encoder = _load_cross_encoder(self.settings.rerank_model)
            documents = [hit.content for hit in hits]
            # FastEmbed returns scores aligned with documents.
            scores = list(encoder.rerank(query, documents))
            scored: list[tuple[float, RetrievalHit]] = []
            for hit, score in zip(hits, scores, strict=False):
                scored.append((float(score), hit))
            scored.sort(key=lambda item: item[0], reverse=True)
            reranked: list[RetrievalHit] = []
            for score, hit in scored[:limit]:
                reranked.append(
                    RetrievalHit(
                        chunk_id=hit.chunk_id,
                        document_id=hit.document_id,
                        document_version_id=hit.document_version_id,
                        content=hit.content,
                        score=score,
                        page_number=hit.page_number,
                        section_name=hit.section_name,
                        source_filename=hit.source_filename,
                        chunk_index=hit.chunk_index,
                        meta={**hit.meta, "rerank_score": score, "reranked": True},
                    )
                )
            return reranked
        except Exception:  # noqa: BLE001 — fall back to original ranking
            logger.exception("rerank_failed_falling_back")
            return hits[:limit]
