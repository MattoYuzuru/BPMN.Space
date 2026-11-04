"""Ключи моделей пользователя: добавление с проверкой, список, правка, удаление, модели.

Открытый ключ существует только в `create` — до шифрования и проверки у провайдера; ни в ответы,
ни в журналы, ни в `last_error` он не попадает (тексты ошибок адаптеров его не содержат, а
`redact_secrets` вычищает остаточные следы).
"""

import time
from collections.abc import Callable
from dataclasses import replace
from uuid import UUID

from pydantic import SecretStr

from app.domain.credentials import (
    MAX_CREDENTIALS_PER_USER,
    MAX_LABEL_CHARS,
    LlmCredential,
    key_hint,
)
from app.infra.crypto import CredentialCipher, CredentialCipherError
from app.infra.repositories.base import Repositories
from app.llm.capabilities import capabilities_for, nearest_effort
from app.llm.client import (
    PROVIDER_ANTHROPIC,
    PROVIDER_COMPATIBLE,
    USER_PROVIDERS,
    LlmAuthError,
    LlmClient,
    LlmConfig,
    ModelInfo,
    redact_secrets,
)
from app.llm.net_guard import UnsafeBaseUrlError, normalize_base_url
from app.services.common import Runtime
from app.services.errors import ConflictError, InvalidInputError, NotFoundError, UnavailableError

type ClientFactory = Callable[[LlmConfig], LlmClient]

PROVIDER_LABELS = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "openai_compatible": "Совместимый",
}
_MIN_KEY_CHARS = 8
_MAX_KEY_CHARS = 512
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"


