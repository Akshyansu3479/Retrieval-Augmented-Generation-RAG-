"""Ollama HTTP LLM client (exclusive generation provider)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.core.exceptions import OllamaError
from app.core.logging import get_logger
from app.generation.llm_client import ChatMessage, LLMClient, LLMResponse, LLMUsage

logger = get_logger(__name__)


class OllamaClient(LLMClient):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.ollama_base_url.rstrip("/")
        self.model = self.settings.ollama_model

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.settings.ollama_timeout),
        )

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        num_predict: int | None = None,
    ) -> LLMResponse:
        payload = self._chat_payload(
            messages,
            stream=False,
            temperature=temperature,
            num_predict=num_predict,
        )
        data = await self._post_chat(payload)
        message = data.get("message") or {}
        content = str(message.get("content") or "")
        usage = LLMUsage(
            prompt_tokens=_as_int(data.get("prompt_eval_count")),
            completion_tokens=_as_int(data.get("eval_count")),
            total_tokens=_sum_ints(
                data.get("prompt_eval_count"),
                data.get("eval_count"),
            ),
        )
        return LLMResponse(
            content=content,
            model=str(data.get("model") or self.model),
            usage=usage,
            raw=data,
        )

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        num_predict: int | None = None,
    ) -> AsyncIterator[str]:
        payload = self._chat_payload(
            messages,
            stream=True,
            temperature=temperature,
            num_predict=num_predict,
        )
        attempts = max(1, self.settings.ollama_max_retries)

        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                async with self._client() as client:
                    async with client.stream("POST", "/api/chat", json=payload) as resp:
                        if resp.status_code >= 400:
                            body = await resp.aread()
                            raise OllamaError(
                                f"Ollama stream failed ({resp.status_code})",
                                details={"body": body.decode("utf-8", errors="replace")[:500]},
                            )
                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            import orjson

                            chunk = orjson.loads(line)
                            if chunk.get("error"):
                                raise OllamaError(str(chunk["error"]))
                            message = chunk.get("message") or {}
                            token = message.get("content")
                            if token:
                                yield str(token)
                            if chunk.get("done"):
                                return
                return
            except (httpx.HTTPError, OllamaError, ValueError) as exc:
                last_error = exc
                logger.warning("ollama_stream_retry", error=str(exc))
        raise OllamaError(
            "Ollama streaming failed after retries",
            details={"error": str(last_error)},
        )

    async def is_model_available(self) -> bool:
        try:
            async with self._client() as client:
                resp = await client.get("/api/tags")
                resp.raise_for_status()
                models = resp.json().get("models") or []
                names = {str(m.get("name") or "") for m in models}
                return self.model in names or any(
                    name.startswith(f"{self.model.split(':')[0]}:") for name in names
                )
        except Exception:  # noqa: BLE001
            return False

    def _chat_payload(
        self,
        messages: Sequence[ChatMessage],
        *,
        stream: bool,
        temperature: float | None,
        num_predict: int | None,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
            "options": {
                "temperature": (
                    self.settings.ollama_temperature
                    if temperature is None
                    else temperature
                ),
                "num_ctx": self.settings.ollama_num_ctx,
                "num_predict": (
                    self.settings.ollama_num_predict
                    if num_predict is None
                    else num_predict
                ),
            },
        }

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        attempts = max(1, self.settings.ollama_max_retries)

        @retry(
            reraise=True,
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=1, min=1, max=8),
        )
        async def _call() -> dict[str, Any]:
            async with self._client() as client:
                resp = await client.post("/api/chat", json=payload)
                if resp.status_code >= 400:
                    raise OllamaError(
                        f"Ollama chat failed ({resp.status_code})",
                        details={"body": resp.text[:500]},
                    )
                data = resp.json()
                if data.get("error"):
                    raise OllamaError(str(data["error"]))
                return data

        try:
            return await _call()
        except httpx.HTTPError as exc:
            raise OllamaError(
                "Ollama connection failed",
                details={"error": str(exc), "base_url": self.base_url},
            ) from exc


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _sum_ints(*values: Any) -> int | None:
    nums = [_as_int(v) for v in values]
    if any(n is None for n in nums):
        return None
    return sum(n for n in nums if n is not None)


def get_llm_client(settings: Settings | None = None) -> LLMClient:
    return OllamaClient(settings=settings)
