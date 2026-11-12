"""Load document binaries from object storage for parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID

from app.config import Settings, get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.database.models import DocumentVersion
from app.ingestion.validation import resolve_extension
from app.storage import file_storage

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    """Binary payload ready for parsing."""

    document_id: UUID
    document_version_id: UUID
    version_number: int
    filename: str
    content_type: str | None
    extension: str
    object_key: str
    data: bytes
    size_bytes: int


class DocumentLoader:
    """Fetch a document version payload from MinIO."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def load_version(self, version: DocumentVersion) -> LoadedDocument:
        if not version.object_key:
            raise ValidationError(
                "Document version has no object storage key",
                details={"document_version_id": str(version.id)},
            )

        data = file_storage.download_bytes(
            version.object_key,
            settings=self.settings,
        )
        if not data:
            raise NotFoundError(
                "Document object is empty in storage",
                details={"object_key": version.object_key},
            )

        filename = version.filename or PurePosixPath(version.object_key).name
        extension = resolve_extension(filename)
        logger.info(
            "document_loaded",
            document_id=str(version.document_id),
            document_version_id=str(version.id),
            object_key=version.object_key,
            size_bytes=len(data),
            extension=extension,
        )
        return LoadedDocument(
            document_id=version.document_id,
            document_version_id=version.id,
            version_number=version.version_number,
            filename=filename,
            content_type=version.content_type,
            extension=extension,
            object_key=version.object_key,
            data=data,
            size_bytes=len(data),
        )
