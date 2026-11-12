"""Aggregate API v1 routers."""

from fastapi import APIRouter

from app.api.v1 import chat, documents, health, ingestion
from app.core.constants import API_V1_PREFIX

api_router = APIRouter(prefix=API_V1_PREFIX)

# Health endpoints are also mounted at root in main.py for k8s-style probes.
# Versioned copies remain available under /api/v1 for consistency.
api_router.include_router(health.router)
api_router.include_router(documents.router)
api_router.include_router(ingestion.router)
api_router.include_router(chat.router)
