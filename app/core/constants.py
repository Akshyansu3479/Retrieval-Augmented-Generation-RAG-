"""Shared application constants."""

from enum import StrEnum

API_V1_PREFIX = "/api/v1"

SUPPORTED_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".xlsx",
        ".csv",
        ".pptx",
        ".txt",
        ".md",
        ".markdown",
        ".html",
        ".htm",
    }
)

HEALTH_STATUS_OK = "ok"
HEALTH_STATUS_DEGRADED = "degraded"
HEALTH_STATUS_UNAVAILABLE = "unavailable"

SERVICE_POSTGRES = "postgres"
SERVICE_REDIS = "redis"
SERVICE_QDRANT = "qdrant"
SERVICE_MINIO = "minio"
SERVICE_OLLAMA = "ollama"


class DocumentStatus(StrEnum):
    """Lifecycle status for a document record."""

    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"
    DELETED = "deleted"


class IngestionJobStatus(StrEnum):
    """Background ingestion job status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MessageRole(StrEnum):
    """Chat message roles."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class FeedbackRating(StrEnum):
    """User feedback ratings for generated answers."""

    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
