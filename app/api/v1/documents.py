"""Document upload and management endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.config import Settings, get_settings
from app.database.postgres import DbSession
from app.schemas.document import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentResponse,
)
from app.schemas.chunk import ChunkDocumentResponse, ChunkListResponse
from app.schemas.embedding import EmbedDocumentResponse, EmbeddingStatusResponse
from app.schemas.indexing import (
    IndexDeleteResponse,
    IndexDocumentResponse,
    IndexSearchResponse,
    IndexStatusResponse,
)
from app.schemas.parse import ParseDocumentResponse
from app.services.chunk_service import ChunkService
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.indexing_service import IndexingService
from app.services.parse_service import ParseService

router = APIRouter(prefix="/documents", tags=["documents"])


def get_document_service(
    session: DbSession,
    settings: Settings = Depends(get_settings),
) -> DocumentService:
    return DocumentService(session=session, settings=settings)


def get_parse_service(
    session: DbSession,
    settings: Settings = Depends(get_settings),
) -> ParseService:
    return ParseService(session=session, settings=settings)


def get_chunk_service(
    session: DbSession,
    settings: Settings = Depends(get_settings),
) -> ChunkService:
    return ChunkService(session=session, settings=settings)


def get_embedding_service(
    session: DbSession,
    settings: Settings = Depends(get_settings),
) -> EmbeddingService:
    return EmbeddingService(session=session, settings=settings)


def get_indexing_service(
    session: DbSession,
    settings: Settings = Depends(get_settings),
) -> IndexingService:
    return IndexingService(session=session, settings=settings)


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document to object storage",
)
async def upload_document(
    file: UploadFile = File(..., description="Document file to ingest"),
    document_id: UUID | None = Query(
        default=None,
        description="Optional existing document ID to create a new version",
    ),
    allow_duplicate: bool = Query(
        default=False,
        description="Allow upload even when SHA-256 matches an existing document",
    ),
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    document = await service.upload(
        file,
        document_id=document_id,
        allow_duplicate=allow_duplicate,
    )
    return DocumentResponse.model_validate(document)


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List uploaded documents",
)
async def list_documents(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    include_deleted: bool = Query(default=False),
    service: DocumentService = Depends(get_document_service),
) -> DocumentListResponse:
    items, total = await service.list_documents(
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
    )
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get a document by ID",
)
async def get_document(
    document_id: UUID,
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    document = await service.get_document(document_id, include_versions=True)
    return DocumentResponse.model_validate(document)


@router.post(
    "/{document_id}/parse",
    response_model=ParseDocumentResponse,
    summary="Parse a document version (text, tables, metadata)",
)
async def parse_document(
    document_id: UUID,
    version_number: int | None = Query(
        default=None,
        ge=1,
        description="Specific version to parse (defaults to latest)",
    ),
    include_full_text: bool = Query(
        default=True,
        description="Include full extracted text in the response",
    ),
    persist: bool = Query(
        default=True,
        description="Persist extraction summary onto the document version",
    ),
    clean: bool | None = Query(
        default=None,
        description="Override CLEANER_ENABLED for this request",
    ),
    enrich_metadata: bool | None = Query(
        default=None,
        description="Override METADATA_ENRICHMENT_ENABLED for this request",
    ),
    service: ParseService = Depends(get_parse_service),
) -> ParseDocumentResponse:
    return await service.parse_document(
        document_id,
        version_number=version_number,
        include_full_text=include_full_text,
        persist=persist,
        clean=clean,
        enrich_metadata=enrich_metadata,
    )


@router.post(
    "/{document_id}/chunk",
    response_model=ChunkDocumentResponse,
    summary="Chunk a parsed document version",
)
async def chunk_document(
    document_id: UUID,
    version_number: int | None = Query(default=None, ge=1),
    strategy: str | None = Query(
        default=None,
        description=(
            "recursive|token|sentence|heading|semantic|table_aware|parent_child"
        ),
    ),
    chunk_size: int | None = Query(default=None, ge=32, le=8192),
    chunk_overlap: int | None = Query(default=None, ge=0, le=4096),
    replace_existing: bool = Query(default=True),
    reparse: bool = Query(
        default=False,
        description="Force re-parse from MinIO instead of stored extraction",
    ),
    service: ChunkService = Depends(get_chunk_service),
) -> ChunkDocumentResponse:
    return await service.chunk_document(
        document_id,
        version_number=version_number,
        strategy=strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        replace_existing=replace_existing,
        reparse=reparse,
    )


@router.get(
    "/{document_id}/chunks",
    response_model=ChunkListResponse,
    summary="List persisted chunks for a document version",
)
async def list_document_chunks(
    document_id: UUID,
    version_number: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: ChunkService = Depends(get_chunk_service),
) -> ChunkListResponse:
    return await service.list_chunks(
        document_id,
        version_number=version_number,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{document_id}/embed",
    response_model=EmbedDocumentResponse,
    summary="Generate embeddings for document chunks",
)
async def embed_document(
    document_id: UUID,
    version_number: int | None = Query(default=None, ge=1),
    force: bool = Query(
        default=False,
        description="Re-embed even when cached vectors already exist",
    ),
    service: EmbeddingService = Depends(get_embedding_service),
) -> EmbedDocumentResponse:
    return await service.embed_document(
        document_id,
        version_number=version_number,
        force=force,
    )


@router.get(
    "/{document_id}/embeddings/status",
    response_model=EmbeddingStatusResponse,
    summary="Embedding readiness status for a document version",
)
async def embedding_status(
    document_id: UUID,
    version_number: int | None = Query(default=None, ge=1),
    service: EmbeddingService = Depends(get_embedding_service),
) -> EmbeddingStatusResponse:
    return await service.get_status(
        document_id,
        version_number=version_number,
    )


@router.post(
    "/{document_id}/index",
    response_model=IndexDocumentResponse,
    summary="Upsert chunk embeddings into Qdrant",
)
async def index_document(
    document_id: UUID,
    version_number: int | None = Query(default=None, ge=1),
    replace_existing: bool = Query(default=True),
    ensure_embeddings: bool = Query(
        default=True,
        description="Automatically embed missing chunks before indexing",
    ),
    service: IndexingService = Depends(get_indexing_service),
) -> IndexDocumentResponse:
    return await service.index_document(
        document_id,
        version_number=version_number,
        replace_existing=replace_existing,
        ensure_embeddings=ensure_embeddings,
    )


@router.get(
    "/{document_id}/index/status",
    response_model=IndexStatusResponse,
    summary="Qdrant indexing status for a document version",
)
async def index_status(
    document_id: UUID,
    version_number: int | None = Query(default=None, ge=1),
    service: IndexingService = Depends(get_indexing_service),
) -> IndexStatusResponse:
    return await service.get_status(
        document_id,
        version_number=version_number,
    )


@router.delete(
    "/{document_id}/index",
    response_model=IndexDeleteResponse,
    summary="Remove document vectors from Qdrant",
)
async def delete_document_index(
    document_id: UUID,
    version_number: int | None = Query(default=None, ge=1),
    service: IndexingService = Depends(get_indexing_service),
) -> IndexDeleteResponse:
    return await service.delete_index(
        document_id,
        version_number=version_number,
    )


@router.post(
    "/{document_id}/search",
    response_model=IndexSearchResponse,
    summary="Semantic search within an indexed document (Phase 8 helper)",
)
async def search_document(
    document_id: UUID,
    query: str = Query(..., min_length=1),
    limit: int = Query(default=5, ge=1, le=50),
    service: IndexingService = Depends(get_indexing_service),
) -> IndexSearchResponse:
    return await service.search(
        query,
        document_id=document_id,
        limit=limit,
    )


@router.delete(
    "/{document_id}",
    response_model=DocumentDeleteResponse,
    summary="Soft-delete a document",
)
async def delete_document(
    document_id: UUID,
    purge_objects: bool = Query(
        default=False,
        description="Also delete version binaries from MinIO",
    ),
    service: DocumentService = Depends(get_document_service),
) -> DocumentDeleteResponse:
    document = await service.delete_document(
        document_id,
        purge_objects=purge_objects,
    )
    assert document.deleted_at is not None
    return DocumentDeleteResponse(
        id=document.id,
        status=document.status,
        deleted_at=document.deleted_at,
    )
