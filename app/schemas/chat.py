"""Chat / retrieval / citation schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ChatCitation(BaseModel):
    rank: int
    chunk_id: UUID | None = None
    document_id: UUID | None = None
    score: float | None = None
    page_number: int | None = None
    section_name: str | None = None
    source_filename: str | None = None
    snippet: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: UUID | None = None
    document_ids: list[UUID] | None = None
    retrieval_mode: Literal["hybrid", "semantic", "bm25"] | None = None
    stream: bool = False


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    model: str
    retrieval_mode: str
    citations: list[ChatCitation] = Field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: float | None = None


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    model_name: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    citations: list[ChatCitation] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ConversationHistoryResponse(BaseModel):
    conversation_id: UUID
    title: str | None = None
    messages: list[MessageResponse] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    message_id: UUID
    rating: Literal["thumbs_up", "thumbs_down"]
    comment: str | None = None


class FeedbackResponse(BaseModel):
    id: UUID
    message_id: UUID
    rating: str
    comment: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1)
    document_ids: list[UUID] | None = None
    mode: Literal["hybrid", "semantic", "bm25"] | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)
    rerank: bool | None = None


class RetrieveHitResponse(BaseModel):
    chunk_id: str | None = None
    document_id: str | None = None
    score: float
    page_number: int | None = None
    section_name: str | None = None
    source_filename: str | None = None
    content_preview: str | None = None


class RetrieveResponse(BaseModel):
    query: str
    rewritten_query: str
    mode: str
    hits: list[RetrieveHitResponse] = Field(default_factory=list)
