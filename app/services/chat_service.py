"""Chat orchestration: retrieve → generate → persist messages/citations."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.core.constants import MessageRole
from app.core.exceptions import NotFoundError, ValidationError
from app.core.flow_log import flow
from app.core.logging import get_logger
from app.database.models import Citation, Conversation, Message
from app.generation.llm_client import ChatMessage
from app.generation.response_generator import ResponseGenerator
from app.schemas.chat import (
    ChatCitation,
    ChatRequest,
    ChatResponse,
    ConversationHistoryResponse,
    MessageResponse,
)
from app.retrieval.types import RetrievalHit

logger = get_logger(__name__)


class ChatService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.generator = ResponseGenerator(session=session, settings=self.settings)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if not request.message.strip():
            raise ValidationError("message must not be empty")

        question = request.message.strip()
        flow(
            "chat.start",
            "Chat request received",
            question=question[:200],
            document_ids=[str(d) for d in (request.document_ids or [])],
            retrieval_mode=request.retrieval_mode,
            streaming=False,
        )

        conversation = await self._get_or_create_conversation(request.conversation_id)
        history = await self._history_messages(conversation.id)
        await self._add_message(
            conversation.id,
            role=MessageRole.USER.value,
            content=question,
        )
        flow(
            "chat.persist_user",
            "User message stored",
            conversation_id=str(conversation.id),
            history_turns=len(history),
        )

        started = time.perf_counter()
        generated = await self.generator.answer(
            question,
            document_ids=request.document_ids,
            mode=request.retrieval_mode,
            history=history,
        )
        latency_ms = (time.perf_counter() - started) * 1000

        assistant = await self._add_message(
            conversation.id,
            role=MessageRole.ASSISTANT.value,
            content=generated.answer,
            model_name=generated.model,
            prompt_tokens=generated.usage_prompt_tokens,
            completion_tokens=generated.usage_completion_tokens,
            total_tokens=generated.usage_total_tokens,
            latency_ms=latency_ms,
            meta={
                "retrieval_mode": generated.retrieval_mode,
                "context_tokens": generated.context.token_estimate,
                "truncated": generated.context.truncated,
            },
        )
        citations = await self._persist_citations(assistant, generated.hits)
        await self.session.commit()

        if conversation.title is None:
            conversation.title = question[:120]
            await self.session.commit()

        flow(
            "chat.done",
            "Chat completed",
            conversation_id=str(conversation.id),
            message_id=str(assistant.id),
            model=generated.model,
            retrieval_mode=generated.retrieval_mode,
            citations=len(citations),
            latency_ms=round(latency_ms, 2),
            answer_preview=generated.answer[:240],
        )

        return ChatResponse(
            conversation_id=conversation.id,
            message_id=assistant.id,
            answer=generated.answer,
            model=generated.model,
            retrieval_mode=generated.retrieval_mode,
            citations=citations,
            prompt_tokens=generated.usage_prompt_tokens,
            completion_tokens=generated.usage_completion_tokens,
            total_tokens=generated.usage_total_tokens,
            latency_ms=round(latency_ms, 2),
        )

    async def stream_chat(
        self,
        request: ChatRequest,
    ) -> tuple[Conversation, Message, list[ChatCitation], AsyncIterator[str]]:
        """
        Prepare streaming chat.

        Returns conversation, placeholder assistant message, citations from
        retrieval (pre-generation), and an async token iterator. Caller should
        finalize the assistant message content after the stream ends.
        """
        if not request.message.strip():
            raise ValidationError("message must not be empty")

        question = request.message.strip()
        flow(
            "chat.start",
            "Chat stream request received",
            question=question[:200],
            document_ids=[str(d) for d in (request.document_ids or [])],
            retrieval_mode=request.retrieval_mode,
            streaming=True,
        )

        conversation = await self._get_or_create_conversation(request.conversation_id)
        history = await self._history_messages(conversation.id)
        await self._add_message(
            conversation.id,
            role=MessageRole.USER.value,
            content=question,
        )
        if conversation.title is None:
            conversation.title = question[:120]

        context, hits, mode, token_iter = await self.generator.stream_answer(
            question,
            document_ids=request.document_ids,
            mode=request.retrieval_mode,
            history=history,
        )
        flow(
            "chat.stream_ready",
            "Retrieval done; starting token stream",
            conversation_id=str(conversation.id),
            hits=len(hits),
            retrieval_mode=mode,
            context_tokens=context.token_estimate,
        )
        assistant = await self._add_message(
            conversation.id,
            role=MessageRole.ASSISTANT.value,
            content="",
            model_name=self.settings.ollama_model,
            meta={
                "retrieval_mode": mode,
                "streaming": True,
                "context_tokens": context.token_estimate,
            },
        )
        citations = await self._persist_citations(assistant, hits)
        await self.session.commit()
        assistant_id = assistant.id
        had_hits = bool(hits)

        async def _wrapped() -> AsyncIterator[str]:
            parts: list[str] = []
            started = time.perf_counter()
            try:
                async for token in token_iter:
                    parts.append(token)
                    yield token
            finally:
                content = "".join(parts).strip() or (
                    "I cannot answer based on the available documents."
                    if not had_hits
                    else ""
                )
                latency_ms = (time.perf_counter() - started) * 1000
                # Request-scoped session may already be closed; open a fresh one.
                from app.database.postgres import get_session_factory

                factory = get_session_factory()
                async with factory() as session:
                    message = await session.get(Message, assistant_id)
                    if message is not None:
                        message.content = content
                        message.latency_ms = latency_ms
                        await session.commit()

        return conversation, assistant, citations, _wrapped()

    async def finalize_stream_message(
        self,
        message_id: UUID,
        content: str,
        *,
        latency_ms: float | None = None,
    ) -> None:
        message = await self.session.get(Message, message_id)
        if message is None:
            return
        message.content = content
        if latency_ms is not None:
            message.latency_ms = latency_ms
        await self.session.commit()

    async def history(self, conversation_id: UUID) -> ConversationHistoryResponse:
        stmt = (
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(
                selectinload(Conversation.messages).selectinload(Message.citations)
            )
        )
        conversation = (await self.session.execute(stmt)).scalar_one_or_none()
        if conversation is None:
            raise NotFoundError(
                f"Conversation '{conversation_id}' not found",
                details={"conversation_id": str(conversation_id)},
            )
        messages: list[MessageResponse] = []
        for msg in conversation.messages:
            messages.append(
                MessageResponse(
                    id=msg.id,
                    conversation_id=msg.conversation_id,
                    role=msg.role,
                    content=msg.content,
                    model_name=msg.model_name,
                    prompt_tokens=msg.prompt_tokens,
                    completion_tokens=msg.completion_tokens,
                    total_tokens=msg.total_tokens,
                    latency_ms=msg.latency_ms,
                    meta=msg.meta or {},
                    citations=[
                        ChatCitation(
                            rank=c.rank,
                            chunk_id=c.chunk_id,
                            document_id=c.document_id,
                            score=c.score,
                            page_number=c.page_number,
                            source_filename=c.source_filename,
                            snippet=c.snippet,
                        )
                        for c in sorted(msg.citations, key=lambda item: item.rank)
                    ],
                    created_at=msg.created_at,
                    updated_at=msg.updated_at,
                )
            )
        return ConversationHistoryResponse(
            conversation_id=conversation.id,
            title=conversation.title,
            messages=messages,
        )

    async def _get_or_create_conversation(
        self,
        conversation_id: UUID | None,
    ) -> Conversation:
        if conversation_id is None:
            conversation = Conversation(title=None, meta={})
            self.session.add(conversation)
            await self.session.commit()
            await self.session.refresh(conversation)
            return conversation
        conversation = await self.session.get(Conversation, conversation_id)
        if conversation is None:
            raise NotFoundError(
                f"Conversation '{conversation_id}' not found",
                details={"conversation_id": str(conversation_id)},
            )
        return conversation

    async def _history_messages(self, conversation_id: UUID) -> list[ChatMessage]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        return [
            ChatMessage(role=row.role, content=row.content)
            for row in rows
            if row.content
        ]

    async def _add_message(
        self,
        conversation_id: UUID,
        *,
        role: str,
        content: str,
        model_name: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_ms: float | None = None,
        meta: dict | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            meta=meta or {},
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def _persist_citations(
        self,
        message: Message,
        hits: list[RetrievalHit],
    ) -> list[ChatCitation]:
        citations: list[ChatCitation] = []
        for rank, hit in enumerate(hits, start=1):
            chunk_uuid = hit.chunk_uuid
            doc_uuid = None
            if hit.document_id:
                try:
                    doc_uuid = UUID(hit.document_id)
                except ValueError:
                    doc_uuid = None
            citation = Citation(
                message_id=message.id,
                chunk_id=chunk_uuid,
                document_id=doc_uuid,
                rank=rank,
                score=hit.score,
                snippet=(hit.content or "")[:500],
                page_number=hit.page_number,
                source_filename=hit.source_filename,
                meta={"section_name": hit.section_name},
            )
            self.session.add(citation)
            citations.append(
                ChatCitation(
                    rank=rank,
                    chunk_id=chunk_uuid,
                    document_id=doc_uuid,
                    score=hit.score,
                    page_number=hit.page_number,
                    section_name=hit.section_name,
                    source_filename=hit.source_filename,
                    snippet=(hit.content or "")[:500],
                )
            )
        await self.session.flush()
        return citations
