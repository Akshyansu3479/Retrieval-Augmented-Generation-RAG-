"""Application configuration via Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "production-rag"
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = False
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    log_json: bool = True
    # Master switch: false silences almost all application logs
    log_enabled: bool = True

    # PostgreSQL
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "rag"
    postgres_password: str = "rag_secret"
    postgres_db: str = "rag"
    database_url: str = (
        "postgresql+asyncpg://rag:rag_secret@postgres:5432/rag"
    )
    database_url_sync: str = (
        "postgresql+psycopg2://rag:rag_secret@postgres:5432/rag"
    )

    # Redis / Celery
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # Qdrant
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "documents"
    qdrant_api_key: str | None = None

    # MinIO
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "rag-documents"
    minio_secure: bool = False
    minio_public_url: str = "http://localhost:9000"

    # Ollama (exclusive LLM provider)
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen2.5-coder:32b"
    ollama_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    ollama_num_ctx: int = Field(default=8192, ge=512)
    ollama_num_predict: int = Field(default=2048, ge=1)
    ollama_timeout: float = Field(default=120.0, gt=0)
    ollama_max_retries: int = Field(default=3, ge=0)

    # Embeddings (independent of LLM)
    embedding_provider: Literal["bge", "openai"] = "bge"
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_dimension: int = Field(default=768, ge=1)
    embedding_batch_size: int = Field(default=32, ge=1)
    embedding_version: str = "1"
    embedding_max_retries: int = Field(default=3, ge=0)
    embedding_cache_ttl_seconds: int = Field(default=604800, ge=60)
    openai_api_key: str | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_base_url: str | None = None
    openai_timeout: float = Field(default=60.0, gt=0)

    # Ingestion defaults
    max_upload_size_mb: int = Field(default=50, ge=1)
    chunk_size: int = Field(default=512, ge=64)
    chunk_overlap: int = Field(default=64, ge=0)
    chunk_strategy: Literal[
        "recursive",
        "token",
        "sentence",
        "heading",
        "semantic",
        "table_aware",
        "parent_child",
    ] = "recursive"
    chunk_parent_size: int = Field(default=2000, ge=128)
    chunk_semantic_threshold: float = Field(default=0.25, ge=0.0, le=1.0)

    # Parsing (Phase 4+)
    # auto: prefer Docling when installed, else native parsers
    # native: always use PyMuPDF + format-specific libraries
    # docling: require Docling (fail if unavailable)
    parser_backend: Literal["auto", "native", "docling"] = "auto"
    parser_enable_ocr: bool = True
    parser_ocr_min_chars: int = Field(default=40, ge=0)
    parser_store_full_text: bool = True

    # Cleaning / metadata enrichment (Phase 5+)
    cleaner_enabled: bool = True
    cleaner_fix_hyphenation: bool = True
    cleaner_strip_urls: bool = False
    metadata_enrichment_enabled: bool = True
    metadata_max_keywords: int = Field(default=15, ge=0, le=100)
    metadata_max_headings: int = Field(default=20, ge=0, le=100)

    # Qdrant indexing / search (Phase 8+)
    qdrant_upsert_batch_size: int = Field(default=64, ge=1)
    qdrant_hnsw_ef: int = Field(default=128, ge=16)
    qdrant_exact_search: bool = False
    qdrant_score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)

    # Retrieval defaults (Phase 10–12)
    retrieval_top_k: int = Field(default=20, ge=1)
    rerank_top_k: int = Field(default=5, ge=1)
    hybrid_alpha: float = Field(default=0.5, ge=0.0, le=1.0)
    retrieval_mode: Literal["hybrid", "semantic", "bm25"] = "hybrid"
    rrf_k: int = Field(default=60, ge=1)
    bm25_corpus_limit: int = Field(default=5000, ge=100)
    query_rewrite_enabled: bool = True
    rerank_enabled: bool = True
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"

    # Context / generation (Phase 13–15)
    context_max_tokens: int = Field(default=3500, ge=256)

    # Observability (Phase 17)
    metrics_enabled: bool = True
    request_id_header: str = "X-Request-ID"

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (dependency-injection friendly)."""
    return Settings()
