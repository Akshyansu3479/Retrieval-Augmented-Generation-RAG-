"""Qdrant vector database client, collection management, and point ops."""

from __future__ import annotations

from typing import Annotated, Any, Sequence
from uuid import UUID

from fastapi import Depends
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_qdrant_client: QdrantClient | None = None


def init_qdrant(settings: Settings | None = None) -> QdrantClient:
    """Initialize the shared Qdrant client."""
    global _qdrant_client
    cfg = settings or get_settings()
    if _qdrant_client is None:
        kwargs: dict[str, Any] = {
            "url": cfg.qdrant_url,
            "timeout": 30,
        }
        if cfg.qdrant_api_key:
            kwargs["api_key"] = cfg.qdrant_api_key
        _qdrant_client = QdrantClient(**kwargs)
        logger.info("qdrant_initialized", url=cfg.qdrant_url)
    return _qdrant_client


def get_qdrant() -> QdrantClient:
    if _qdrant_client is None:
        raise RuntimeError("Qdrant client is not initialized")
    return _qdrant_client


def close_qdrant() -> None:
    global _qdrant_client
    if _qdrant_client is not None:
        _qdrant_client.close()
        logger.info("qdrant_closed")
    _qdrant_client = None


def ensure_collection(
    client: QdrantClient | None = None,
    settings: Settings | None = None,
) -> None:
    """
    Create the documents collection if missing.

    Vector size must match the configured embedding dimension.
    """
    cfg = settings or get_settings()
    qdrant = client or get_qdrant()
    collection = cfg.qdrant_collection
    dimension = cfg.embedding_dimension

    existing = {c.name for c in qdrant.get_collections().collections}
    if collection in existing:
        info = qdrant.get_collection(collection)
        vectors = info.config.params.vectors
        current_size: int | None = None
        if isinstance(vectors, qmodels.VectorParams):
            current_size = vectors.size
        elif isinstance(vectors, dict) and "" in vectors:
            current_size = vectors[""].size

        if current_size is not None and current_size != dimension:
            raise RuntimeError(
                f"Qdrant collection '{collection}' has vector size "
                f"{current_size}, but EMBEDDING_DIMENSION={dimension}. "
                "Recreate the collection or update the embedding config."
            )
        logger.info(
            "qdrant_collection_exists",
            collection=collection,
            vector_size=current_size or dimension,
        )
        return

    qdrant.create_collection(
        collection_name=collection,
        vectors_config=qmodels.VectorParams(
            size=dimension,
            distance=qmodels.Distance.COSINE,
        ),
        optimizers_config=qmodels.OptimizersConfigDiff(
            indexing_threshold=20000,
        ),
    )
    _ensure_payload_indexes(qdrant, collection)
    logger.info(
        "qdrant_collection_created",
        collection=collection,
        vector_size=dimension,
    )


def _ensure_payload_indexes(qdrant: QdrantClient, collection: str) -> None:
    for field_name, schema in (
        ("document_id", qmodels.PayloadSchemaType.KEYWORD),
        ("document_version_id", qmodels.PayloadSchemaType.KEYWORD),
        ("chunk_id", qmodels.PayloadSchemaType.KEYWORD),
        ("source_filename", qmodels.PayloadSchemaType.KEYWORD),
        ("page_number", qmodels.PayloadSchemaType.INTEGER),
        ("section_name", qmodels.PayloadSchemaType.KEYWORD),
        ("chunk_strategy", qmodels.PayloadSchemaType.KEYWORD),
    ):
        try:
            qdrant.create_payload_index(
                collection_name=collection,
                field_name=field_name,
                field_schema=schema,
            )
        except Exception:  # noqa: BLE001 — index may already exist
            pass


def upsert_points(
    points: Sequence[qmodels.PointStruct],
    *,
    client: QdrantClient | None = None,
    settings: Settings | None = None,
    wait: bool = True,
) -> None:
    """Batch upsert points into the configured collection."""
    if not points:
        return
    cfg = settings or get_settings()
    qdrant = client or get_qdrant()
    qdrant.upsert(
        collection_name=cfg.qdrant_collection,
        points=list(points),
        wait=wait,
    )
    logger.info(
        "qdrant_upserted",
        collection=cfg.qdrant_collection,
        count=len(points),
    )