class LlmCredentialService:
    def __init__(
        self,
        repos: Repositories,
        *,
        cipher: CredentialCipher,
        client_factory: ClientFactory,
        runtime: Runtime,
        allowed_private_hosts: tuple[str, ...] = (),
        models_cache_sec: float = 300.0,
        monotonic: Callable[[], float] = time.monotonic,
        anthropic_effort: str | None = None,
    ) -> None:
        self._anthropic_effort = anthropic_effort
        self._repos = repos
        self._cipher = cipher
        self._client_factory = client_factory
        self._rt = runtime
        self._allowed_private = allowed_private_hosts
        self._cache_sec = models_cache_sec
        self._monotonic = monotonic
        self._models: dict[UUID, tuple[float, list[ModelInfo]]] = {}

    @property
    def storage_available(self) -> bool:
        return self._cipher.available

    @property
    def _repo(self):
        repo = self._repos.llm_credentials
        if repo is None:
            raise UnavailableError("Ключи моделей требуют PostgreSQL или in-memory хранилище")
        return repo

    async def list_for(self, user_id: UUID) -> list[LlmCredential]:
        return await self._repo.list_by_user(user_id)

    async def _own(self, user_id: UUID, credential_id: UUID) -> LlmCredential:
        credential = await self._repo.get(credential_id)
        if credential is None or credential.user_id != user_id:
            raise NotFoundError("Ключ модели не найден")
        return credential

    async def create(
        self,
        user_id: UUID,
        *,
        provider: str,
        label: str | None,
        api_key: SecretStr,
        base_url: str | None,
        default_model: str | None,
        make_default: bool,
    ) -> LlmCredential:
        if not self._cipher.available:
            raise UnavailableError(
                "Хранение ключей не настроено на сервере: администратору нужен "
                "CREDENTIALS_ENCRYPTION_KEY"
            )
        if provider not in USER_PROVIDERS:
            raise InvalidInputError("Неизвестный провайдер")
        secret = api_key.get_secret_value().strip()
        if not _MIN_KEY_CHARS <= len(secret) <= _MAX_KEY_CHARS or any(c.isspace() for c in secret):
            raise InvalidInputError("Ключ выглядит неверно: проверьте, что скопировали его целиком")
        url = self._checked_url(provider, base_url)
        if await self._repo.count(user_id) >= MAX_CREDENTIALS_PER_USER:
            raise ConflictError("Достигнут лимит ключей: удалите ненужные")
        title = (label or "").strip()[:MAX_LABEL_CHARS] or PROVIDER_LABELS[provider]
        config = LlmConfig(
            provider=provider,
            model=default_model or "-",
            api_key=SecretStr(secret),
            base_url=url,
        )
        models = await self._fetch_models(config)
        model = default_model or self._pick_default(provider, models)
        existing = await self._repo.list_by_user(user_id)
        credential = LlmCredential(
            id=self._rt.new_id(),
            user_id=user_id,
            provider=provider,
            label=title,
            base_url=url,
            encrypted_key=self._cipher.encrypt(user_id, secret),
            key_hint=key_hint(secret),
            default_model=model,
            is_default=make_default or not existing,
            created_at=self._rt.clock(),
        )
        await self._repo.save(credential)
        self._models[credential.id] = (self._monotonic(), models)
        return credential

    def _checked_url(self, provider: str, base_url: str | None) -> str | None:
        if provider != PROVIDER_COMPATIBLE:
            return None  # адреса OpenAI и Anthropic фиксированы
        if not base_url or not base_url.strip():
            raise InvalidInputError("Укажите адрес API совместимого провайдера")
        try:
            return normalize_base_url(base_url, allowed_private_hosts=self._allowed_private)
        except UnsafeBaseUrlError as error:
            raise InvalidInputError(str(error)) from None

    @staticmethod
    def _pick_default(provider: str, models: list[ModelInfo]) -> str | None:
        ids = [item.id for item in models]
        if provider == PROVIDER_ANTHROPIC and DEFAULT_ANTHROPIC_MODEL in ids:
            return DEFAULT_ANTHROPIC_MODEL
        return ids[0] if ids else None

    async def _fetch_models(self, config: LlmConfig) -> list[ModelInfo]:
        client = self._client_factory(config)
        try:
            return self._describe(config, await client.list_models())
        except LlmAuthError as error:
            raise InvalidInputError(str(error)) from None
        except RuntimeError as error:
            raise InvalidInputError(
                f"Не удалось проверить ключ: {redact_secrets(str(error))}"
            ) from None
        finally:
            await client.aclose()

    def _describe(self, config: LlmConfig, models: list[ModelInfo]) -> list[ModelInfo]:
        """Каждой модели — возможности: от провайдера, иначе из справочника или умолчания.

        `effort_default` — тот уровень, который сервер реально отправит без профиля: у Anthropic
        явный `LLM_ANTHROPIC_EFFORT` главнее умолчания модели.
        """
        described: list[ModelInfo] = []
        for item in models:
            caps = item.capabilities or capabilities_for(
                config.provider, item.id, base_url=config.base_url
            )
            if config.provider == PROVIDER_ANTHROPIC and self._anthropic_effort:
                level = nearest_effort(self._anthropic_effort, caps.effort_levels)
                caps = replace(caps, effort_default=level)  # type: ignore[arg-type]
            described.append(replace(item, capabilities=caps))
        return described

    async def update(
        self,
        user_id: UUID,
        credential_id: UUID,
        *,
        label: str | None = None,
        default_model: str | None = None,
        is_default: bool | None = None,
    ) -> LlmCredential:
        await self._own(user_id, credential_id)
        title: str | None = None
        if label is not None:
            title = label.strip()[:MAX_LABEL_CHARS]
            if not title:
                raise InvalidInputError("Название не может быть пустым")
        model = default_model.strip()[:128] if default_model is not None else None
        # Только изменённые колонки: целая строка затёрла бы параллельный `mark_used`.
        updated = await self._repo.update_fields(
            credential_id,
            label=title,
            default_model=model or None,
            is_default=is_default,
            clear_default_model=default_model is not None and not model,
        )
        if updated is None:
            raise NotFoundError("Ключ модели не найден")
        return updated

    async def delete(self, user_id: UUID, credential_id: UUID) -> None:
        await self._own(user_id, credential_id)
        await self._repo.delete(credential_id)
        self._models.pop(credential_id, None)

    async def models(self, user_id: UUID, credential_id: UUID) -> list[ModelInfo]:
        credential = await self._own(user_id, credential_id)
        cached = self._models.get(credential_id)
        now = self._monotonic()
        if cached is not None and now - cached[0] < self._cache_sec:
            return cached[1]
        api_key = self._decrypt(credential)
        config = LlmConfig(
            provider=credential.provider,
            model=credential.default_model or "-",
            api_key=api_key,
            base_url=credential.base_url,
        )
        try:
            models = await self._fetch_models(config)
        except InvalidInputError as error:
            await self._repo.mark_used(credential_id, self._rt.clock(), error.message)
            raise
        self._models[credential_id] = (now, models)
        return models

    def _decrypt(self, credential: LlmCredential) -> SecretStr:
        try:
            return self._cipher.decrypt(credential.user_id, credential.encrypted_key)
        except CredentialCipherError as error:
            raise InvalidInputError(str(error)) from None
