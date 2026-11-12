"""Async ingestion enqueue and status endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.database.postgres import DbSession
from app.schemas.ingestion import IngestionEnqueueResponse, IngestionJobResponse
from app.services.ingestion_service import IngestionService

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


def get_ingestion_service(
    session: DbSession,
    settings: Settings = Depends(get_settings),
) -> IngestionService:
    return IngestionService(session=session, settings=settings)


@router.post(
    "/{document_id}",
    response_model=IngestionEnqueueResponse,
    summary="Enqueue full document ingestion (parse→chunk→embed→index)",
)
async def enqueue_ingestion(
    document_id: UUID,
    version_number: int | None = Query(default=None, ge=1),
    force: bool = Query(
        default=False,
        description="Force a new job even if one already succeeded",
    ),
    service: IngestionService = Depends(get_ingestion_service),
) -> IngestionEnqueueResponse:
    return await service.enqueue(
        document_id,
        version_number=version_number,
        force=force,
    )


@router.get(
    "/{document_id}/status",
    response_model=IngestionJobResponse,
    summary="Latest (or specific) ingestion job status for a document",
)
async def ingestion_status(
    document_id: UUID,
    job_id: UUID | None = Query(default=None),
    service: IngestionService = Depends(get_ingestion_service),
) -> IngestionJobResponse:
    return await service.get_status(document_id, job_id=job_id)


@router.get(
    "/jobs/{job_id}",
    response_model=IngestionJobResponse,
    summary="Get ingestion job by id",
)
async def get_ingestion_job(
    job_id: UUID,
    service: IngestionService = Depends(get_ingestion_service),
) -> IngestionJobResponse:
    return await service.get_job(job_id)
