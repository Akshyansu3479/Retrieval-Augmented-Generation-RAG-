"""Embedding providers (BGE via FastEmbed, optional OpenAI embeddings API)."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Sequence

import httpx
import numpy as np
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.core.exceptions import ConfigurationError, ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingProvider(ABC):
    """Provider-independent embedding interface."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def dimension(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def version(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed passages/documents."""
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        """Embed a query (defaults to document embedding)."""
        vectors = self.embed_documents([text])
        return vectors[0]


class BGEEmbeddingProvider(EmbeddingProvider):
    """
    BGE embeddings via FastEmbed (ONNX).

    Default model: BAAI/bge-base-en-v1.5 (768-d).
    """

    def __init__(self, settings: Settings) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise ConfigurationError(
                "fastembed is required for BGE embeddings. "
                "Install with: pip install fastembed"
            ) from exc

        self._settings = settings
        self._model_name = settings.embedding_model
        self._version = settings.embedding_version
        self._expected_dim = settings.embedding_dimension
        logger.info("bge_embedding_loading", model=self._model_name)
        self._model = TextEmbedding(model_name=self._model_name)
        # Probe dimension once.
        probe = list(self._model.embed(["dimension probe"]))[0]
        self._dimension = int(len(probe))
        if self._dimension != self._expected_dim:
            raise ConfigurationError(
                "Embedding dimension mismatch with configuration",
                details={
                    "model": self._model_name,
                    "model_dimension": self._dimension,
                    "configured_dimension": self._expected_dim,
                    "hint": (
                        "Set EMBEDDING_DIMENSION to match the model, "
                        "and recreate the Qdrant collection if needed."
                    ),
                },
            )
        logger.info(
            "bge_embedding_ready",
            model=self._model_name,
            dimension=self._dimension,
        )

    @property
    def provider_name(self) -> str:
        return "bge"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def version(self) -> str:
        return self._version

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        cleaned = [text if text and text.strip() else " " for text in texts]
        vectors = list(self._model.embed(cleaned, batch_size=self._settings.embedding_batch_size))
        return [_normalize(np.asarray(vec, dtype=np.float32)).tolist() for vec in vectors]

    def embed_query(self, text: str) -> list[float]:
        # BGE retrieval tip: prefix queries; FastEmbed may handle this for some models.
        query = text if text.strip().startswith("Represent") else text
        return self.embed_documents([query])[0]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible embeddings HTTP API (embeddings only — not chat/LLM)."""

    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ConfigurationError(
                "OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai"
            )
        self._settings = settings
        self._model_name = settings.openai_embedding_model
        self._version = settings.embedding_version
        self._dimension = settings.embedding_dimension
        self._base_url = (
            settings.openai_base_url or "https://api.openai.com/v1"
        ).rstrip("/")
        self._api_key = settings.openai_api_key

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def version(self) -> str:
        return self._version

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed_with_retry(list(texts))

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def _embed_with_retry(self, texts: list[str]) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, object] = {
            "model": self._model_name,
            "input": texts,
        }
        # text-embedding-3-* supports dimensions parameter
        if self._model_name.startswith("text-embedding-3"):
            payload["dimensions"] = self._dimension

        with httpx.Client(timeout=self._settings.openai_timeout) as client:
            response = client.post(
                f"{self._base_url}/embeddings",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        items = sorted(data.get("data") or [], key=lambda row: row.get("index", 0))
        vectors = [list(map(float, row["embedding"])) for row in items]
        for vector in vectors:
            if len(vector) != self._dimension:
                raise ValidationError(
                    "OpenAI embedding dimension mismatch",
                    details={
                        "expected": self._dimension,
                        "actual": len(vector),
                        "model": self._model_name,
                    },
                )
        return [_normalize(np.asarray(vec, dtype=np.float32)).tolist() for vec in vectors]


def _normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        return vector
    return vector / norm


_provider: EmbeddingProvider | None = None


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Lazy singleton embedding provider."""
    global _provider
    cfg = settings or get_settings()
    if _provider is None:
        _provider = create_embedding_provider(cfg)
    return _provider


def reset_embedding_provider() -> None:
    global _provider
    _provider = None


def create_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    cfg = settings or get_settings()
    if cfg.embedding_provider == "openai":
        return OpenAIEmbeddingProvider(cfg)
    if cfg.embedding_provider == "bge":
        return BGEEmbeddingProvider(cfg)
    raise ConfigurationError(
        f"Unsupported embedding provider '{cfg.embedding_provider}'"
    )


def embedding_cache_key(chunk_id: str, model: str, version: str) -> str:
    digest = hashlib.sha1(f"{model}:{version}".encode()).hexdigest()[:10]
    return f"rag:emb:{digest}:{chunk_id}"
