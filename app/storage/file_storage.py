"""MinIO object storage client for original documents."""

from __future__ import annotations

from io import BytesIO
from typing import Annotated, BinaryIO

from fastapi import Depends
from minio import Minio
from minio.error import S3Error

from app.config import Settings, get_settings
from app.core.exceptions import ServiceUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

_minio_client: Minio | None = None


def init_minio(settings: Settings | None = None) -> Minio:
    """Initialize the shared MinIO client."""
    global _minio_client
    cfg = settings or get_settings()
    if _minio_client is None:
        _minio_client = Minio(
            cfg.minio_endpoint,
            access_key=cfg.minio_access_key,
            secret_key=cfg.minio_secret_key,
            secure=cfg.minio_secure,
        )
        logger.info("minio_initialized", endpoint=cfg.minio_endpoint)
    return _minio_client


def get_minio() -> Minio:
    if _minio_client is None:
        raise RuntimeError("MinIO client is not initialized")
    return _minio_client


def close_minio() -> None:
    """MinIO client has no persistent connection to close."""
    global _minio_client
    _minio_client = None
    logger.info("minio_closed")


def ensure_bucket(
    client: Minio | None = None,
    settings: Settings | None = None,
) -> None:
    """Create the configured bucket when missing."""
    cfg = settings or get_settings()
    minio = client or get_minio()
    bucket = cfg.minio_bucket
    try:
        if not minio.bucket_exists(bucket):
            minio.make_bucket(bucket)
            logger.info("minio_bucket_created", bucket=bucket)
        else:
            logger.info("minio_bucket_exists", bucket=bucket)
    except S3Error as exc:
        raise ServiceUnavailableError(
            "minio",
            f"Failed to ensure bucket '{bucket}': {exc}",
        ) from exc


def check_minio() -> None:
    client = get_minio()
    settings = get_settings()
    # list_buckets requires credentials and validates reachability.
    _ = client.bucket_exists(settings.minio_bucket)


def upload_bytes(
    *,
    object_key: str,
    data: bytes,
    content_type: str | None = None,
    client: Minio | None = None,
    settings: Settings | None = None,
) -> str:
    """Upload raw bytes and return the object key."""
    cfg = settings or get_settings()
    minio = client or get_minio()
    stream = BytesIO(data)
    minio.put_object(
        bucket_name=cfg.minio_bucket,
        object_name=object_key,
        data=stream,
        length=len(data),
        content_type=content_type or "application/octet-stream",
    )
    return object_key


def upload_fileobj(
    *,
    object_key: str,
    fileobj: BinaryIO,
    length: int,
    content_type: str | None = None,
    client: Minio | None = None,
    settings: Settings | None = None,
) -> str:
    """Upload a file-like object and return the object key."""
    cfg = settings or get_settings()
    minio = client or get_minio()
    minio.put_object(
        bucket_name=cfg.minio_bucket,
        object_name=object_key,
        data=fileobj,
        length=length,
        content_type=content_type or "application/octet-stream",
    )
    return object_key


def download_bytes(
    object_key: str,
    *,
    client: Minio | None = None,
    settings: Settings | None = None,
) -> bytes:
    """Download an object and return its raw bytes."""
    cfg = settings or get_settings()
    minio = client or get_minio()
    try:
        response = minio.get_object(cfg.minio_bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
    except S3Error as exc:
        raise ServiceUnavailableError(
            "minio",
            f"Failed to download object '{object_key}': {exc}",
        ) from exc


def delete_object(
    object_key: str,
    *,
    client: Minio | None = None,
    settings: Settings | None = None,
) -> None:
    cfg = settings or get_settings()
    minio = client or get_minio()
    minio.remove_object(cfg.minio_bucket, object_key)


def object_exists(
    object_key: str,
    *,
    client: Minio | None = None,
    settings: Settings | None = None,
) -> bool:
    cfg = settings or get_settings()
    minio = client or get_minio()
    try:
        minio.stat_object(cfg.minio_bucket, object_key)
        return True
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
            return False
        raise


MinioDep = Annotated[Minio, Depends(get_minio)]
