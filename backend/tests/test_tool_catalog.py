"""Каталог провайдеров для «Инструментов» (RFC-0006, шаг 6): данные, консистентность, HTTP.

Каталог — подсказки «где взять ключ» с датой проверки 04.11.2026 и признаком «есть адаптер в
коде». Проверяется, что у каждой возможности есть провайдеры, ссылки только https, дата
присутствует, а признаки поддержки не расходятся с реестром адаптеров. HTTP-тесты: cookie-сессия
обязательна, гость получает 401, контракт отдаёт карточки.
"""

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.container import build_container
from app.domain.capabilities import (
    CAPABILITY_DESCRIPTIONS,
    CAPABILITY_LABELS,
    CAPABILITY_TOOLS,
    Capability,
    kinds_for_capability,
)
from app.ingest.adapters import build_default_registry
from app.main import create_app
from app.services.auth import optional_user
from app.services.tool_catalog import CATALOG_CHECKED_ON, ToolCatalogService

API = "/api/v1"
CHECKED_ON = date(2026, 11, 4)


def _catalog() -> ToolCatalogService:
    return ToolCatalogService(build_default_registry())


def test_catalog_has_checked_date_and_every_capability() -> None:
    catalog = _catalog().catalog()

    assert catalog.checked_on == CHECKED_ON == CATALOG_CHECKED_ON
    by_capability = {card.capability: card for card in catalog.capabilities}
    assert set(by_capability) == set(Capability)
    for capability, card in by_capability.items():
        assert card.providers, f"у возможности {capability} нет провайдеров"
        assert card.label == CAPABILITY_LABELS[capability]
        assert card.description == CAPABILITY_DESCRIPTIONS[capability]
        assert card.tool == CAPABILITY_TOOLS[capability]
        assert card.kinds == kinds_for_capability(capability)


def test_every_capability_has_https_key_page() -> None:
    """Хотя бы один провайдер возможности отвечает на вопрос «где взять ключ» (https)."""
    for card in _catalog().catalog().capabilities:
        key_urls = [provider.key_url for provider in card.providers if provider.key_url]
        assert key_urls, f"у возможности {card.capability} нет ссылки на страницу ключа"
        assert all(url.startswith("https://") for url in key_urls)


def test_provider_ids_are_unique_and_urls_https() -> None:
    for card in _catalog().catalog().capabilities:
        ids = [provider.id for provider in card.providers]
        assert len(ids) == len(set(ids)), f"повтор провайдера в {card.capability}"
        for provider in card.providers:
            assert provider.key_url is None or provider.key_url.startswith("https://")


def test_support_flags_do_not_divorce_adapter_registry() -> None:
    """`supported=true` — рабочие вызовы адаптера, а каждый провайдер из кода есть в каталоге."""
    registry = build_default_registry()
    catalog = _catalog().catalog()
    listed = {
        (card.capability, provider.id)
        for card in catalog.capabilities
        for provider in card.providers
    }
    for card in catalog.capabilities:
        if card.capability is Capability.LLM:
            continue  # у моделей своя проверка провайдера (ADR-0011), не реестр адаптеров
        for provider in card.providers:
            if provider.supported:
                assert registry.implements(card.capability, provider.id), provider.id
    for capability in Capability:
        for provider_id, _ in registry.providers(capability):
            if provider_id == "openai_compatible":
                # Адрес и ключ выдаёт сам совместимый сервер: страницы «где взять» нет.
                continue
            assert (capability, provider_id) in listed, (capability, provider_id)


def test_contract_providers_are_not_marked_supported() -> None:
    """Контракты без вызовов: ключ сохранить можно, но каталог не выдаёт их за рабочие."""
    registry = build_default_registry()
    by_capability = {card.capability: card for card in _catalog().catalog().capabilities}
    ocr = {provider.id: provider for provider in by_capability[Capability.OCR].providers}
    for provider_id in ("mistral", "yandex"):
        assert provider_id in ocr
        assert ocr[provider_id].supported is False
        # Ключ можно добавить заранее (регистрация есть), но рабочих вызовов нет.
        assert registry.supports(Capability.OCR, provider_id) is True
        assert registry.implements(Capability.OCR, provider_id) is False


