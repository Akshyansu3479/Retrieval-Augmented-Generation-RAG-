"""BM25 keyword retrieval over chunk text (in-memory corpus per query scope)."""

from __future__ import annotations

import re
from uuid import UUID

from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database.models import Chunk
from app.retrieval.types import RetrievalHit

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in _TOKEN_RE.findall(text or "")]


class BM25Search:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        document_ids: list[UUID] | None = None,
    ) -> list[RetrievalHit]:
        stmt = select(Chunk)
        if document_ids:
            stmt = stmt.where(Chunk.document_id.in_(document_ids))
        stmt = stmt.order_by(Chunk.created_at.desc()).limit(
            self.settings.bm25_corpus_limit
        )
        chunks = list((await self.session.execute(stmt)).scalars().all())
        if not chunks:
            return []

        corpus_tokens = [tokenize(chunk.content) for chunk in chunks]
        if not any(corpus_tokens):
            return []

        bm25 = BM25Okapi(corpus_tokens)
        scores = bm25.get_scores(tokenize(query))
        ranked = sorted(
            zip(chunks, scores, strict=True),
            key=lambda item: float(item[1]),
            reverse=True,
        )
        limit = top_k or self.settings.retrieval_top_k
        hits: list[RetrievalHit] = []
        for chunk, score in ranked[:limit]:
            if float(score) <= 0:
                continue
            hits.append(
                RetrievalHit(
                    chunk_id=str(chunk.id),
                    document_id=str(chunk.document_id),
                    document_version_id=str(chunk.document_version_id),
                    content=chunk.content,
                    score=float(score),
                    page_number=chunk.page_number,
                    section_name=chunk.section_name,
                    source_filename=chunk.source_filename,
                    chunk_index=chunk.chunk_index,
                    meta={"channel": "bm25"},
                )
            )
        return hits
