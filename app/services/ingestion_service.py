"""Enqueue and track Celery ingestion jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.core.constants import DocumentStatus, IngestionJobStatus
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.database.models import Document, DocumentVersion, IngestionJob
from app.schemas.ingestion import IngestionEnqueueResponse, IngestionJobResponse

logger = get_logger(__name__)


class IngestionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def enqueue(
        self,
        document_id: UUID,
        *,
        version_number: int | None = None,
        force: bool = False,
    ) -> IngestionEnqueueResponse:
        document, version = await self._get_document_and_version(
            document_id,
            version_number=version_number,
        )
        idempotency_key = f"{document.id}:{version.id}:v{version.version_number}"

        existing = await self._get_job_by_idempotency(idempotency_key)
        if existing is not None and not force:
            if existing.status in {
                IngestionJobStatus.PENDING.value,
                IngestionJobStatus.RUNNING.value,
                IngestionJobStatus.SUCCEEDED.value,
            }:
                return IngestionEnqueueResponse(
                    job_id=existing.id,
                    document_id=document.id,
                    document_version_id=version.id,
                    status=existing.status,
                    celery_task_id=existing.celery_task_id,
                    idempotency_key=existing.idempotency_key,
                    message="Existing ingestion job reused (idempotent)",
                )

        if force and existing is not None:
            # New key suffix so UniqueConstraint allows a fresh row.
            idempotency_key = (
                f"{idempotency_key}:retry:{int(datetime.now(UTC).timestamp())}"
            )

        job = IngestionJob(
            document_id=document.id,
            document_version_id=version.id,
            status=IngestionJobStatus.PENDING.value,
            idempotency_key=idempotency_key,
            attempt_count=0,
            progress_pct=0.0,
            meta={"force": force},
        )
        self.session.add(job)
        document.status = DocumentStatus.QUEUED.value
        await self.session.commit()
        await self.session.refresh(job)

        from app.workers.ingestion_tasks import ingest_document_task

        async_result = ingest_document_task.delay(str(job.id))
        job.celery_task_id = async_result.id
        await self.session.commit()
        await self.session.refresh(job)

        logger.info(
            "ingestion_enqueued",
            job_id=str(job.id),
            document_id=str(document.id),
            celery_task_id=job.celery_task_id,
        )
        return IngestionEnqueueResponse(
            job_id=job.id,
            document_id=document.id,
            document_version_id=version.id,
            status=job.status,
            celery_task_id=job.celery_task_id,
            idempotency_key=job.idempotency_key,
        )

    async def get_status(
        self,
        document_id: UUID,
        *,
        job_id: UUID | None = None,
    ) -> IngestionJobResponse:
        await self._require_document(document_id)
        if job_id is not None:
            job = await self.session.get(IngestionJob, job_id)
            if job is None or job.document_id != document_id:
                raise NotFoundError(
                    f"Ingestion job '{job_id}' not found",
                    details={"job_id": str(job_id)},
                )
            return IngestionJobResponse.model_validate(job)

        stmt = (
            select(IngestionJob)
            .where(IngestionJob.document_id == document_id)
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
        )
        job = (await self.session.execute(stmt)).scalar_one_or_none()
        if job is None:
            raise NotFoundError(
                f"No ingestion jobs for document '{document_id}'",
                details={"document_id": str(document_id)},
            )
        return IngestionJobResponse.model_validate(job)

    async def get_job(self, job_id: UUID) -> IngestionJobResponse:
        job = await self.session.get(IngestionJob, job_id)
        if job is None:
            raise NotFoundError(
                f"Ingestion job '{job_id}' not found",
                details={"job_id": str(job_id)},
            )
        return IngestionJobResponse.model_validate(job)

    async def _require_document(self, document_id: UUID) -> Document:
        document = await self.session.get(Document, document_id)
        if document is None or document.deleted_at is not None:
            raise NotFoundError(
                f"Document '{document_id}' not found",
                details={"document_id": str(document_id)},
            )
        return document

    async def _get_document_and_version(
        self,
        document_id: UUID,
        *,
        version_number: int | None,
    ) -> tuple[Document, DocumentVersion]:
        stmt = (
            select(Document)
            .where(Document.id == document_id)
            .options(selectinload(Document.versions))
        )
        document = (await self.session.execute(stmt)).scalar_one_or_none()
        if document is None or document.deleted_at is not None:
            raise NotFoundError(
                f"Document '{document_id}' not found",
                details={"document_id": str(document_id)},
            )
        if not document.versions:
            raise ValidationError("Document has no versions")
        if version_number is None:
            version = max(document.versions, key=lambda item: item.version_number)
        else:
            version = next(
                (
                    item
                    for item in document.versions
                    if item.version_number == version_number
                ),
                None,
            )
            if version is None:
                raise NotFoundError(
                    f"Version {version_number} not found for document '{document_id}'"
                )
        return document, version

    async def _get_job_by_idempotency(self, key: str) -> IngestionJob | None:
        stmt = select(IngestionJob).where(IngestionJob.idempotency_key == key)
        return (await self.session.execute(stmt)).scalar_one_or_none()
