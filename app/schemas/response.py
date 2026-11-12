"""Shared API response schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness probe response."""

    status: Literal["ok"] = "ok"
    service: str
    version: str = "1.0.0"


class DependencyStatus(BaseModel):
    """Status of a single infrastructure dependency."""

    name: str
    status: Literal["ok", "degraded", "unavailable"]
    detail: str | None = None
    latency_ms: float | None = None


class ReadyResponse(BaseModel):
    """Readiness probe response."""

    status: Literal["ok", "degraded", "unavailable"]
    service: str
    dependencies: list[DependencyStatus] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Standard error payload."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
