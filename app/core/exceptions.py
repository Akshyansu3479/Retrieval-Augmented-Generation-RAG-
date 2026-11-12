"""Application-specific exception hierarchy."""

from typing import Any


class AppError(Exception):
    """Base application error."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "app_error",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class ConfigurationError(AppError):
    """Raised when configuration is invalid or incomplete."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code="configuration_error",
            status_code=500,
            details=details,
        )


class ValidationError(AppError):
    """Raised for invalid client input."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code="validation_error",
            status_code=422,
            details=details,
        )


class NotFoundError(AppError):
    """Raised when a requested resource does not exist."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code="not_found",
            status_code=404,
            details=details,
        )


class ConflictError(AppError):
    """Raised when a resource conflict occurs (e.g. duplicate upload)."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code="conflict",
            status_code=409,
            details=details,
        )


class ServiceUnavailableError(AppError):
    """Raised when a dependent infrastructure service is unreachable."""

    def __init__(
        self,
        service: str,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message or f"Service '{service}' is unavailable",
            code="service_unavailable",
            status_code=503,
            details={"service": service, **(details or {})},
        )
        self.service = service


class OllamaError(AppError):
    """Raised for Ollama client or model failures."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code="ollama_error",
            status_code=502,
            details=details,
        )
