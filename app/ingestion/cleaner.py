"""Text cleaning for extracted document content."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.ingestion.types import ParsedDocument, ParsedSection, ParsedTable

logger = get_logger(__name__)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTISPACE_RE = re.compile(r"[^\S\n\t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")
_FORM_FEED_RE = re.compile(r"\f+")
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_SMART_QUOTES = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u00a0": " ",
    "\u2026": "...",
}


@dataclass(slots=True)
class CleaningStats:
    """Counters describing cleaning transformations."""

    original_char_count: int = 0
    cleaned_char_count: int = 0
    characters_removed: int = 0
    hyphen_breaks_fixed: int = 0
    control_chars_removed: int = 0
    blank_lines_collapsed: int = 0
    sections_cleaned: int = 0
    tables_cleaned: int = 0
    operations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "original_char_count": self.original_char_count,
            "cleaned_char_count": self.cleaned_char_count,
            "characters_removed": self.characters_removed,
            "hyphen_breaks_fixed": self.hyphen_breaks_fixed,
            "control_chars_removed": self.control_chars_removed,
            "blank_lines_collapsed": self.blank_lines_collapsed,
            "sections_cleaned": self.sections_cleaned,
            "tables_cleaned": self.tables_cleaned,
            "operations": list(self.operations),
        }


class TextCleaner:
    """Normalize and clean parsed document text/tables for downstream chunking."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def clean_document(self, parsed: ParsedDocument) -> tuple[ParsedDocument, CleaningStats]:
        stats = CleaningStats(original_char_count=len(parsed.text or ""))
        if not self.settings.cleaner_enabled:
            stats.cleaned_char_count = stats.original_char_count
            stats.operations.append("skipped")
            return parsed, stats

        cleaned_sections: list[ParsedSection] = []
        for section in parsed.sections:
            cleaned_text, section_stats = self.clean_text(section.text)
            stats.hyphen_breaks_fixed += section_stats.hyphen_breaks_fixed
            stats.control_chars_removed += section_stats.control_chars_removed
            stats.blank_lines_collapsed += section_stats.blank_lines_collapsed
            stats.sections_cleaned += 1
            cleaned_sections.append(
                section.model_copy(update={"text": cleaned_text})
            )

        cleaned_tables: list[ParsedTable] = []
        for table in parsed.tables:
            headers = [self.clean_text(h)[0] for h in table.headers]
            rows = [[self.clean_text(cell)[0] for cell in row] for row in table.rows]
            markdown, _ = self.clean_text(table.markdown)
            cleaned_tables.append(
                table.model_copy(
                    update={
                        "headers": headers,
                        "rows": rows,
                        "markdown": markdown,
                    }
                )
            )
            stats.tables_cleaned += 1

        parsed.sections = cleaned_sections
        parsed.tables = cleaned_tables
        if cleaned_sections:
            parsed.text = "\n\n".join(
                section.text for section in cleaned_sections if section.text.strip()
            )
        else:
            parsed.text, text_stats = self.clean_text(parsed.text)
            stats.hyphen_breaks_fixed += text_stats.hyphen_breaks_fixed
            stats.control_chars_removed += text_stats.control_chars_removed
            stats.blank_lines_collapsed += text_stats.blank_lines_collapsed

        parsed.finalize()
        stats.cleaned_char_count = parsed.char_count
        stats.characters_removed = max(
            0, stats.original_char_count - stats.cleaned_char_count
        )
        stats.operations.extend(
            [
                "unicode_normalize",
                "control_char_strip",
                "whitespace_normalize",
                "hyphen_break_fix",
                "smart_quote_normalize",
            ]
        )
        if self.settings.cleaner_strip_urls:
            stats.operations.append("url_strip")

        logger.info(
            "document_cleaned",
            filename=parsed.filename,
            removed=stats.characters_removed,
            sections=stats.sections_cleaned,
            tables=stats.tables_cleaned,
        )
        return parsed, stats

    def clean_text(self, text: str) -> tuple[str, CleaningStats]:
        """Clean a single text blob and return stats for that blob."""
        stats = CleaningStats(original_char_count=len(text or ""))
        if not text:
            return "", stats

        value = unicodedata.normalize("NFKC", text)
        for src, dst in _SMART_QUOTES.items():
            if src in value:
                value = value.replace(src, dst)

        before_ctrl = len(value)
        value = _ZERO_WIDTH_RE.sub("", value)
        value = _FORM_FEED_RE.sub("\n", value)
        value = _CONTROL_CHARS_RE.sub("", value)
        stats.control_chars_removed = max(0, before_ctrl - len(value))

        value = value.replace("\r\n", "\n").replace("\r", "\n")

        if self.settings.cleaner_fix_hyphenation:
            value, n = _HYPHEN_BREAK_RE.subn(r"\1\2", value)
            stats.hyphen_breaks_fixed = n

        # Keep intentional single newlines; collapse runs of blank lines.
        value = "\n".join(line.rstrip() for line in value.split("\n"))
        value = _MULTISPACE_RE.sub(" ", value)
        collapsed, n_blank = _MULTI_NEWLINE_RE.subn("\n\n", value)
        value = collapsed
        stats.blank_lines_collapsed = n_blank

        if self.settings.cleaner_strip_urls:
            value = re.sub(r"https?://\S+|www\.\S+", " ", value)
            value = _MULTISPACE_RE.sub(" ", value)
            value = _MULTI_NEWLINE_RE.sub("\n\n", value)

        value = value.strip()
        stats.cleaned_char_count = len(value)
        stats.characters_removed = max(
            0, stats.original_char_count - stats.cleaned_char_count
        )
        return value, stats
