"""Chat, streaming, history, retrieval, and feedback endpoints."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.config import Settings, get_settings
from app.database.postgres import DbSession
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationHistoryResponse,
    FeedbackRequest,
    FeedbackResponse,
    RetrieveRequest,
    RetrieveResponse,
)
from app.services.chat_service import ChatService
from app.services.feedback_service import FeedbackService
from app.services.retrieval_service import RetrievalService

router = APIRouter(tags=["chat"])


def get_chat_service(
    session: DbSession,
    settings: Settings = Depends(get_settings),
) -> ChatService:
    return ChatService(session=session, settings=settings)


def get_feedback_service(session: DbSession) -> FeedbackService:
    return FeedbackService(session=session)


def get_retrieval_service(
    session: DbSession,
    settings: Settings = Depends(get_settings),
) -> RetrievalService:
    return RetrievalService(session=session, settings=settings)


@router.post("/chat", response_model=ChatResponse, summary="RAG chat (non-streaming)")
async def chat(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    return await service.chat(request)


@router.post("/chat/stream", summary="RAG chat with SSE token stream")
async def chat_stream(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    conversation, assistant, citations, tokens = await service.stream_chat(request)

    async def event_generator():
        meta = {
            "event": "meta",
            "conversation_id": str(conversation.id),
            "message_id": str(assistant.id),
            "citations": [c.model_dump(mode="json") for c in citations],
        }
        yield f"data: {json.dumps(meta)}\n\n"
        async for token in tokens:
            yield f"data: {json.dumps({'event': 'token', 'token': token})}\n\n"
        yield f"data: {json.dumps({'event': 'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get(
    "/chat/history",
    response_model=ConversationHistoryResponse,
    summary="Conversation history",
)
async def chat_history(
    conversation_id: UUID,
    service: ChatService = Depends(get_chat_service),
) -> ConversationHistoryResponse:
    return await service.history(conversation_id)


@router.post(
    "/retrieve",
    response_model=RetrieveResponse,
    summary="Retrieve passages without generation",
)
async def retrieve(
    request: RetrieveRequest,
    service: RetrievalService = Depends(get_retrieval_service),
) -> RetrieveResponse:
    return await service.retrieve(request)


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    summary="Submit feedback on an assistant message",
)
async def feedback(
    request: FeedbackRequest,
    service: FeedbackService = Depends(get_feedback_service),
) -> FeedbackResponse:
    return await service.create(request)
