"""Request ID and lightweight metrics middleware."""

from __future__ import annotations

import time
import uuid
from collections import Counter
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings

_request_counts: Counter[str] = Counter()
_latency_ms_sum: Counter[str] = Counter()
_error_counts: Counter[str] = Counter()


def metrics_snapshot() -> dict:
    paths = sorted(set(_request_counts) | set(_error_counts))
    items = []
    for path in paths:
        count = _request_counts[path]
        total_latency = _latency_ms_sum[path]
        items.append(
            {
                "path": path,
                "requests": count,
                "errors": _error_counts[path],
                "avg_latency_ms": round(total_latency / count, 2) if count else 0.0,
            }
        )
    return {
        "requests_total": int(sum(_request_counts.values())),
        "errors_total": int(sum(_error_counts.values())),
        "paths": items,
    }


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()
        header = settings.request_id_header
        request_id = request.headers.get(header) or str(uuid.uuid4())
        started = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            latency = (time.perf_counter() - started) * 1000
            path = request.url.path
            if settings.metrics_enabled:
                _request_counts[path] += 1
                _latency_ms_sum[path] += int(latency)
                if response is not None and response.status_code >= 500:
                    _error_counts[path] += 1
            if response is not None:
                response.headers[header] = request_id
                response.headers["X-Response-Time-ms"] = f"{latency:.2f}"
