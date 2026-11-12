"""Build a token-budgeted context window from retrieval hits."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.retrieval.types import RetrievalHit


def estimate_tokens(text: str) -> int:
    # Rough heuristic (~4 chars/token) — good enough for budget gating.
    return max(1, len(text) // 4)


@dataclass
class ContextPassage:
    index: int
    hit: RetrievalHit
    text: str


@dataclass
class BuiltContext:
    passages: list[ContextPassage]
    context_block: str
    token_estimate: int
    truncated: bool


class ContextBuilder:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def build(self, hits: list[RetrievalHit]) -> BuiltContext:
        max_tokens = self.settings.context_max_tokens
        passages: list[ContextPassage] = []
        used = 0
        truncated = False
        blocks: list[str] = []

        for idx, hit in enumerate(hits, start=1):
            header = (
                f"[{idx}] source={hit.source_filename or 'unknown'}"
                f" page={hit.page_number if hit.page_number is not None else '-'}"
                f" section={hit.section_name or '-'}"
            )
            body = (hit.content or "").strip()
            if not body:
                continue
            piece = f"{header}\n{body}"
            cost = estimate_tokens(piece) + 8
            if used + cost > max_tokens and passages:
                truncated = True
                break
            if used + cost > max_tokens and not passages:
                # Always include at least one truncated passage.
                keep_chars = max_tokens * 4
                body = body[:keep_chars]
                piece = f"{header}\n{body}"
                truncated = True
                cost = estimate_tokens(piece)
            passages.append(ContextPassage(index=idx, hit=hit, text=body))
            blocks.append(piece)
            used += cost
            if truncated:
                break

        context_block = "\n\n".join(blocks) if blocks else "(no context retrieved)"
        return BuiltContext(
            passages=passages,
            context_block=context_block,
            token_estimate=used,
            truncated=truncated,
        )
