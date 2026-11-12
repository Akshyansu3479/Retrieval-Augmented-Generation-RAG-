"""Grounded answer generation using retrieved context + Ollama."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.flow_log import flow
from app.generation.context_builder import BuiltContext, ContextBuilder
from app.generation.llm_client import ChatMessage, LLMResponse
from app.generation.ollama_client import get_llm_client
from app.generation.prompt_manager import SYSTEM_PROMPT, build_user_prompt
from app.retrieval.retriever import Retriever
from app.retrieval.types import RetrievalHit


@dataclass
class GeneratedAnswer:
    answer: str
    model: str
    context: BuiltContext
    hits: list[RetrievalHit]
    usage_prompt_tokens: int | None = None
    usage_completion_tokens: int | None = None
    usage_total_tokens: int | None = None
    retrieval_mode: str = "hybrid"


class ResponseGenerator:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.retriever = Retriever(session=session, settings=self.settings)
        self.context_builder = ContextBuilder(self.settings)
        self.llm = get_llm_client(self.settings)

    async def answer(
        self,
        question: str,
        *,
        document_ids: list[UUID] | None = None,
        mode: str | None = None,
        history: list[ChatMessage] | None = None,
    ) -> GeneratedAnswer:
        retrieval = await self.retriever.retrieve(
            question,
            document_ids=document_ids,
            mode=mode,
        )
        context = self.context_builder.build(retrieval.hits)
        flow(
            "context.build",
            "Context window built",
            passages=len(context.passages),
            token_estimate=context.token_estimate,
            truncated=context.truncated,
        )
        messages = self._messages(question, context, history=history)
        flow(
            "llm.generate",
            "Calling Ollama",
            model=self.settings.ollama_model,
            message_count=len(messages),
            streaming=False,
        )
        response = await self.llm.generate(messages)
        flow(
            "llm.done",
            "Ollama response received",
            model=response.model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            answer_chars=len(response.content or ""),
        )
        return self._to_answer(response, context, retrieval.hits, retrieval.mode)

    async def stream_answer(
        self,
        question: str,
        *,
        document_ids: list[UUID] | None = None,
        mode: str | None = None,
        history: list[ChatMessage] | None = None,
    ) -> tuple[BuiltContext, list[RetrievalHit], str, AsyncIterator[str]]:
        retrieval = await self.retriever.retrieve(
            question,
            document_ids=document_ids,
            mode=mode,
        )
        context = self.context_builder.build(retrieval.hits)
        flow(
            "context.build",
            "Context window built",
            passages=len(context.passages),
            token_estimate=context.token_estimate,
            truncated=context.truncated,
        )
        messages = self._messages(question, context, history=history)
        flow(
            "llm.generate",
            "Calling Ollama (stream)",
            model=self.settings.ollama_model,
            message_count=len(messages),
            streaming=True,
        )

        async def _tokens() -> AsyncIterator[str]:
            async for token in self.llm.stream(messages):
                yield token
            flow("llm.done", "Ollama stream finished", model=self.settings.ollama_model)

        return context, retrieval.hits, retrieval.mode, _tokens()

    def _messages(
        self,
        question: str,
        context: BuiltContext,
        *,
        history: list[ChatMessage] | None,
    ) -> list[ChatMessage]:
        messages: list[ChatMessage] = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
        if history:
            # Keep a short trailing history window.
            messages.extend(history[-6:])
        messages.append(
            ChatMessage(
                role="user",
                content=build_user_prompt(
                    question=question,
                    context_block=context.context_block,
                ),
            )
        )
        return messages

    def _to_answer(
        self,
        response: LLMResponse,
        context: BuiltContext,
        hits: list[RetrievalHit],
        mode: str,
    ) -> GeneratedAnswer:
        answer = response.content.strip()
        if not hits:
            answer = (
                "I cannot answer based on the available documents — "
                "no relevant passages were retrieved."
            )
        return GeneratedAnswer(
            answer=answer,
            model=response.model,
            context=context,
            hits=hits,
            usage_prompt_tokens=response.usage.prompt_tokens,
            usage_completion_tokens=response.usage.completion_tokens,
            usage_total_tokens=response.usage.total_tokens,
            retrieval_mode=mode,
        )
