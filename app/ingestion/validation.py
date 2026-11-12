"""Upload validation helpers for document ingestion."""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.config import Settings
from app.core.constants import SUPPORTED_DOCUMENT_EXTENSIONS
from app.core.exceptions import ValidationError

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._\- ]+")

EXTENSION_CONTENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    ".csv": "text/csv",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
}


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    """Normalized metadata for an accepted upload."""

    original_filename: str
    safe_filename: str
    extension: str
    content_type: str


def sanitize_filename(filename: str) -> str:
    """Return a filesystem-safe basename."""
    name = PurePosixPath(filename.replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        raise ValidationError("Filename is required")
    cleaned = _SAFE_FILENAME_RE.sub("_", name).strip(" ._")
    if not cleaned:
        raise ValidationError("Filename is invalid after sanitization")
    if len(cleaned) > 255:
        stem = PurePosixPath(cleaned).stem[:200]
        suffix = PurePosixPath(cleaned).suffix[:40]
        cleaned = f"{stem}{suffix}"
    return cleaned


def resolve_extension(filename: str) -> str:
    extension = PurePosixPath(filename).suffix.lower()
    if extension == ".markdown":
        return ".md"
    return extension


def guess_content_type(filename: str, provided: str | None) -> str:
    extension = resolve_extension(filename)
    if provided and provided != "application/octet-stream":
        return provided
    if extension in EXTENSION_CONTENT_TYPES:
        return EXTENSION_CONTENT_TYPES[extension]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def validate_upload(
    *,
    filename: str | None,
    content_type: str | None,
    size_bytes: int,
    settings: Settings,
) -> ValidatedUpload:
    """Validate filename, extension, and size against configured limits."""
    if not filename:
        raise ValidationError("Uploaded file must include a filename")

    safe_name = sanitize_filename(filename)
    extension = resolve_extension(safe_name)
    if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '{extension or '(none)'}'",
            details={
                "supported_extensions": sorted(SUPPORTED_DOCUMENT_EXTENSIONS),
            },
        )

    max_bytes = settings.max_upload_size_bytes
    if size_bytes <= 0:
        raise ValidationError("Uploaded file is empty")
    if size_bytes > max_bytes:
        raise ValidationError(
            f"File exceeds maximum size of {settings.max_upload_size_mb} MB",
            details={
                "size_bytes": size_bytes,
                "max_bytes": max_bytes,
            },
        )

    resolved_type = guess_content_type(safe_name, content_type)
    return ValidatedUpload(
        original_filename=filename,
        safe_filename=safe_name,
        extension=extension,
        content_type=resolved_type,
    )


def build_object_key(*, document_id: str, version: int, filename: str) -> str:
    """Stable MinIO object key for a document version."""
    safe = sanitize_filename(filename)
    return f"documents/{document_id}/v{version}/{safe}"
