"""Маршруты API v1 (RFC §5.8). Префикс `/api/v1` добавляет `app/main.py` из config."""

from fastapi import APIRouter

from app.api.v1 import (
    api_tokens,
    assistant,
    collaboration,
    credentials,
    llm_credentials,
    onboarding,
    presence,
    projects,
    questions,
    runs,
    sharing,
    sources,
    tool_catalog,
    versions,
)

api_router = APIRouter()
for module in (
    projects,
    sources,
    questions,
    runs,
    versions,
    assistant,
    collaboration,
    sharing,
    onboarding,
    llm_credentials,
    credentials,
    tool_catalog,
    api_tokens,
    presence,
):
    api_router.include_router(module.router)