def test_web_capabilities_have_working_providers() -> None:
    catalog = _catalog().catalog()
    by_capability = {card.capability: card for card in catalog.capabilities}

    search = by_capability[Capability.WEB_SEARCH]
    working = {provider.id for provider in search.providers if provider.supported}
    assert {"tavily", "brave", "exa"} <= working
    assert search.tool == "search_web"

    fetch = by_capability[Capability.WEB_FETCH]
    working_fetch = {provider.id for provider in fetch.providers if provider.supported}
    assert {"jina", "firecrawl"} <= working_fetch
    assert fetch.tool == "read_url"

    # Ключ модели тоже закрывает веб-возможности — это подсказка, а не рабочий адаптер.
    assert any(provider.model_covers for provider in search.providers)
    assert search.model_coverage


def test_model_coverage_text_present_for_non_llm_capabilities() -> None:
    for card in _catalog().catalog().capabilities:
        if card.capability is Capability.LLM:
            assert card.model_coverage is None
            continue
        assert card.model_coverage, card.capability


def test_rf_providers_are_present_and_marked() -> None:
    """Геоограничения важнее цен: данных в РФ должны быть провайдеры и они помечены."""
    providers = [
        provider
        for card in _catalog().catalog().capabilities
        for provider in card.providers
        if provider.rf
    ]
    assert {provider.id for provider in providers} >= {"yandex"}


# --- HTTP -----------------------------------------------------------------------------------


class CatalogStack:
    """Контейнер с каталогом; пользователь подменяется зависимостью FastAPI."""

    def __init__(self, *, auth_enabled: bool = False, with_user: bool = True) -> None:
        self.settings = Settings(
            mock_delay_scale=0,
            auth_enabled=auth_enabled,
            seed_demo_data=False,
            credentials_encryption_key=SecretStr(Fernet.generate_key().decode()),
            rate_limit_enabled=False,
        )
        self.container = build_container(self.settings)
        self.app = create_app(self.settings, container=self.container)
        if with_user:
            self.user = SimpleNamespace(id=uuid4(), email="tools@example.com")
            self.app.dependency_overrides[optional_user] = lambda: self.user


def test_tool_catalog_http_returns_cards() -> None:
    stack = CatalogStack()
    with TestClient(stack.app) as client:
        response = client.get(f"{API}/me/tool-catalog")

    assert response.status_code == 200
    body = response.json()
    assert body["checked_on"] == "2026-11-04"
    assert len(body["capabilities"]) == len(list(Capability))
    cards = {card["capability"]: card for card in body["capabilities"]}
    search = cards["web_search"]
    assert search["label"] == "Поиск в интернете"
    assert search["tool"] == "search_web"
    assert search["kinds"] == ["web_search"]
    assert search["model_coverage"]
    ids = {provider["id"] for provider in search["providers"]}
    assert ids >= {"tavily", "brave", "exa"}
    tavily = next(provider for provider in search["providers"] if provider["id"] == "tavily")
    assert tavily["key_url"] == "https://app.tavily.com"
    assert tavily["supported"] is True
    assert tavily["free_tier"]
    assert tavily["rf"] is False
    assert cards["web_fetch"]["providers"]
    assert all(not provider["supported"] for provider in cards["ocr"]["providers"])


def test_tool_catalog_requires_session() -> None:
    """Без вошедшего пользователя каталог закрыт (как и управление ключами)."""
    stack = CatalogStack(auth_enabled=True, with_user=False)
    # Cookie-сессии нет: зависимость пользователя возвращает None, как для гостя.
    stack.app.dependency_overrides[optional_user] = lambda: None
    with TestClient(stack.app) as client:
        response = client.get(f"{API}/me/tool-catalog")

    assert response.status_code == 401


def test_tool_catalog_http_with_user() -> None:
    stack = CatalogStack(auth_enabled=True)
    with TestClient(stack.app) as client:
        response = client.get(f"{API}/me/tool-catalog")

    assert response.status_code == 200
    assert response.json()["checked_on"] == CHECKED_ON.isoformat()


@pytest.mark.parametrize("capability", list(Capability))
def test_catalog_card_names_provider_hints(capability: Capability) -> None:
    cards = {card.capability: card for card in _catalog().catalog().capabilities}
    card = cards[capability]
    assert any(provider.key_url or provider.model_covers for provider in card.providers)
