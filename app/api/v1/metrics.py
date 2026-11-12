"""Lightweight in-process metrics endpoint (Phase 17)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.core.middleware import metrics_snapshot

router = APIRouter(tags=["metrics"])


@router.get("/metrics", summary="In-process request metrics snapshot")
async def metrics(settings: Settings = Depends(get_settings)) -> dict:
    if not settings.metrics_enabled:
        return {"enabled": False}
    snap = metrics_snapshot()
    snap["enabled"] = True
    snap["service"] = settings.app_name
    return snap
