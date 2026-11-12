"""Query preprocessing and optional lightweight rewriting."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s\-?.!]")


@dataclass
class ProcessedQuery:
    original: str
    normalized: str
    rewritten: str
    keywords: list[str]


class QueryProcessor:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def process(self, query: str) -> ProcessedQuery:
        original = query.strip()
        normalized = _WHITESPACE_RE.sub(" ", original).strip()
        rewritten = normalized
        if self.settings.query_rewrite_enabled:
            rewritten = self._rewrite(normalized)
        keywords = [
            token.lower()
            for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{1,}", rewritten)
            if len(token) > 2
        ]
        return ProcessedQuery(
            original=original,
            normalized=normalized,
            rewritten=rewritten,
            keywords=keywords,
        )

    def _rewrite(self, text: str) -> str:
        """
        Lightweight deterministic rewrite (no extra LLM round-trip).

        Expands common RAG shorthand and strips noisy punctuation.
        """
        lowered = text
        replacements = {
            r"\bw/\b": "with",
            r"\bw/o\b": "without",
            r"\binfo\b": "information",
            r"\bdocs?\b": "documents",
        }
        for pattern, repl in replacements.items():
            lowered = re.sub(pattern, repl, lowered, flags=re.IGNORECASE)
        cleaned = _PUNCT_RE.sub(" ", lowered)
        return _WHITESPACE_RE.sub(" ", cleaned).strip() or text
