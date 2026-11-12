"""Native parsers: PyMuPDF + format-specific libraries."""

from __future__ import annotations

import csv
import io
from pathlib import PurePosixPath
from typing import Any

from bs4 import BeautifulSoup
from docx import Document as DocxDocument
from openpyxl import load_workbook
from pptx import Presentation

from app.config import Settings
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.ingestion.loader import LoadedDocument
from app.ingestion.types import (
    DocumentMetadata,
    ParsedDocument,
    ParsedSection,
    ParsedTable,
)

logger = get_logger(__name__)


def _table_to_markdown(headers: list[str], rows: list[list[str]]) -> str:
    if not headers and not rows:
        return ""
    cols = headers or [f"col_{i+1}" for i in range(len(rows[0]) if rows else 0)]
    if not cols:
        return ""
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for row in rows:
        padded = list(row) + [""] * max(0, len(cols) - len(row))
        lines.append("| " + " | ".join(padded[: len(cols)]) + " |")
    return "\n".join(lines)


def _cells_to_str(values: list[Any]) -> list[str]:
    return ["" if v is None else str(v).strip() for v in values]


class NativeParser:
    """Parse documents with PyMuPDF and lightweight format libraries."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def parse(self, loaded: LoadedDocument) -> ParsedDocument:
        ext = loaded.extension
        handlers = {
            ".pdf": self._parse_pdf,
            ".txt": self._parse_text,
            ".md": self._parse_text,
            ".markdown": self._parse_text,
            ".html": self._parse_html,
            ".htm": self._parse_html,
            ".csv": self._parse_csv,
            ".docx": self._parse_docx,
            ".xlsx": self._parse_xlsx,
            ".pptx": self._parse_pptx,
        }
        handler = handlers.get(ext)
        if handler is None:
            raise ValidationError(
                f"No native parser for extension '{ext}'",
                details={"extension": ext},
            )
        result = handler(loaded)
        result.document_id = loaded.document_id
        result.document_version_id = loaded.document_version_id
        result.filename = loaded.filename
        result.content_type = loaded.content_type
        result.extension = loaded.extension
        return result.finalize()

    def _parse_text(self, loaded: LoadedDocument) -> ParsedDocument:
        try:
            text = loaded.data.decode("utf-8")
        except UnicodeDecodeError:
            text = loaded.data.decode("latin-1", errors="replace")
            warning = "Decoded text with latin-1 fallback"
        else:
            warning = None

        doc = ParsedDocument(
            filename=loaded.filename,
            content_type=loaded.content_type,
            extension=loaded.extension,
            parser_name="native-text",
            text=text,
            sections=[ParsedSection(page_number=1, text=text)],
            metadata=DocumentMetadata(
                title=PurePosixPath(loaded.filename).stem,
                page_count=1,
            ),
        )
        if warning:
            doc.warnings.append(warning)
        return doc

    def _parse_html(self, loaded: LoadedDocument) -> ParsedDocument:
        raw = loaded.data.decode("utf-8", errors="replace")
        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        text = soup.get_text("\n", strip=True)
        tables: list[ParsedTable] = []
        for idx, table in enumerate(soup.find_all("table"), start=1):
            rows_raw = []
            for tr in table.find_all("tr"):
                cells = [
                    c.get_text(" ", strip=True)
                    for c in tr.find_all(["th", "td"])
                ]
                if cells:
                    rows_raw.append(cells)
            if not rows_raw:
                continue
            headers = rows_raw[0]
            body = rows_raw[1:] if len(rows_raw) > 1 else []
            tables.append(
                ParsedTable(
                    page_number=1,
                    section_name=f"table_{idx}",
                    headers=headers,
                    rows=body,
                    markdown=_table_to_markdown(headers, body),
                )
            )
        return ParsedDocument(
            filename=loaded.filename,
            content_type=loaded.content_type,
            extension=loaded.extension,
            parser_name="native-html",
            text=text,
            sections=[ParsedSection(page_number=1, section_name=title, text=text)],
            tables=tables,
            metadata=DocumentMetadata(title=title, page_count=1),
        )

    def _parse_csv(self, loaded: LoadedDocument) -> ParsedDocument:
        raw = loaded.data.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(raw))
        rows = [_cells_to_str(row) for row in reader]
        headers = rows[0] if rows else []
        body = rows[1:] if len(rows) > 1 else []
        table = ParsedTable(
            page_number=1,
            section_name="csv",
            headers=headers,
            rows=body,
            markdown=_table_to_markdown(headers, body),
        )
        text = table.markdown
        return ParsedDocument(
            filename=loaded.filename,
            content_type=loaded.content_type,
            extension=loaded.extension,
            parser_name="native-csv",
            text=text,
            sections=[ParsedSection(page_number=1, text=text)],
            tables=[table],
            metadata=DocumentMetadata(
                title=PurePosixPath(loaded.filename).stem,
                page_count=1,
                extra={"row_count": len(body)},
            ),
        )

    def _parse_docx(self, loaded: LoadedDocument) -> ParsedDocument:
        document = DocxDocument(io.BytesIO(loaded.data))
        sections: list[ParsedSection] = []
        parts: list[str] = []
        current_heading: str | None = None
        buffer: list[str] = []

        def flush() -> None:
            nonlocal buffer, current_heading
            if buffer:
                text = "\n".join(buffer).strip()
                if text:
                    sections.append(
                        ParsedSection(section_name=current_heading, text=text)
                    )
                    parts.append(text)
            buffer = []

        for paragraph in document.paragraphs:
            style_name = (paragraph.style.name or "").lower() if paragraph.style else ""
            text = paragraph.text.strip()
            if not text:
                continue
            if "heading" in style_name:
                flush()
                current_heading = text
                parts.append(text)
            else:
                buffer.append(text)
        flush()

        tables: list[ParsedTable] = []
        for idx, table in enumerate(document.tables, start=1):
            matrix = [
                _cells_to_str([cell.text for cell in row.cells])
                for row in table.rows
            ]
            if not matrix:
                continue
            headers = matrix[0]
            body = matrix[1:] if len(matrix) > 1 else []
            md = _table_to_markdown(headers, body)
            tables.append(
                ParsedTable(
                    section_name=f"table_{idx}",
                    headers=headers,
                    rows=body,
                    markdown=md,
                )
            )
            parts.append(md)

        core = document.core_properties
        metadata = DocumentMetadata(
            title=core.title or PurePosixPath(loaded.filename).stem,
            author=core.author,
            created=core.created.isoformat() if core.created else None,
            modified=core.modified.isoformat() if core.modified else None,
            page_count=None,
        )
        return ParsedDocument(
            filename=loaded.filename,
            content_type=loaded.content_type,
            extension=loaded.extension,
            parser_name="native-docx",
            text="\n\n".join(parts),
            sections=sections or [ParsedSection(text="\n\n".join(parts))],
            tables=tables,
            metadata=metadata,
        )

    def _parse_xlsx(self, loaded: LoadedDocument) -> ParsedDocument:
        workbook = load_workbook(io.BytesIO(loaded.data), data_only=True, read_only=True)
        sheet_names = list(workbook.sheetnames)
        sections: list[ParsedSection] = []
        tables: list[ParsedTable] = []
        parts: list[str] = []
        for sheet_idx, sheet_name in enumerate(sheet_names, start=1):
            sheet = workbook[sheet_name]
            matrix: list[list[str]] = []
            for row in sheet.iter_rows(values_only=True):
                values = _cells_to_str(list(row))
                if any(values):
                    matrix.append(values)
            if not matrix:
                continue
            headers = matrix[0]
            body = matrix[1:] if len(matrix) > 1 else []
            md = _table_to_markdown(headers, body)
            tables.append(
                ParsedTable(
                    page_number=sheet_idx,
                    section_name=sheet_name,
                    headers=headers,
                    rows=body,
                    markdown=md,
                )
            )
            section_text = f"# {sheet_name}\n\n{md}"
            sections.append(
                ParsedSection(
                    page_number=sheet_idx,
                    section_name=sheet_name,
                    text=section_text,
                )
            )
            parts.append(section_text)
        workbook.close()
        return ParsedDocument(
            filename=loaded.filename,
            content_type=loaded.content_type,
            extension=loaded.extension,
            parser_name="native-xlsx",
            text="\n\n".join(parts),
            sections=sections,
            tables=tables,
            metadata=DocumentMetadata(
                title=PurePosixPath(loaded.filename).stem,
                page_count=len(sheet_names),
                extra={"sheet_names": sheet_names},
            ),
        )

    def _parse_pptx(self, loaded: LoadedDocument) -> ParsedDocument:
        presentation = Presentation(io.BytesIO(loaded.data))
        sections: list[ParsedSection] = []
        tables: list[ParsedTable] = []
        parts: list[str] = []
        for idx, slide in enumerate(presentation.slides, start=1):
            slide_parts: list[str] = []
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    text = shape.text_frame.text.strip()
                    if text:
                        slide_parts.append(text)
                if getattr(shape, "has_table", False):
                    matrix = [
                        _cells_to_str([cell.text for cell in row.cells])
                        for row in shape.table.rows
                    ]
                    if not matrix:
                        continue
                    headers = matrix[0]
                    body = matrix[1:] if len(matrix) > 1 else []
                    md = _table_to_markdown(headers, body)
                    tables.append(
                        ParsedTable(
                            page_number=idx,
                            section_name=f"slide_{idx}_table",
                            headers=headers,
                            rows=body,
                            markdown=md,
                        )
                    )
                    slide_parts.append(md)
            slide_text = "\n".join(slide_parts).strip()
            if slide_text:
                sections.append(
                    ParsedSection(
                        page_number=idx,
                        section_name=f"slide_{idx}",
                        text=slide_text,
                    )
                )
                parts.append(f"## Slide {idx}\n{slide_text}")
        return ParsedDocument(
            filename=loaded.filename,
            content_type=loaded.content_type,
            extension=loaded.extension,
            parser_name="native-pptx",
            text="\n\n".join(parts),
            sections=sections,
            tables=tables,
            metadata=DocumentMetadata(
                title=PurePosixPath(loaded.filename).stem,
                page_count=len(presentation.slides),
            ),
        )

    def _parse_pdf(self, loaded: LoadedDocument) -> ParsedDocument:
        import fitz  # PyMuPDF

        pdf = fitz.open(stream=loaded.data, filetype="pdf")
        sections: list[ParsedSection] = []
        tables: list[ParsedTable] = []
        parts: list[str] = []
        ocr_used = False
        warnings: list[str] = []

        for page_index in range(pdf.page_count):
            page = pdf.load_page(page_index)
            page_number = page_index + 1
            text = page.get_text("text").strip()

            # Table-ish extraction via text blocks is limited; capture find_tables when available.
            try:
                found = page.find_tables()
                for t_idx, table in enumerate(found.tables, start=1):  # type: ignore[attr-defined]
                    extracted = table.extract()
                    if not extracted:
                        continue
                    matrix = [_cells_to_str(row) for row in extracted]
                    headers = matrix[0]
                    body = matrix[1:] if len(matrix) > 1 else []
                    md = _table_to_markdown(headers, body)
                    tables.append(
                        ParsedTable(
                            page_number=page_number,
                            section_name=f"page_{page_number}_table_{t_idx}",
                            headers=headers,
                            rows=body,
                            markdown=md,
                        )
                    )
                    if md and md not in text:
                        text = f"{text}\n\n{md}".strip()
            except Exception as exc:  # noqa: BLE001 — table API varies by pymupdf build
                warnings.append(f"PDF table extraction skipped on page {page_number}: {exc}")

            if (
                self.settings.parser_enable_ocr
                and len(text) < self.settings.parser_ocr_min_chars
            ):
                ocr_text = self._ocr_page(page)
                if ocr_text:
                    text = ocr_text
                    ocr_used = True

            if text:
                sections.append(
                    ParsedSection(
                        page_number=page_number,
                        section_name=f"page_{page_number}",
                        text=text,
                    )
                )
                parts.append(text)

        meta_title = None
        meta_author = None
        meta_created = None
        meta_modified = None
        pdf_meta = pdf.metadata or {}
        meta_title = pdf_meta.get("title") or None
        meta_author = pdf_meta.get("author") or None
        meta_created = pdf_meta.get("creationDate") or None
        meta_modified = pdf_meta.get("modDate") or None
        page_count = pdf.page_count
        pdf.close()

        if ocr_used:
            warnings.append("OCR was used for one or more low-text PDF pages")

        return ParsedDocument(
            filename=loaded.filename,
            content_type=loaded.content_type,
            extension=loaded.extension,
            parser_name="native-pymupdf",
            text="\n\n".join(parts),
            sections=sections,
            tables=tables,
            metadata=DocumentMetadata(
                title=meta_title or PurePosixPath(loaded.filename).stem,
                author=meta_author,
                created=meta_created,
                modified=meta_modified,
                page_count=page_count,
            ),
            warnings=warnings,
            ocr_used=ocr_used,
        )

    def _ocr_page(self, page: Any) -> str:
        """OCR a PDF page via pytesseract when available."""
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            logger.warning("ocr_dependencies_missing")
            return ""

        try:
            pix = page.get_pixmap(dpi=200)
            image = Image.open(io.BytesIO(pix.tobytes("png")))
            text = pytesseract.image_to_string(image)
            return text.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("ocr_failed", error=str(exc))
            return ""
