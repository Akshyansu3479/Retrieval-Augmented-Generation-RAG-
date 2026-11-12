"""Document parsing facade with Docling / native backends."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.ingestion.loader import LoadedDocument
from app.ingestion.parsers.docling_parser import DoclingParser, docling_available
from app.ingestion.parsers.native import NativeParser
from app.ingestion.types import ParsedDocument

logger = get_logger(__name__)


class DocumentParser:
    """
    Parse loaded document bytes into structured text/tables/metadata.

    Backend selection:
    - native: PyMuPDF + format libraries
    - docling: require Docling
    - auto: Docling when installed and format supported, else native
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._native = NativeParser(self.settings)

    def parse(self, loaded: LoadedDocument) -> ParsedDocument:
        backend = self.settings.parser_backend
        if backend == "native":
            return self._native.parse(loaded)

        if backend == "docling":
            return DoclingParser(self.settings).parse(loaded)

        # auto
        if docling_available() and loaded.extension in DoclingParser.SUPPORTED:
            try:
                parsed = DoclingParser(self.settings).parse(loaded)
                logger.info(
                    "parsed_with_docling",
                    filename=loaded.filename,
                    extension=loaded.extension,
                )
                return parsed
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "docling_parse_failed_fallback_native",
                    error=str(exc),
                    filename=loaded.filename,
                )

        parsed = self._native.parse(loaded)
        logger.info(
            "parsed_with_native",
            filename=loaded.filename,
            parser_name=parsed.parser_name,
            extension=loaded.extension,
        )
        return parsed


def parse_bytes(
    *,
    data: bytes,
    filename: str,
    content_type: str | None = None,
    settings: Settings | None = None,
) -> ParsedDocument:
    """Convenience helper for ad-hoc parsing without MinIO metadata."""
    from uuid import uuid4

    from app.ingestion.validation import resolve_extension

    cfg = settings or get_settings()
    extension = resolve_extension(filename)
    if not extension:
        raise ValidationError("Filename must include an extension")

    loaded = LoadedDocument(
        document_id=uuid4(),
        document_version_id=uuid4(),
        version_number=1,
        filename=filename,
        content_type=content_type,
        extension=extension,
        object_key=f"ephemeral/{filename}",
        data=data,
        size_bytes=len(data),
    )
    return DocumentParser(cfg).parse(loaded)
