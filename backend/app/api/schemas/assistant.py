"""Контракт диалогового помощника."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel


class AssistantTurn(ApiModel):
    role: Literal["assistant", "user"]
    text: str = Field(min_length=1, max_length=4000)


class AssistantRequest(ApiModel):
    message: str = Field(min_length=1, max_length=4000)
    diagram_xml: str = Field(default="", max_length=30_000)
    history: list[AssistantTurn] = Field(default_factory=list, max_length=10)
    credential_id: UUID | None = Field(
        default=None, description="Свой ключ модели; не задан — ключ по умолчанию, затем сервер"
    )
    model: str | None = Field(default=None, max_length=128)


class LocalAssistantRequest(AssistantRequest):
    project_title: str = Field(min_length=1, max_length=200)
    source: str = Field(default="", max_length=24_000)


class AssistantResponse(ApiModel):
    answer: str
