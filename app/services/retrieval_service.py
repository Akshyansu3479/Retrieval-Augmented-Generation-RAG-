"""API-facing retrieval helper."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.exceptions import ValidationError
from app.retrieval.retriever import Retriever
from app.schemas.chat import RetrieveHitResponse, RetrieveRequest, RetrieveResponse


class RetrievalService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.retriever = Retriever(session=session, settings=self.settings)

    async def retrieve(self, request: RetrieveRequest) -> RetrieveResponse:
        if not request.query.strip():
            raise ValidationError("query must not be empty")
        result = await self.retriever.retrieve(
            request.query.strip(),
            top_k=request.top_k,
            document_ids=request.document_ids,
            mode=request.mode,
            rerank=request.rerank,
        )
        return RetrieveResponse(
            query=result.query.original,
            rewritten_query=result.query.rewritten,
            mode=result.mode,
            hits=[
                RetrieveHitResponse(
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    score=hit.score,
                    page_number=hit.page_number,
                    section_name=hit.section_name,
                    source_filename=hit.source_filename,
                    content_preview=(hit.content or "")[:400],
                )
                for hit in result.hits
            ],
        )
