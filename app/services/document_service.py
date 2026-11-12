"""Document upload, listing, retrieval, and deletion service."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.core.constants import DocumentStatus
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.database.models import Document, DocumentVersion
from app.ingestion.validation import build_object_key, validate_upload
from app.storage import file_storage

logger = get_logger(__name__)

# Read uploads in chunks to bound memory usage while hashing.
_READ_CHUNK_SIZE = 1024 * 1024


class DocumentService:
    """Business logic for document storage metadata and object storage."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def upload(
        self,
        upload: UploadFile,
        *,
        document_id: UUID | None = None,
        allow_duplicate: bool = False,
    ) -> Document:
        """
        Validate, store, and register an uploaded file.

        - New upload creates a Document + version 1.
        - Providing ``document_id`` appends a new version.
        - Identical checksum of an active document raises ConflictError
          unless ``allow_duplicate`` is true or uploading a new version.
        """
        data, size_bytes, checksum = await self._read_and_hash(upload)
        validated = validate_upload(
            filename=upload.filename,
            content_type=upload.content_type,
            size_bytes=size_bytes,
            settings=self.settings,
        )

        if document_id is None and not allow_duplicate:
            existing = await self._find_active_by_checksum(checksum)
            if existing is not None:
                raise ConflictError(
                    "Duplicate document detected (matching SHA-256 checksum)",
                    details={
                        "checksum_sha256": checksum,
                        "existing_document_id": str(existing.id),
                        "existing_filename": existing.filename,
                        "existing_status": existing.status,
                    },
                )

        if document_id is not None:
            document = await self.get_document(document_id, include_versions=True)
            next_version = document.current_version + 1
        else:
            document = Document(
                id=uuid4(),
                filename=validated.safe_filename,
                content_type=validated.content_type,
                checksum_sha256=checksum,
                status=DocumentStatus.UPLOADED.value,
                current_version=1,
                meta={
                    "original_filename": validated.original_filename,
                    "extension": validated.extension,
                },
            )
            self.session.add(document)
            await self.session.flush()
            next_version = 1

        object_key = build_object_key(
            document_id=str(document.id),
            version=next_version,
            filename=validated.safe_filename,
        )

        try:
            file_storage.upload_bytes(
                object_key=object_key,
                data=data,
                content_type=validated.content_type,
                settings=self.settings,
            )
        except Exception:
            logger.exception(
                "minio_upload_failed",
                document_id=str(document.id),
                object_key=object_key,
            )
            raise

        version = DocumentVersion(
            id=uuid4(),
            document_id=document.id,
            version_number=next_version,
            object_key=object_key,
            bucket=self.settings.minio_bucket,
            filename=validated.safe_filename,
            content_type=validated.content_type,
            size_bytes=size_bytes,
            checksum_sha256=checksum,
            meta={
                "original_filename": validated.original_filename,
                "extension": validated.extension,
            },
        )
        self.session.add(version)

        document.filename = validated.safe_filename
        document.content_type = validated.content_type
        document.checksum_sha256 = checksum
        document.current_version = next_version
        document.status = DocumentStatus.UPLOADED.value
        document.source_uri = (
            f"s3://{self.settings.minio_bucket}/{object_key}"
        )
        document.deleted_at = None

        await self.session.commit()
        await self.session.refresh(document)

        # Reload with versions for response serialization.
        return await self.get_document(document.id, include_versions=True)

    async def list_documents(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> tuple[list[Document], int]:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        filters = []
        if not include_deleted:
            filters.append(Document.deleted_at.is_(None))
            filters.append(Document.status != DocumentStatus.DELETED.value)

        count_stmt = select(func.count()).select_from(Document)
        list_stmt = (
            select(Document)
            .options(selectinload(Document.versions))
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if filters:
            count_stmt = count_stmt.where(*filters)
            list_stmt = list_stmt.where(*filters)

        total = int((await self.session.execute(count_stmt)).scalar_one())
        rows = list((await self.session.execute(list_stmt)).scalars().all())
        return rows, total

    async def get_document(
        self,
        document_id: UUID,
        *,
        include_versions: bool = True,
        include_deleted: bool = False,
    ) -> Document:
        stmt = select(Document).where(Document.id == document_id)
        if include_versions:
            stmt = stmt.options(selectinload(Document.versions))

        document = (await self.session.execute(stmt)).scalar_one_or_none()
        if document is None:
            raise NotFoundError(
                f"Document '{document_id}' not found",
                details={"document_id": str(document_id)},
            )
        if (
            not include_deleted
            and (
                document.deleted_at is not None
                or document.status == DocumentStatus.DELETED.value
            )
        ):
            raise NotFoundError(
                f"Document '{document_id}' not found",
                details={"document_id": str(document_id)},
            )
        return document

    async def delete_document(
        self,
        document_id: UUID,
        *,
        purge_objects: bool = False,
    ) -> Document:
        """
        Soft-delete a document.

        When ``purge_objects`` is true, also remove version objects from MinIO.
        """
        document = await self.get_document(
            document_id,
            include_versions=True,
            include_deleted=False,
        )

        if purge_objects:
            for version in document.versions:
                try:
                    file_storage.delete_object(
                        version.object_key,
                        settings=self.settings,
                    )
                except Exception:
                    logger.exception(
                        "minio_delete_failed",
                        document_id=str(document.id),
                        object_key=version.object_key,
                    )

        try:
            from app.database import qdrant as qdrant_store

            qdrant_store.delete_by_document_id(
                document.id,
                settings=self.settings,
            )
        except Exception:
            logger.exception(
                "qdrant_delete_failed",
                document_id=str(document.id),
            )

        now = datetime.now(UTC)
        document.status = DocumentStatus.DELETED.value
        document.deleted_at = now
        await self.session.commit()
        await self.session.refresh(document)

        logger.info(
            "document_deleted",
            document_id=str(document.id),
            purge_objects=purge_objects,
        )
        return document

    async def _find_active_by_checksum(self, checksum: str) -> Document | None:
        stmt = (
            select(Document)
            .where(
                Document.checksum_sha256 == checksum,
                Document.deleted_at.is_(None),
                Document.status != DocumentStatus.DELETED.value,
            )
            .order_by(Document.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _read_and_hash(
        self,
        upload: UploadFile,
    ) -> tuple[bytes, int, str]:
        """Read upload stream with size enforcement and SHA-256 hashing."""
        max_bytes = self.settings.max_upload_size_bytes
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        total = 0

        while True:
            chunk = await upload.read(_READ_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValidationError(
                    f"File exceeds maximum size of "
                    f"{self.settings.max_upload_size_mb} MB",
                    details={
                        "size_bytes": total,
                        "max_bytes": max_bytes,
                    },
                )
            digest.update(chunk)
            chunks.append(chunk)

        await upload.close()
        data = b"".join(chunks)
        return data, total, digest.hexdigest()
