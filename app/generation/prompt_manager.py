"""Prompt templates for grounded RAG answers."""

from __future__ import annotations

SYSTEM_PROMPT = """You are a careful retrieval-augmented assistant.
Answer ONLY using the provided context passages.
If the context is insufficient, say you cannot answer based on the available documents.
When you use information from a passage, cite it inline using [n] where n is the passage number.
Do not invent sources or facts outside the context."""


def build_user_prompt(*, question: str, context_block: str) -> str:
    return (
        "Context passages:\n"
        f"{context_block}\n\n"
        f"Question: {question}\n\n"
        "Provide a concise answer with inline citations like [1], [2]."
    )