def delete_by_document_id(
    document_id: str | UUID,
    *,
    client: QdrantClient | None = None,
    settings: Settings | None = None,
) -> None:
    """Delete all points belonging to a document."""
    cfg = settings or get_settings()
    qdrant = client or get_qdrant()
    qdrant.delete(
        collection_name=cfg.qdrant_collection,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="document_id",
                        match=qmodels.MatchValue(value=str(document_id)),
                    )
                ]
            )
        ),
        wait=True,
    )
    logger.info(
        "qdrant_deleted_document",
        collection=cfg.qdrant_collection,
        document_id=str(document_id),
    )


def delete_by_document_version_id(
    document_version_id: str | UUID,
    *,
    client: QdrantClient | None = None,
    settings: Settings | None = None,
) -> None:
    """Delete all points belonging to a document version."""
    cfg = settings or get_settings()
    qdrant = client or get_qdrant()
    qdrant.delete(
        collection_name=cfg.qdrant_collection,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="document_version_id",
                        match=qmodels.MatchValue(value=str(document_version_id)),
                    )
                ]
            )
        ),
        wait=True,
    )
    logger.info(
        "qdrant_deleted_document_version",
        collection=cfg.qdrant_collection,
        document_version_id=str(document_version_id),
    )


def delete_points(
    point_ids: Sequence[str | UUID],
    *,
    client: QdrantClient | None = None,
    settings: Settings | None = None,
) -> None:
    if not point_ids:
        return
    cfg = settings or get_settings()
    qdrant = client or get_qdrant()
    qdrant.delete(
        collection_name=cfg.qdrant_collection,
        points_selector=qmodels.PointIdsList(
            points=[str(pid) for pid in point_ids]
        ),
        wait=True,
    )


def similarity_search(
    query_vector: Sequence[float],
    *,
    limit: int | None = None,
    score_threshold: float | None = None,
    document_ids: Sequence[str] | None = None,
    filters: qmodels.Filter | None = None,
    client: QdrantClient | None = None,
    settings: Settings | None = None,
) -> list[qmodels.ScoredPoint]:
    """
    Similarity search with optional metadata filters.

    Used by Phase 8 verification and Phase 10 semantic retrieval.
    """
    cfg = settings or get_settings()
    qdrant = client or get_qdrant()
    top_k = limit or cfg.retrieval_top_k
    threshold = (
        score_threshold
        if score_threshold is not None
        else cfg.qdrant_score_threshold
    )

    must_conditions: list[qmodels.Condition] = []
    if document_ids:
        must_conditions.append(
            qmodels.FieldCondition(
                key="document_id",
                match=qmodels.MatchAny(any=list(document_ids)),
            )
        )
    query_filter = filters
    if must_conditions:
        extra = qmodels.Filter(must=must_conditions)
        if filters is None:
            query_filter = extra
        else:
            query_filter = qmodels.Filter(
                must=[*(filters.must or []), *must_conditions],
                should=filters.should,
                must_not=filters.must_not,
            )

    return qdrant.search(
        collection_name=cfg.qdrant_collection,
        query_vector=list(query_vector),
        limit=top_k,
        score_threshold=threshold if threshold > 0 else None,
        query_filter=query_filter,
        with_payload=True,
        search_params=qmodels.SearchParams(
            hnsw_ef=cfg.qdrant_hnsw_ef,
            exact=cfg.qdrant_exact_search,
        ),
    )


def count_points_for_document(
    document_id: str | UUID,
    *,
    client: QdrantClient | None = None,
    settings: Settings | None = None,
) -> int:
    cfg = settings or get_settings()
    qdrant = client or get_qdrant()
    result = qdrant.count(
        collection_name=cfg.qdrant_collection,
        count_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="document_id",
                    match=qmodels.MatchValue(value=str(document_id)),
                )
            ]
        ),
        exact=True,
    )
    return int(result.count)


def check_qdrant() -> None:
    client = get_qdrant()
    client.get_collections()


QdrantDep = Annotated[QdrantClient, Depends(get_qdrant)]
