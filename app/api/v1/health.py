"""Health and readiness endpoints."""

from __future__ import annotations

import asyncio
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Response, status

from app.config import Settings, get_settings
from app.core.constants import (
    HEALTH_STATUS_DEGRADED,
    HEALTH_STATUS_OK,
    HEALTH_STATUS_UNAVAILABLE,
    SERVICE_MINIO,
    SERVICE_OLLAMA,
    SERVICE_POSTGRES,
    SERVICE_QDRANT,
    SERVICE_REDIS,
)
from app.core.logging import get_logger
from app.database.postgres import check_postgres
from app.database.qdrant import check_qdrant
from app.database.redis import check_redis
from app.schemas.response import DependencyStatus, HealthResponse, ReadyResponse
from app.storage.file_storage import check_minio

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Liveness probe — process is up and serving requests."""
    return HealthResponse(status="ok", service=settings.app_name, version="1.0.0")


async def _timed(coro: Any) -> tuple[str, str | None, float]:
    started = time.perf_counter()
    try:
        await coro
        latency = (time.perf_counter() - started) * 1000
        return HEALTH_STATUS_OK, None, latency
    except Exception as exc:  # noqa: BLE001 — readiness must never raise
        latency = (time.perf_counter() - started) * 1000
        return HEALTH_STATUS_UNAVAILABLE, str(exc), latency


async def _timed_sync(fn: Any) -> tuple[str, str | None, float]:
    started = time.perf_counter()
    try:
        await asyncio.to_thread(fn)
        latency = (time.perf_counter() - started) * 1000
        return HEALTH_STATUS_OK, None, latency
    except Exception as exc:  # noqa: BLE001
        latency = (time.perf_counter() - started) * 1000
        return HEALTH_STATUS_UNAVAILABLE, str(exc), latency


async def _check_postgres() -> DependencyStatus:
    status_value, detail, latency = await _timed(check_postgres())
    return DependencyStatus(
        name=SERVICE_POSTGRES,
        status=status_value,  # type: ignore[arg-type]
        detail=detail,
        latency_ms=round(latency, 2),
    )


async def _check_redis() -> DependencyStatus:
    status_value, detail, latency = await _timed(check_redis())
    return DependencyStatus(
        name=SERVICE_REDIS,
        status=status_value,  # type: ignore[arg-type]
        detail=detail,
        latency_ms=round(latency, 2),
    )


async def _check_qdrant() -> DependencyStatus:
    status_value, detail, latency = await _timed_sync(check_qdrant)
    return DependencyStatus(
        name=SERVICE_QDRANT,
        status=status_value,  # type: ignore[arg-type]
        detail=detail,
        latency_ms=round(latency, 2),
    )


async def _check_minio() -> DependencyStatus:
    status_value, detail, latency = await _timed_sync(check_minio)
    return DependencyStatus(
        name=SERVICE_MINIO,
        status=status_value,  # type: ignore[arg-type]
        detail=detail,
        latency_ms=round(latency, 2),
    )


async def _check_ollama(settings: Settings) -> DependencyStatus:
    """
    Check Ollama reachability and whether the configured model is listed.

    Model absence is reported as degraded (service up, model not pulled yet).
    """
    base = settings.ollama_base_url.rstrip("/")
    tags_url = f"{base}/api/tags"
    started = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=min(settings.ollama_timeout, 5.0)) as client:
            response = await client.get(tags_url)
        latency = (time.perf_counter() - started) * 1000

        if response.status_code >= 500:
            return DependencyStatus(
                name=SERVICE_OLLAMA,
                status=HEALTH_STATUS_UNAVAILABLE,  # type: ignore[arg-type]
                detail=f"HTTP {response.status_code}",
                latency_ms=round(latency, 2),
            )

        payload: dict[str, Any] = response.json()
        models = payload.get("models") or []
        model_names = {
            str(m.get("name", ""))
            for m in models
            if isinstance(m, dict)
        }
        configured = settings.ollama_model
        configured_base = configured.split(":")[0]
        model_found = any(
            name == configured or name.startswith(f"{configured_base}:")
            for name in model_names
        )

        if model_found:
            return DependencyStatus(
                name=SERVICE_OLLAMA,
                status=HEALTH_STATUS_OK,  # type: ignore[arg-type]
                detail=f"model '{configured}' available",
                latency_ms=round(latency, 2),
            )

        return DependencyStatus(
            name=SERVICE_OLLAMA,
            status=HEALTH_STATUS_DEGRADED,  # type: ignore[arg-type]
            detail=(
                f"reachable, but model '{configured}' not found; "
                f"pull it with: ollama pull {configured}"
            ),
            latency_ms=round(latency, 2),
        )
    except Exception as exc:  # noqa: BLE001
        latency = (time.perf_counter() - started) * 1000
        host_hint = _ollama_host_hint(settings.ollama_base_url)
        return DependencyStatus(
            name=SERVICE_OLLAMA,
            status=HEALTH_STATUS_UNAVAILABLE,  # type: ignore[arg-type]
            detail=f"{exc}{host_hint}",
            latency_ms=round(latency, 2),
        )


def _ollama_host_hint(base_url: str) -> str:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if host == "host.docker.internal":
        try:
            socket.getaddrinfo(host, parsed.port or 11434)
        except socket.gaierror:
            return (
                " | hint: ensure docker-compose sets "
                "extra_hosts: host.docker.internal:host-gateway"
            )
        return (
            " | hint: Ollama must listen beyond localhost — start with "
            "OLLAMA_HOST=0.0.0.0:11434 ollama serve"
        )
    return ""


def _aggregate_status(dependencies: list[DependencyStatus]) -> str:
    statuses = {dep.status for dep in dependencies}
    if HEALTH_STATUS_UNAVAILABLE in statuses:
        return HEALTH_STATUS_UNAVAILABLE
    if HEALTH_STATUS_DEGRADED in statuses:
        return HEALTH_STATUS_DEGRADED
    return HEALTH_STATUS_OK


@router.get("/ready", response_model=ReadyResponse)
async def ready(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> ReadyResponse:
    """
    Readiness probe using real client checks for data-plane services.

    Ollama may be degraded/unavailable without failing core readiness:
    missing model => degraded; unreachable Ollama => overall degraded.
    """
    results = await asyncio.gather(
        _check_postgres(),
        _check_redis(),
        _check_qdrant(),
        _check_minio(),
        _check_ollama(settings),
    )
    dependencies = list(results)

    core = [dep for dep in dependencies if dep.name != SERVICE_OLLAMA]
    ollama = next(dep for dep in dependencies if dep.name == SERVICE_OLLAMA)

    core_status = _aggregate_status(core)
    if core_status == HEALTH_STATUS_UNAVAILABLE:
        overall = HEALTH_STATUS_UNAVAILABLE
    elif ollama.status == HEALTH_STATUS_UNAVAILABLE:
        overall = HEALTH_STATUS_DEGRADED
    elif (
        ollama.status == HEALTH_STATUS_DEGRADED
        or core_status == HEALTH_STATUS_DEGRADED
    ):
        overall = HEALTH_STATUS_DEGRADED
    else:
        overall = HEALTH_STATUS_OK

    if overall == HEALTH_STATUS_UNAVAILABLE:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        response.status_code = status.HTTP_200_OK

    logger.info(
        "readiness_check",
        overall=overall,
        dependencies=[dep.model_dump() for dep in dependencies],
    )

    return ReadyResponse(
        status=overall,  # type: ignore[arg-type]
        service=settings.app_name,
        dependencies=dependencies,
    )
