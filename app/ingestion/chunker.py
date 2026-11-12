"""Configurable multi-strategy document chunking engine."""

from __future__ import annotations

import hashlib
import re
from typing import Iterable, Literal

from app.config import Settings, get_settings
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.ingestion.chunk_types import ChunkDraft, ChunkingResult
from app.ingestion.types import ParsedDocument, ParsedSection, ParsedTable

logger = get_logger(__name__)

ChunkStrategy = Literal[
    "recursive",
    "token",
    "sentence",
    "heading",
    "semantic",
    "table_aware",
    "parent_child",
]

SUPPORTED_STRATEGIES: tuple[str, ...] = (
    "recursive",
    "token",
    "sentence",
    "heading",
    "semantic",
    "table_aware",
    "parent_child",
)

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|(?<=\n)\s*")
_HEADING_SPLIT_RE = re.compile(r"(?m)^(#{1,6}\s+.+)$")
_WORD_RE = re.compile(r"\S+")


def estimate_tokens(text: str) -> int:
    """Lightweight token estimate (whitespace words)."""
    if not text:
        return 0
    return max(1, len(_WORD_RE.findall(text)))


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DocumentChunker:
    """Chunk a ParsedDocument using the configured strategy."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def chunk(
        self,
        parsed: ParsedDocument,
        *,
        strategy: str | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> ChunkingResult:
        strategy_name = (strategy or self.settings.chunk_strategy).lower()
        size = chunk_size or self.settings.chunk_size
        overlap = chunk_overlap if chunk_overlap is not None else self.settings.chunk_overlap

        if strategy_name not in SUPPORTED_STRATEGIES:
            raise ValidationError(
                f"Unsupported chunk strategy '{strategy_name}'",
                details={"supported": list(SUPPORTED_STRATEGIES)},
            )
        if size < 32:
            raise ValidationError("chunk_size must be >= 32")
        if overlap < 0 or overlap >= size:
            raise ValidationError(
                "chunk_overlap must be >= 0 and < chunk_size",
                details={"chunk_size": size, "chunk_overlap": overlap},
            )

        handlers = {
            "recursive": self._chunk_recursive,
            "token": self._chunk_token,
            "sentence": self._chunk_sentence,
            "heading": self._chunk_heading,
            "semantic": self._chunk_semantic,
            "table_aware": self._chunk_table_aware,
            "parent_child": self._chunk_parent_child,
        }
        drafts = handlers[strategy_name](parsed, size=size, overlap=overlap)
        drafts = self._finalize_drafts(drafts, strategy=strategy_name)

        result = ChunkingResult(
            document_id=parsed.document_id,
            document_version_id=parsed.document_version_id,
            strategy=strategy_name,
            chunk_size=size,
            chunk_overlap=overlap,
            chunks=drafts,
        )
        logger.info(
            "document_chunked",
            filename=parsed.filename,
            strategy=strategy_name,
            chunk_count=result.chunk_count,
            chunk_size=size,
            chunk_overlap=overlap,
        )
        return result

    def _finalize_drafts(
        self,
        drafts: list[ChunkDraft],
        *,
        strategy: str,
    ) -> list[ChunkDraft]:
        finalized: list[ChunkDraft] = []
        for idx, draft in enumerate(drafts):
            content = draft.content.strip()
            if not content:
                continue
            finalized.append(
                draft.model_copy(
                    update={
                        "content": content,
                        "chunk_index": len(finalized),
                        "token_count": estimate_tokens(content),
                        "strategy": strategy,
                        "meta": {
                            **draft.meta,
                            "content_hash": content_sha256(content),
                        },
                    }
                )
            )
        # Re-map parent_index after dropping empties: parents keep relative indexes
        # among parent-only drafts first; children reference original parent_index.
        return finalized

    def _iter_section_units(
        self,
        parsed: ParsedDocument,
    ) -> Iterable[tuple[str, int | None, str | None]]:
        if parsed.sections:
            for section in parsed.sections:
                text = (section.text or "").strip()
                if text:
                    yield text, section.page_number, section.section_name
            return
        if parsed.text.strip():
            yield parsed.text.strip(), None, None

    def _split_recursive(self, text: str, *, size: int, overlap: int) -> list[str]:
        separators = ["\n\n", "\n", ". ", " ", ""]
        return self._recursive_split(text, separators=separators, size=size, overlap=overlap)

    def _recursive_split(
        self,
        text: str,
        *,
        separators: list[str],
        size: int,
        overlap: int,
    ) -> list[str]:
        text = text.strip()
        if not text:
            return []
        if len(text) <= size:
            return [text]

        sep = separators[0]
        rest = separators[1:] or [""]
        if sep:
            parts = text.split(sep)
        else:
            parts = list(text)

        chunks: list[str] = []
        current = ""
        for part in parts:
            piece = part if sep == "" else (part + sep if part != parts[-1] else part)
            candidate = f"{current}{piece}" if current else piece
            if len(candidate) <= size:
                current = candidate
                continue
            if current:
                chunks.append(current.strip())
            if len(piece) > size:
                if rest:
                    chunks.extend(
                        self._recursive_split(
                            piece,
                            separators=rest,
                            size=size,
                            overlap=overlap,
                        )
                    )
                    current = ""
                else:
                    start = 0
                    while start < len(piece):
                        end = min(start + size, len(piece))
                        chunks.append(piece[start:end].strip())
                        if end >= len(piece):
                            break
                        start = max(0, end - overlap)
                    current = ""
            else:
                current = piece
        if current.strip():
            chunks.append(current.strip())

        return self._apply_overlap(chunks, overlap=overlap)

    def _apply_overlap(self, chunks: list[str], *, overlap: int) -> list[str]:
        if overlap <= 0 or len(chunks) <= 1:
            return [c for c in chunks if c]
        overlapped: list[str] = []
        for idx, chunk in enumerate(chunks):
            if not chunk:
                continue
            if idx == 0:
                overlapped.append(chunk)
                continue
            prev = overlapped[-1]
            prefix = prev[-overlap:] if len(prev) > overlap else prev
            merged = f"{prefix}{chunk}" if not chunk.startswith(prefix) else chunk
            overlapped.append(merged)
        return overlapped

    def _pack_units(
        self,
        units: list[tuple[str, int | None, str | None]],
        *,
        size: int,
        overlap: int,
        measure: str = "chars",
    ) -> list[ChunkDraft]:
        drafts: list[ChunkDraft] = []
        current_parts: list[str] = []
        current_len = 0
        page_number: int | None = None
        section_name: str | None = None

        def flush() -> None:
            nonlocal current_parts, current_len, page_number, section_name
            if not current_parts:
                return
            content = " ".join(current_parts).strip()
            if content:
                drafts.append(
                    ChunkDraft(
                        content=content,
                        page_number=page_number,
                        section_name=section_name,
                        strategy="pending",
                    )
                )
            if overlap > 0 and content:
                # Keep a trailing overlap window for the next chunk.
                if measure == "tokens":
                    words = content.split()
                    keep = words[-overlap:] if len(words) > overlap else words
                    current_parts = keep
                    current_len = len(keep)
                else:
                    tail = content[-overlap:]
                    current_parts = [tail] if tail else []
                    current_len = len(tail)
            else:
                current_parts = []
                current_len = 0
            page_number = None
            section_name = None

        for text, page, section in units:
            unit_len = estimate_tokens(text) if measure == "tokens" else len(text)
            if unit_len > size:
                flush()
                # Oversized unit: hard-split recursively by characters.
                for piece in self._split_recursive(text, size=size, overlap=overlap):
                    drafts.append(
                        ChunkDraft(
                            content=piece,
                            page_number=page,
                            section_name=section,
                            strategy="pending",
                        )
                    )
                continue

            if current_len and current_len + unit_len + 1 > size:
                flush()

            if not current_parts:
                page_number = page
                section_name = section
            current_parts.append(text)
            current_len += unit_len + (1 if current_len else 0)

        flush()
        # Clear overlap leftovers that were only for packing.
        return [
            d
            for d in drafts
            if d.content.strip()
        ]

    def _chunk_recursive(
        self,
        parsed: ParsedDocument,
        *,
        size: int,
        overlap: int,
    ) -> list[ChunkDraft]:
        drafts: list[ChunkDraft] = []
        for text, page, section in self._iter_section_units(parsed):
            for piece in self._split_recursive(text, size=size, overlap=overlap):
                drafts.append(
                    ChunkDraft(
                        content=piece,
                        page_number=page,
                        section_name=section,
                        strategy="recursive",
                    )
                )
        return drafts

    def _chunk_token(
        self,
        parsed: ParsedDocument,
        *,
        size: int,
        overlap: int,
    ) -> list[ChunkDraft]:
        units: list[tuple[str, int | None, str | None]] = []
        for text, page, section in self._iter_section_units(parsed):
            for word in text.split():
                units.append((word, page, section))
        return self._pack_units(units, size=size, overlap=overlap, measure="tokens")

    def _split_sentences(self, text: str) -> list[str]:
        parts = [p.strip() for p in _SENTENCE_RE.split(text) if p and p.strip()]
        if parts:
            return parts
        return [text.strip()] if text.strip() else []

    def _chunk_sentence(
        self,
        parsed: ParsedDocument,
        *,
        size: int,
        overlap: int,
    ) -> list[ChunkDraft]:
        units: list[tuple[str, int | None, str | None]] = []
        for text, page, section in self._iter_section_units(parsed):
            for sentence in self._split_sentences(text):
                units.append((sentence, page, section))
        return self._pack_units(units, size=size, overlap=overlap, measure="chars")

    def _chunk_heading(
        self,
        parsed: ParsedDocument,
        *,
        size: int,
        overlap: int,
    ) -> list[ChunkDraft]:
        blocks: list[ParsedSection] = []
        if parsed.sections and any(s.section_name for s in parsed.sections):
            blocks = list(parsed.sections)
        else:
            # Split markdown-like headings from full text.
            text = parsed.text
            parts = _HEADING_SPLIT_RE.split(text)
            current_name: str | None = None
            buffer: list[str] = []
            for part in parts:
                if _HEADING_SPLIT_RE.match(part or ""):
                    if buffer:
                        blocks.append(
                            ParsedSection(
                                section_name=current_name,
                                text="\n".join(buffer).strip(),
                            )
                        )
                        buffer = []
                    current_name = part.lstrip("#").strip()
                elif part.strip():
                    buffer.append(part.strip())
            if buffer:
                blocks.append(
                    ParsedSection(
                        section_name=current_name,
                        text="\n".join(buffer).strip(),
                    )
                )

        drafts: list[ChunkDraft] = []
        for block in blocks:
            text = (block.text or "").strip()
            if not text:
                continue
            if len(text) <= size:
                drafts.append(
                    ChunkDraft(
                        content=text,
                        page_number=block.page_number,
                        section_name=block.section_name,
                        strategy="heading",
                    )
                )
            else:
                for piece in self._split_recursive(text, size=size, overlap=overlap):
                    drafts.append(
                        ChunkDraft(
                            content=piece,
                            page_number=block.page_number,
                            section_name=block.section_name,
                            strategy="heading",
                        )
                    )
        return drafts

    def _sentence_similarity(self, a: str, b: str) -> float:
        ta = {t.lower() for t in _WORD_RE.findall(a)}
        tb = {t.lower() for t in _WORD_RE.findall(b)}
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        union = len(ta | tb)
        return inter / union if union else 0.0

    def _chunk_semantic(
        self,
        parsed: ParsedDocument,
        *,
        size: int,
        overlap: int,
    ) -> list[ChunkDraft]:
        """
        Lexical-cohesion semantic chunking.

        Groups adjacent sentences when Jaccard similarity stays above threshold.
        Neural embedding-based semantic chunking can replace this in Phase 7+.
        """
        threshold = self.settings.chunk_semantic_threshold
        drafts: list[ChunkDraft] = []
        for text, page, section in self._iter_section_units(parsed):
            sentences = self._split_sentences(text)
            if not sentences:
                continue
            group = [sentences[0]]
            for sentence in sentences[1:]:
                sim = self._sentence_similarity(group[-1], sentence)
                candidate = " ".join(group + [sentence])
                if sim >= threshold and len(candidate) <= size:
                    group.append(sentence)
                else:
                    drafts.append(
                        ChunkDraft(
                            content=" ".join(group),
                            page_number=page,
                            section_name=section,
                            strategy="semantic",
                            meta={"similarity_threshold": threshold},
                        )
                    )
                    if overlap > 0 and group:
                        candidate = [group[-1], sentence]
                        group = (
                            candidate
                            if len(" ".join(candidate)) <= size
                            else [sentence]
                        )
                    else:
                        group = [sentence]
            if group:
                drafts.append(
                    ChunkDraft(
                        content=" ".join(group),
                        page_number=page,
                        section_name=section,
                        strategy="semantic",
                        meta={"similarity_threshold": threshold},
                    )
                )
        # Ensure oversized semantic groups are recursively split.
        normalized: list[ChunkDraft] = []
        for draft in drafts:
            if len(draft.content) <= size:
                normalized.append(draft)
            else:
                for piece in self._split_recursive(
                    draft.content, size=size, overlap=overlap
                ):
                    normalized.append(
                        draft.model_copy(update={"content": piece})
                    )
        return normalized

    def _table_markdown_chunks(
        self,
        table: ParsedTable,
        *,
        size: int,
    ) -> list[ChunkDraft]:
        md = (table.markdown or "").strip()
        if not md:
            return []
        if len(md) <= size:
            return [
                ChunkDraft(
                    content=md,
                    page_number=table.page_number,
                    section_name=table.section_name or "table",
                    strategy="table_aware",
                    meta={"is_table": True},
                )
            ]
        # Split large tables by row groups, preserving header.
        lines = md.splitlines()
        if len(lines) < 3:
            return [
                ChunkDraft(
                    content=piece,
                    page_number=table.page_number,
                    section_name=table.section_name or "table",
                    strategy="table_aware",
                    meta={"is_table": True},
                )
                for piece in self._split_recursive(md, size=size, overlap=0)
            ]
        header = "\n".join(lines[:2])
        body = lines[2:]
        drafts: list[ChunkDraft] = []
        current = [header]
        current_len = len(header)
        for row in body:
            if current_len + len(row) + 1 > size and len(current) > 1:
                drafts.append(
                    ChunkDraft(
                        content="\n".join(current),
                        page_number=table.page_number,
                        section_name=table.section_name or "table",
                        strategy="table_aware",
                        meta={"is_table": True},
                    )
                )
                current = [header, row]
                current_len = len(header) + len(row) + 1
            else:
                current.append(row)
                current_len += len(row) + 1
        if len(current) > 1:
            drafts.append(
                ChunkDraft(
                    content="\n".join(current),
                    page_number=table.page_number,
                    section_name=table.section_name or "table",
                    strategy="table_aware",
                    meta={"is_table": True},
                )
            )
        return drafts

    def _chunk_table_aware(
        self,
        parsed: ParsedDocument,
        *,
        size: int,
        overlap: int,
    ) -> list[ChunkDraft]:
        drafts: list[ChunkDraft] = []
        # Text sections first (excluding pure table markdown duplicates is best-effort).
        table_mds = {(t.markdown or "").strip() for t in parsed.tables if t.markdown}
        for text, page, section in self._iter_section_units(parsed):
            cleaned = text
            for md in table_mds:
                if md and md in cleaned:
                    cleaned = cleaned.replace(md, "\n")
            cleaned = cleaned.strip()
            if not cleaned:
                continue
            for piece in self._split_recursive(cleaned, size=size, overlap=overlap):
                drafts.append(
                    ChunkDraft(
                        content=piece,
                        page_number=page,
                        section_name=section,
                        strategy="table_aware",
                        meta={"is_table": False},
                    )
                )
        for table in parsed.tables:
            drafts.extend(self._table_markdown_chunks(table, size=size))
        return drafts

    def _chunk_parent_child(
        self,
        parsed: ParsedDocument,
        *,
        size: int,
        overlap: int,
    ) -> list[ChunkDraft]:
        parent_size = max(self.settings.chunk_parent_size, size * 2)
        parents = self._chunk_recursive(
            parsed,
            size=parent_size,
            overlap=max(overlap, self.settings.chunk_overlap),
        )
        drafts: list[ChunkDraft] = []
        for parent_idx, parent in enumerate(parents):
            drafts.append(
                parent.model_copy(
                    update={
                        "strategy": "parent_child",
                        "meta": {
                            **parent.meta,
                            "role": "parent",
                            "parent_index": parent_idx,
                        },
                        "parent_index": None,
                    }
                )
            )
            child_pieces = self._split_recursive(
                parent.content, size=size, overlap=overlap
            )
            for child in child_pieces:
                drafts.append(
                    ChunkDraft(
                        content=child,
                        page_number=parent.page_number,
                        section_name=parent.section_name,
                        strategy="parent_child",
                        parent_index=parent_idx,
                        meta={"role": "child", "parent_index": parent_idx},
                    )
                )
        return drafts
