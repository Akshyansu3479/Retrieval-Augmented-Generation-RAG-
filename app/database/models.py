"""SQLAlchemy 2.0 ORM models for application metadata."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import (
    DocumentStatus,
    FeedbackRating,
    IngestionJobStatus,
    MessageRole,
)
from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Logical document identity (may have multiple versions)."""

    __tablename__ = "documents"

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255))
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DocumentStatus.UPLOADED.value,
        index=True,
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_uri: Mapped[str | None] = mapped_column(String(1024))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number",
    )
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
    ingestion_jobs: Mapped[list[IngestionJob]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_documents_status_created_at", "status", "created_at"),
    )


class DocumentVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Immutable snapshot of an uploaded document binary."""

    __tablename__ = "document_versions"

    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    parser_name: Mapped[str | None] = mapped_column(String(128))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    document: Mapped[Document] = relationship(back_populates="versions")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="version")
    ingestion_jobs: Mapped[list[IngestionJob]] = relationship(
        back_populates="document_version"
    )

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_versions_document_version",
        ),
    )


class Chunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Chunk metadata stored in PostgreSQL (vectors live in Qdrant)."""

    __tablename__ = "chunks"

    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    token_count: Mapped[int | None] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_name: Mapped[str | None] = mapped_column(String(512))
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_chunk_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="SET NULL"),
        index=True,
    )
    qdrant_point_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        unique=True,
    )
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    embedding_version: Mapped[str | None] = mapped_column(String(64))
    chunk_strategy: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    document: Mapped[Document] = relationship(back_populates="chunks")
    version: Mapped[DocumentVersion] = relationship(back_populates="chunks")
    parent: Mapped[Chunk | None] = relationship(
        remote_side="Chunk.id",
        foreign_keys=[parent_chunk_id],
    )
    citations: Mapped[list[Citation]] = relationship(back_populates="chunk")

    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_chunks_version_index",
        ),
        Index("ix_chunks_document_version_page", "document_id", "page_number"),
    )


class IngestionJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tracks asynchronous document ingestion work."""

    __tablename__ = "ingestion_jobs"

    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=IngestionJobStatus.PENDING.value,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    progress_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    document: Mapped[Document] = relationship(back_populates="ingestion_jobs")
    document_version: Mapped[DocumentVersion] = relationship(
        back_populates="ingestion_jobs"
    )

    __table_args__ = (
        Index("ix_ingestion_jobs_status_created_at", "status", "created_at"),
    )


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Chat conversation container."""

    __tablename__ = "conversations"

    title: Mapped[str | None] = mapped_column(String(512))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Single message within a conversation."""

    __tablename__ = "messages"

    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=MessageRole.USER.value)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(255))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    citations: Mapped[list[Citation]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )
    feedback: Mapped[list[Feedback]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )


class Citation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Source citation attached to an assistant message."""

    __tablename__ = "citations"

    message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="SET NULL"),
        index=True,
    )
    document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    score: Mapped[float | None] = mapped_column(Float)
    snippet: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    source_filename: Mapped[str | None] = mapped_column(String(512))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    message: Mapped[Message] = relationship(back_populates="citations")
    chunk: Mapped[Chunk | None] = relationship(back_populates="citations")


class Feedback(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """User feedback on an assistant message."""

    __tablename__ = "feedback"

    message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=FeedbackRating.THUMBS_UP.value,
    )
    comment: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    message: Mapped[Message] = relationship(back_populates="feedback")

    __table_args__ = (
        Index("ix_feedback_message_rating", "message_id", "rating"),
    )
