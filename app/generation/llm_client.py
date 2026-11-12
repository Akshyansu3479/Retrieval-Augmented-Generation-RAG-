"""Provider-independent LLM interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class LLMUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMClient(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        num_predict: int | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        num_predict: int | None = None,
    ) -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""  # pragma: no cover — makes this an async generator type

    @abstractmethod
    async def is_model_available(self) -> bool:
        raise NotImplementedError
