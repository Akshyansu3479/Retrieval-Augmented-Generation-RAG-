"""initial schema

Revision ID: 20261031_0001
Revises:
Create Date: 2026-10-31 16:50:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261031_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("source_uri", sa.String(length=1024), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_documents_checksum_sha256"),
        "documents",
        ["checksum_sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_documents_status"),
        "documents",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_documents_status_created_at",
        "documents",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("parser_name", sa.String(length=128), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_versions_document_version",
        ),
    )
    op.create_index(
        op.f("ix_document_versions_checksum_sha256"),
        "document_versions",
        ["checksum_sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_versions_document_id"),
        "document_versions",
        ["document_id"],
        unique=False,
    )

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_messages_conversation_id"),
        "messages",
        ["conversation_id"],
        unique=False,
    )

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_name", sa.String(length=512), nullable=True),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("parent_chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column("embedding_version", sa.String(length=64), nullable=True),
        sa.Column("chunk_strategy", sa.String(length=64), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_chunk_id"],
            ["chunks.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_chunks_version_index",
        ),
        sa.UniqueConstraint("qdrant_point_id"),
    )
    op.create_index(
        op.f("ix_chunks_content_hash"),
        "chunks",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chunks_document_id"),
        "chunks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chunks_document_version_id"),
        "chunks",
        ["document_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chunks_parent_chunk_id"),
        "chunks",
        ["parent_chunk_id"],
        unique=False,
    )
    op.create_index(
        "ix_chunks_document_version_page",
        "chunks",
        ["document_id", "page_number"],
        unique=False,
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("progress_pct", sa.Float(), nullable=False),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        op.f("ix_ingestion_jobs_celery_task_id"),
        "ingestion_jobs",
        ["celery_task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ingestion_jobs_document_id"),
        "ingestion_jobs",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ingestion_jobs_document_version_id"),
        "ingestion_jobs",
        ["document_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ingestion_jobs_status"),
        "ingestion_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_ingestion_jobs_status_created_at",
        "ingestion_jobs",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_feedback_message_id"),
        "feedback",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        "ix_feedback_message_rating",
        "feedback",
        ["message_id", "rating"],
        unique=False,
    )

    op.create_table(
        "citations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("source_filename", sa.String(length=512), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["chunks.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_citations_chunk_id"),
        "citations",
        ["chunk_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_citations_document_id"),
        "citations",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_citations_message_id"),
        "citations",
        ["message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_citations_message_id"), table_name="citations")
    op.drop_index(op.f("ix_citations_document_id"), table_name="citations")
    op.drop_index(op.f("ix_citations_chunk_id"), table_name="citations")
    op.drop_table("citations")

    op.drop_index("ix_feedback_message_rating", table_name="feedback")
    op.drop_index(op.f("ix_feedback_message_id"), table_name="feedback")
    op.drop_table("feedback")

    op.drop_index("ix_ingestion_jobs_status_created_at", table_name="ingestion_jobs")
    op.drop_index(op.f("ix_ingestion_jobs_status"), table_name="ingestion_jobs")
    op.drop_index(
        op.f("ix_ingestion_jobs_document_version_id"),
        table_name="ingestion_jobs",
    )
    op.drop_index(op.f("ix_ingestion_jobs_document_id"), table_name="ingestion_jobs")
    op.drop_index(op.f("ix_ingestion_jobs_celery_task_id"), table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")

    op.drop_index("ix_chunks_document_version_page", table_name="chunks")
    op.drop_index(op.f("ix_chunks_parent_chunk_id"), table_name="chunks")
    op.drop_index(op.f("ix_chunks_document_version_id"), table_name="chunks")
    op.drop_index(op.f("ix_chunks_document_id"), table_name="chunks")
    op.drop_index(op.f("ix_chunks_content_hash"), table_name="chunks")
    op.drop_table("chunks")

    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_table("messages")

    op.drop_index(
        op.f("ix_document_versions_document_id"),
        table_name="document_versions",
    )
    op.drop_index(
        op.f("ix_document_versions_checksum_sha256"),
        table_name="document_versions",
    )
    op.drop_table("document_versions")

    op.drop_table("conversations")

    op.drop_index("ix_documents_status_created_at", table_name="documents")
    op.drop_index(op.f("ix_documents_status"), table_name="documents")
    op.drop_index(op.f("ix_documents_checksum_sha256"), table_name="documents")
    op.drop_table("documents")
