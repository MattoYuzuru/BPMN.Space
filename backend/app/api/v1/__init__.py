"""Маршруты API v1 (RFC §5.8). Префикс `/api/v1` добавляет `app/main.py` из config."""

from fastapi import APIRouter

from app.api.v1 import assistant, projects, questions, runs, sharing, sources, versions

api_router = APIRouter()
for module in (projects, sources, questions, runs, versions, assistant, sharing):
    api_router.include_router(module.router)
