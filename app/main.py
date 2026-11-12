"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import health, metrics
from app.api.v1.router import api_router
from app.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.database.postgres import close_postgres, init_postgres
from app.database.qdrant import close_qdrant, ensure_collection, init_qdrant
from app.database.redis import close_redis, init_redis
from app.schemas.response import ErrorResponse
from app.storage.file_storage import close_minio, ensure_bucket, init_minio

settings = get_settings()
configure_logging(settings)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize shared infrastructure clients on startup."""
    logger.info(
        "application_startup",
        app_name=settings.app_name,
        env=settings.app_env,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        log_enabled=settings.log_enabled,
        log_level=settings.log_level,
        log_json=settings.log_json,
    )

    init_postgres(settings)
    init_redis(settings)
    init_qdrant(settings)
    ensure_collection(settings=settings)
    init_minio(settings)
    ensure_bucket(settings=settings)

    logger.info(
        "infrastructure_ready",
        postgres=settings.postgres_host,
        redis=settings.redis_host,
        qdrant=settings.qdrant_url,
        minio=settings.minio_endpoint,
        qdrant_collection=settings.qdrant_collection,
        embedding_dimension=settings.embedding_dimension,
    )

    yield

    await close_redis()
    await close_postgres()
    close_qdrant()
    close_minio()
    logger.info("application_shutdown", app_name=settings.app_name)


def create_app() -> FastAPI:
    """Application factory for uvicorn and future tests."""
    application = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "Production-oriented RAG backend. "
            "LLM inference via local Ollama only."
        ),
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(AppError)
    async def handle_app_error(
        _request: Request,
        exc: AppError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                code=exc.code,
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                code="http_error",
                message=str(exc.detail),
            ).model_dump(),
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                code="validation_error",
                message="Request validation failed",
                details={"errors": exc.errors()},
            ).model_dump(),
        )

    application.include_router(health.router)
    application.include_router(metrics.router)
    application.include_router(api_router)

    return application


app = create_app()
