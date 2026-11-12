"""Optional Docling-backed parser for advanced document understanding."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.config import Settings
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.ingestion.loader import LoadedDocument
from app.ingestion.types import DocumentMetadata, ParsedDocument, ParsedSection, ParsedTable

logger = get_logger(__name__)


def docling_available() -> bool:
    try:
        import docling  # noqa: F401
        return True
    except ImportError:
        return False


class DoclingParser:
    """Parse supported binaries through Docling when installed."""

    SUPPORTED = {
        ".pdf",
        ".docx",
        ".pptx",
        ".html",
        ".htm",
        ".md",
        ".markdown",
        ".csv",
        ".xlsx",
    }

    def __init__(self, settings: Settings) -> None:
        if not docling_available():
            raise ValidationError(
                "Docling is not installed. Set PARSER_BACKEND=native "
                "or install the docling package."
            )
        self.settings = settings

    def parse(self, loaded: LoadedDocument) -> ParsedDocument:
        if loaded.extension not in self.SUPPORTED:
            raise ValidationError(
                f"Docling does not support extension '{loaded.extension}'",
                details={"extension": loaded.extension},
            )

        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = self.settings.parser_enable_ocr
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            }
        )

        suffix = loaded.extension if loaded.extension != ".markdown" else ".md"
        with tempfile.TemporaryDirectory(prefix="rag-docling-") as tmp:
            path = Path(tmp) / f"input{suffix}"
            path.write_bytes(loaded.data)
            conversion = converter.convert(str(path))

        document = conversion.document
        markdown = document.export_to_markdown()
        sections = [
            ParsedSection(
                page_number=1,
                section_name="docling",
                text=markdown,
            )
        ]
        tables: list[ParsedTable] = []
        # Best-effort table export when Docling exposes tables.
        try:
            for idx, table in enumerate(getattr(document, "tables", []) or [], start=1):
                md = ""
                try:
                    md = table.export_to_markdown(doc=document)  # type: ignore[call-arg]
                except Exception:  # noqa: BLE001
                    md = str(table)
                tables.append(
                    ParsedTable(
                        section_name=f"docling_table_{idx}",
                        markdown=md,
                        rows=[],
                        headers=[],
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("docling_table_export_failed", error=str(exc))

        page_count = None
        try:
            page_count = len(getattr(document, "pages", []) or []) or None
        except Exception:  # noqa: BLE001
            page_count = None

        return ParsedDocument(
            document_id=loaded.document_id,
            document_version_id=loaded.document_version_id,
            filename=loaded.filename,
            content_type=loaded.content_type,
            extension=loaded.extension,
            parser_name="docling",
            text=markdown,
            sections=sections,
            tables=tables,
            metadata=DocumentMetadata(
                title=Path(loaded.filename).stem,
                page_count=page_count,
            ),
            ocr_used=bool(self.settings.parser_enable_ocr and loaded.extension == ".pdf"),
        ).finalize()
