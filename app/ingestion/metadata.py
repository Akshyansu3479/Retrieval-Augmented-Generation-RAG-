"""Metadata enrichment for parsed documents."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.ingestion.types import DocumentMetadata, ParsedDocument

logger = get_logger(__name__)

_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s+|(?:[A-Z][A-Za-z0-9 ,/&\-]{2,80})$)",
    re.MULTILINE,
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}")

_EN_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "all",
        "can",
        "had",
        "her",
        "was",
        "one",
        "our",
        "out",
        "has",
        "have",
        "been",
        "from",
        "that",
        "this",
        "with",
        "they",
        "were",
        "what",
        "when",
        "your",
        "which",
        "their",
        "will",
        "there",
        "would",
        "about",
        "into",
        "than",
        "then",
        "them",
        "these",
        "could",
        "other",
        "some",
        "such",
        "only",
        "over",
        "also",
        "more",
        "most",
        "very",
    }
)

_EN_MARKERS = frozenset(
    {"the", "and", "of", "to", "in", "is", "that", "for", "on", "with"}
)


class MetadataExtractor:
    """Enrich document metadata after parsing/cleaning."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def enrich(self, parsed: ParsedDocument) -> ParsedDocument:
        if not self.settings.metadata_enrichment_enabled:
            return parsed

        meta = parsed.metadata or DocumentMetadata()
        text = parsed.text or ""

        inferred_title = self._infer_title(parsed)
        filename_stem = PurePosixPath(parsed.filename).stem
        if not meta.title or meta.title.strip().lower() in {
            filename_stem.lower(),
            parsed.filename.lower(),
        }:
            meta.title = inferred_title

        if not meta.language:
            meta.language = self._infer_language(text)

        headings = self._extract_headings(parsed)
        keywords = self._extract_keywords(text)
        section_names = [
            section.section_name
            for section in parsed.sections
            if section.section_name
        ]

        extra = dict(meta.extra or {})
        extra.update(
            {
                "filename_stem": PurePosixPath(parsed.filename).stem,
                "extension": parsed.extension,
                "content_type": parsed.content_type,
                "parser_name": parsed.parser_name,
                "ocr_used": parsed.ocr_used,
                "char_count": parsed.char_count,
                "word_count": parsed.word_count,
                "section_count": len(parsed.sections),
                "table_count": len(parsed.tables),
                "headings": headings[: self.settings.metadata_max_headings],
                "keywords": keywords[: self.settings.metadata_max_keywords],
                "section_names": section_names[:50],
                "avg_section_chars": (
                    round(
                        sum(len(s.text) for s in parsed.sections)
                        / max(len(parsed.sections), 1)
                    )
                    if parsed.sections
                    else 0
                ),
            }
        )
        meta.extra = extra
        if meta.page_count is None:
            pages = {
                s.page_number for s in parsed.sections if s.page_number is not None
            }
            if pages:
                meta.page_count = max(pages)

        parsed.metadata = meta
        logger.info(
            "metadata_enriched",
            filename=parsed.filename,
            title=meta.title,
            language=meta.language,
            keywords=len(keywords),
            headings=len(headings),
        )
        return parsed

    def _infer_title(self, parsed: ParsedDocument) -> str:
        for section in parsed.sections:
            if section.section_name and section.section_name.strip():
                candidate = section.section_name.strip()
                if not candidate.lower().startswith("page_"):
                    return candidate[:200]
            first_line = (section.text or "").strip().splitlines()[:1]
            if first_line:
                line = first_line[0].lstrip("#").strip()
                if 3 <= len(line) <= 120:
                    return line
        return PurePosixPath(parsed.filename).stem

    def _infer_language(self, text: str) -> str | None:
        tokens = [t.lower() for t in _TOKEN_RE.findall(text[:5000])]
        if len(tokens) < 20:
            return None
        hits = sum(1 for token in tokens if token in _EN_MARKERS)
        ratio = hits / len(tokens)
        if ratio >= 0.04:
            return "en"
        return "unknown"

    def _extract_headings(self, parsed: ParsedDocument) -> list[str]:
        headings: list[str] = []
        seen: set[str] = set()
        for section in parsed.sections:
            if section.section_name:
                name = section.section_name.strip()
                key = name.lower()
                if name and key not in seen and not key.startswith("page_"):
                    seen.add(key)
                    headings.append(name)
            for match in _HEADING_RE.findall(section.text or ""):
                cleaned = match.lstrip("#").strip()
                key = cleaned.lower()
                if cleaned and key not in seen and len(cleaned) <= 120:
                    seen.add(key)
                    headings.append(cleaned)
        return headings

    def _extract_keywords(self, text: str) -> list[str]:
        tokens = [
            token.lower()
            for token in _TOKEN_RE.findall(text.lower())
            if token.lower() not in _EN_STOPWORDS and not token.isdigit()
        ]
        if not tokens:
            return []
        counts = Counter(tokens)
        return [word for word, _ in counts.most_common(50)]
