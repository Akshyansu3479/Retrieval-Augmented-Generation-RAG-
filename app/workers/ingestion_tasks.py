"""Celery tasks for asynchronous document ingestion."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from celery import shared_task

from app.core.constants import DocumentStatus, IngestionJobStatus
from app.core.logging import get_logger
from app.database.models import Document, IngestionJob
from app.database.postgres import get_session_factory
from app.ingestion.pipeline import IngestionPipeline
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.ingestion_tasks.ingest_document_task",
    max_retries=3,
    default_retry_delay=15,
    autoretry_for=(),
    acks_late=True,
)
def ingest_document_task(self, job_id: str) -> dict:
    """Run parse → chunk → embed → index for an ingestion job."""
    return run_async(_ingest_document(UUID(job_id), celery_task_id=self.request.id))


async def _ingest_document(job_id: UUID, *, celery_task_id: str | None) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(IngestionJob, job_id)
        if job is None:
            logger.error("ingestion_job_missing", job_id=str(job_id))
            return {"ok": False, "error": "job_not_found"}

        if job.status == IngestionJobStatus.SUCCEEDED.value:
            return {"ok": True, "status": "already_succeeded", "job_id": str(job_id)}

        document = await session.get(Document, job.document_id)
        job.status = IngestionJobStatus.RUNNING.value
        job.started_at = datetime.now(UTC)
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.celery_task_id = celery_task_id or job.celery_task_id
        job.error_message = None
        job.progress_pct = 1.0
        if document is not None:
            document.status = DocumentStatus.PROCESSING.value
        await session.commit()

        async def progress_callback(pct: float, stage: str) -> None:
            job.progress_pct = float(pct)
            meta = dict(job.meta or {})
            meta["stage"] = stage
            job.meta = meta
            await session.commit()

        try:
            pipeline = IngestionPipeline(session=session)
            result = await pipeline.run(
                job.document_id,
                progress_callback=progress_callback,
            )
            job.status = IngestionJobStatus.SUCCEEDED.value
            job.progress_pct = 100.0
            job.finished_at = datetime.now(UTC)
            job.meta = {
                **(job.meta or {}),
                "stages": result.stages,
                "document_version_id": str(result.document_version_id),
            }
            # Re-load document in case status was set by indexing service.
            document = await session.get(Document, job.document_id)
            if document is not None:
                document.status = DocumentStatus.INDEXED.value
            await session.commit()
            return {
                "ok": True,
                "job_id": str(job_id),
                "document_id": str(result.document_id),
                "stages": result.stages,
            }
        except Exception as exc:  # noqa: BLE001 — persist failure on job
            logger.exception("ingestion_job_failed", job_id=str(job_id))
            job.status = IngestionJobStatus.FAILED.value
            job.error_message = str(exc)[:4000]
            job.finished_at = datetime.now(UTC)
            meta = dict(job.meta or {})
            meta["failed_stage"] = meta.get("stage")
            job.meta = meta
            document = await session.get(Document, job.document_id)
            if document is not None:
                document.status = DocumentStatus.FAILED.value
            await session.commit()
            raise


@shared_task(name="app.workers.ingestion_tasks.ping")
def ping() -> str:
    return "pong"
