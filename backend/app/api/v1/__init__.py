"""Маршруты API v1 (RFC §5.8). Префикс `/api/v1` добавляет `app/main.py` из config."""

from fastapi import APIRouter

from app.api.v1 import projects, questions, runs, sources, versions

api_router = APIRouter()
for module in (projects, sources, questions, runs, versions):
    api_router.include_router(module.router)
