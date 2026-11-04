"""Ключи пользователя по типам задач (RFC-0006): добавление с проверкой, список, правка, проверка.

Обобщает прежний сервис ключей моделей (ADR-0011). Один ключ закрывает одну или несколько
возможностей; открытый ключ существует только до шифрования и проверки у провайдера. Ни в
ответы, ни в журналы, ни в `last_error` он не попадает: тексты ошибок адаптеров его не содержат,
а `redact_secrets` вычищает остаточные следы.

Проверка ключа дешёвая и не оплачивает основную работу: список моделей у LLM-провайдера,
`GET /models` у OpenAI-совместимого распознавания, `GET /v1/auth/token` у Deepgram, поиск с
одним результатом у веб-поиска, остаток кредитов у Firecrawl. Для vision/OCR/видео/озвучки
проверка честно отвечает «пока недоступна», ключ при этом сохраняется.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from uuid import UUID

from pydantic import SecretStr

from app.domain.capabilities import (
    CAPABILITY_DESCRIPTIONS,
    CAPABILITY_LABELS,
    CAPABILITY_TOOLS,
    KIND_CAPABILITIES,
    Capability,
    CapabilityError,
    CredentialKind,
    ErrorClass,
)
from app.domain.credentials import (
    MAX_CREDENTIALS_PER_USER,
    MAX_LABEL_CHARS,
    MAX_PRIORITY,
    Credential,
    checked_monthly_limit,
    key_hint,
)
from app.infra.crypto import CredentialCipher, CredentialCipherError
from app.infra.repositories.base import Repositories
from app.ingest.adapters import AdapterContext, AdapterRegistry
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
logger = logging.getLogger(__name__)

_MIN_KEY_CHARS = 8
_MAX_KEY_CHARS = 512
_MAX_MODEL_CHARS = 128
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
# Сколько секунд помнить ошибку списка моделей (неверный или отозванный ключ).
MODELS_ERROR_CACHE_SEC = 60.0


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderOption:
    """Провайдер, поддержанный для возможности: идентификатор и подпись для интерфейса."""

    id: str
    label: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityCard:
    """Карточка возможности в настройках: что это, есть ли рабочий ключ и что с ним не так."""

    capability: Capability
    label: str
    description: str
    tool: str
    kinds: tuple[CredentialKind, ...]
    providers: tuple[ProviderOption, ...]
    keys: int
    available: bool
    last_error_code: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CredentialCheck:
    """Итог проверки ключа: без исключений для отказа провайдера, с понятным текстом."""

    ok: bool
    detail: str
    capability: Capability | None = None
    last_error_code: str | None = None


class CredentialService:
    def __init__(
        self,
        repos: Repositories,
        *,
        cipher: CredentialCipher,
        client_factory: ClientFactory,
        registry: AdapterRegistry,
        runtime: Runtime,
        allowed_private_hosts: tuple[str, ...] = (),
        models_cache_sec: float = 300.0,
        adapter_transport=None,
        adapter_client_factory=None,
        monotonic: Callable[[], float] = time.monotonic,
        anthropic_effort: str | None = None,
    ) -> None:
        self._anthropic_effort = anthropic_effort
        self._repos = repos
        self._cipher = cipher
        self._client_factory = client_factory
        self._registry = registry
        self._rt = runtime
        self._allowed_private = allowed_private_hosts
        self._cache_sec = models_cache_sec
        self._adapter_transport = adapter_transport
        self._adapter_client_factory = adapter_client_factory
        self._monotonic = monotonic
        self._models: dict[UUID, tuple[float, list[ModelInfo]]] = {}
        self._model_errors: dict[UUID, tuple[float, str]] = {}

    @property
    def storage_available(self) -> bool:
        return self._cipher.available

    @property
    def _repo(self):
        repo = self._repos.credentials
        if repo is None:
            raise UnavailableError("Ключи требуют PostgreSQL или in-memory хранилище")
        return repo

    async def list_for(self, user_id: UUID) -> list[Credential]:
        return await self._repo.list_by_user(user_id)

    async def list_by_kind(self, user_id: UUID, kind: CredentialKind) -> list[Credential]:
        return [item for item in await self._repo.list_by_user(user_id) if kind in item.kinds]

    async def capabilities(self, user_id: UUID) -> list[CapabilityCard]:
        """Карточки всех возможностей для настроек: даже те, для которых ключа ещё нет."""
        own = await self._repo.list_by_user(user_id)
        now = self._rt.clock()
        cards: list[CapabilityCard] = []
        for capability in Capability:
            matching = [item for item in own if item.covers(capability)]
            working = [item for item in matching if item.enabled and not item.is_exhausted(now)]
            broken = next((item for item in matching if item.last_error_code), None)
            cards.append(
                CapabilityCard(
                    capability=capability,
                    label=CAPABILITY_LABELS[capability],
                    description=CAPABILITY_DESCRIPTIONS[capability],
                    tool=CAPABILITY_TOOLS[capability],
                    kinds=tuple(
                        kind for kind, value in KIND_CAPABILITIES.items() if value is capability
                    ),
                    providers=self._provider_options(capability),
                    keys=len(working),
                    available=bool(working),
                    last_error_code=broken.last_error_code if broken else None,
                )
            )
        return cards

    def _provider_options(self, capability: Capability) -> tuple[ProviderOption, ...]:
        if capability is Capability.LLM:
            return tuple(
                ProviderOption(id=provider, label=PROVIDER_LABELS[provider])
                for provider in USER_PROVIDERS
            )
        return tuple(
            ProviderOption(id=provider, label=label)
            for provider, label in self._registry.providers(capability)
        )

    async def _own(self, user_id: UUID, credential_id: UUID) -> Credential:
        credential = await self._repo.get(credential_id)
        if credential is None or credential.user_id != user_id:
            raise NotFoundError("Ключ не найден")
        return credential

    async def _own_llm(self, user_id: UUID, credential_id: UUID) -> Credential:
        """Ключ модели для прежнего `/me/llm-credentials`: не-LLM ключ для него не существует.

        Такой ключ неотличим от чужого или удалённого: `404`, а не удаление или правка.
        """
        credential = await self._own(user_id, credential_id)
        if not credential.is_llm:
            raise NotFoundError("Ключ модели не найден")
        return credential

    async def create(
        self,
        user_id: UUID,
        *,
        kinds: tuple[CredentialKind, ...],
        provider: str,
        label: str | None,
        api_key: SecretStr,
        base_url: str | None,
        default_model: str | None,
        priority: int,
        enabled: bool,
        monthly_limit: dict[str, float] | None,
        make_default: bool,
    ) -> Credential:
        """Проверяет и сохраняет ключ для одной или нескольких возможностей."""
        if not self._cipher.available:
            raise UnavailableError(
                "Хранение ключей не настроено на сервере: администратору нужен "
                "CREDENTIALS_ENCRYPTION_KEY"
            )
        chosen_kinds = self._checked_kinds(kinds, provider)
        secret = api_key.get_secret_value().strip()
        if not _MIN_KEY_CHARS <= len(secret) <= _MAX_KEY_CHARS or any(c.isspace() for c in secret):
            raise InvalidInputError("Ключ выглядит неверно: проверьте, что скопировали его целиком")
        is_llm = CredentialKind.LLM in chosen_kinds
        if make_default and not is_llm:
            raise InvalidInputError("Ключ по умолчанию выбирается только среди ключей моделей")
        try:
            limit = checked_monthly_limit(monthly_limit)
        except ValueError as error:
            raise InvalidInputError(str(error)) from None
        if not 0 <= priority <= MAX_PRIORITY:
            raise InvalidInputError(f"Приоритет — от 0 до {MAX_PRIORITY}: меньше — раньше")
        url = self._checked_base_url(provider, base_url)
        if await self._repo.count(user_id) >= MAX_CREDENTIALS_PER_USER:
            raise ConflictError("Достигнут лимит ключей: удалите ненужные")
        title = (label or "").strip()[:MAX_LABEL_CHARS] or self._default_label(provider)
        model = (default_model or "").strip()[:_MAX_MODEL_CHARS] or None
        models: list[ModelInfo] = []
        if is_llm:
            config = LlmConfig(
                provider=provider,
                model=model or "-",
                api_key=SecretStr(secret),
                base_url=url,
            )
            models = await self._checked_models(config)
            model = model or self._pick_default(provider, models)
        credential = Credential(
            id=self._rt.new_id(),
            user_id=user_id,
            kinds=chosen_kinds,
            provider=provider,
            label=title,
            base_url=url,
            encrypted_key=self._cipher.encrypt(user_id, secret),
            key_hint=key_hint(secret),
            default_model=model,
            priority=priority,
            enabled=enabled,
            monthly_limit=limit,
            is_default=False,
            created_at=self._rt.clock(),
        )
        if not is_llm:
            await self._check_adapter(credential, secret)
        if is_llm:
            existing = await self._repo.list_by_user(user_id)
            llm_keys = [item for item in existing if item.is_llm]
            credential = replace(credential, is_default=make_default or not llm_keys)
        await self._repo.save(credential)
        if is_llm:
            self._models[credential.id] = (self._monotonic(), models)
        return credential

    def _checked_kinds(
        self, kinds: tuple[CredentialKind, ...], provider: str
    ) -> tuple[CredentialKind, ...]:
        unique = tuple(dict.fromkeys(kinds))
        if not unique:
            raise InvalidInputError("Выберите хотя бы один тип задачи для ключа")
        for kind in unique:
            capability = KIND_CAPABILITIES[kind]
            if capability is Capability.LLM:
                if provider not in USER_PROVIDERS:
                    raise InvalidInputError("Неизвестный провайдер модели")
                continue
            if not self._registry.supports(capability, provider):
                text = (
                    ", ".join(label for _, label in self._registry.providers(capability))
                    or "пока ни один провайдер"
                )
                raise InvalidInputError(
                    f"Провайдер «{provider}» не умеет «{CAPABILITY_LABELS[capability]}». "
                    f"Поддержаны: {text}"
                )
        return unique

    @staticmethod
    def _default_label(provider: str) -> str:
        if provider in PROVIDER_LABELS:
            return PROVIDER_LABELS[provider]
        return provider.capitalize()

    def _checked_base_url(self, provider: str, base_url: str | None) -> str | None:
        """Адрес задаёт пользователь только у совместимых провайдеров; правила SSRF — ADR-0011."""
        if provider != PROVIDER_COMPATIBLE:
            return None  # адреса Anthropic, OpenAI, Deepgram, Groq фиксированы
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

    async def create_llm(
        self,
        user_id: UUID,
        *,
        provider: str,
        label: str | None,
        api_key: SecretStr,
        base_url: str | None,
        default_model: str | None,
        make_default: bool,
    ) -> Credential:
        """Совместимость `/me/llm-credentials` (ADR-0011): ключ только для моделей."""
        return await self.create(
            user_id,
            kinds=(CredentialKind.LLM,),
            provider=provider,
            label=label,
            api_key=api_key,
            base_url=base_url,
            default_model=default_model,
            priority=100,
            enabled=True,
            monthly_limit=None,
            make_default=make_default,
        )

    async def _checked_models(self, config: LlmConfig) -> list[ModelInfo]:
        try:
            return await self._fetch_models(config)
        except CapabilityError as error:
            raise InvalidInputError(error.message) from None

    async def _fetch_models(self, config: LlmConfig) -> list[ModelInfo]:
        client = self._client_factory(config)
        try:
            return self._describe(config, await client.list_models())
        except LlmAuthError as error:
            raise CapabilityError(ErrorClass.AUTH, str(error)) from None
        except RuntimeError as error:
            raise CapabilityError(
                ErrorClass.TRANSIENT,
                f"Не удалось проверить ключ: {redact_secrets(str(error))}",
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

    async def _check_adapter(self, credential: Credential, secret: str) -> None:
        """Проверяет не-LLM ключ дешёвым запросом адаптера (список моделей, токен провайдера)."""
        capability = next(
            value for kind, value in KIND_CAPABILITIES.items() if kind in credential.kinds
        )
        adapter = None
        try:
            adapter = self._registry.create(
                capability,
                credential.provider,
                AdapterContext(
                    api_key=secret,
                    base_url=credential.base_url,
                    model=credential.default_model,
                    credential_id=credential.id,
                    transport=self._adapter_transport,
                    client_factory=self._adapter_client_factory,
                    allowed_private_hosts=self._allowed_private,
                ),
            )
            await adapter.check()
        except CapabilityError as error:
            raise InvalidInputError(error.message) from None
        except ValueError as error:
            raise InvalidInputError(
                f"Адрес провайдера отклонён проверкой безопасности: {error}"
            ) from None
        finally:
            if adapter is not None:
                await adapter.aclose()

    async def _check_existing(self, credential: Credential, api_key: SecretStr) -> str:
        """Проверка сохранённого ключа: LLM — список моделей, остальные — адаптер."""
        if credential.is_llm:
            config = LlmConfig(
                provider=credential.provider,
                model=credential.default_model or "-",
                api_key=api_key,
                base_url=credential.base_url,
            )
            models = await self._fetch_models(config)
            self._models[credential.id] = (self._monotonic(), models)
            return f"Ключ действует: доступно моделей — {len(models)}"
        capability = next(
            value for kind, value in KIND_CAPABILITIES.items() if kind in credential.kinds
        )
        adapter = None
        try:
            adapter = self._registry.create(
                capability,
                credential.provider,
                AdapterContext(
                    api_key=api_key.get_secret_value(),
                    base_url=credential.base_url,
                    model=credential.default_model,
                    credential_id=credential.id,
                    transport=self._adapter_transport,
                    client_factory=self._adapter_client_factory,
                    allowed_private_hosts=self._allowed_private,
                ),
            )
            return await adapter.check()
        finally:
            if adapter is not None:
                await adapter.aclose()

    async def check(self, user_id: UUID, credential_id: UUID) -> CredentialCheck:
        """Проверить сохранённый ключ. Отказ провайдера — `ok=false`, а не исключение."""
        credential = await self._own(user_id, credential_id)
        try:
            api_key = self._cipher.decrypt(credential.user_id, credential.encrypted_key)
        except CredentialCipherError as error:
            raise InvalidInputError(str(error)) from None
        capability = credential.capabilities[0] if len(credential.capabilities) == 1 else None
        try:
            detail = await self._check_existing(credential, api_key)
        except CapabilityError as error:
            await self._record_failure(credential, error)
            return CredentialCheck(
                ok=False,
                detail=error.message,
                capability=capability,
                last_error_code=error.error_class.value,
            )
        except ValueError as error:
            # Проверка SSRF не должна превращаться в 500: это отказ класса `unsupported`.
            return CredentialCheck(
                ok=False,
                detail=f"Адрес провайдера отклонён проверкой безопасности: {error}",
                capability=capability,
                last_error_code=ErrorClass.UNSUPPORTED.value,
            )
        await self._repo.mark_used(credential.id, self._rt.clock(), None)
        if not credential.enabled:
            # Ключ был помечен недействительным: успешная проверка включает его снова.
            await self._repo.update_fields(credential.id, enabled=True)
        return CredentialCheck(ok=True, detail=detail, capability=capability)

    async def _record_failure(self, credential: Credential, error: CapabilityError) -> None:
        """Пишет класс и текст ошибки. Ключи моделей не выключаются даже при отказе 401.

        Выключенный LLM-ключ резолвер молча пропускает, и прогон уходит на модель сервера
        (платит оператор), а пользователь не видит причину. Поэтому для `llm` только
        `last_error_code`/`last_error`: модель сообщит об ошибке ключа, а проверить его можно
        в настройках. Ключи инструментов по-прежнему помечаются недействительными.
        """
        try:
            await self._repo.mark_failure(
                credential.id,
                self._rt.clock(),
                error=error.message,
                error_code=error.error_class.value,
                disable=error.error_class is ErrorClass.AUTH and not credential.is_llm,
            )
        except Exception:
            logger.exception("Не удалось записать отказ ключа %s", credential.id)

    async def update_llm(
        self,
        user_id: UUID,
        credential_id: UUID,
        *,
        label: str | None = None,
        default_model: str | None = None,
        is_default: bool | None = None,
    ) -> Credential:
        """Совместимость `/me/llm-credentials`: правит только ключи моделей."""
        await self._own_llm(user_id, credential_id)
        return await self.update(
            user_id,
            credential_id,
            label=label,
            default_model=default_model,
            is_default=is_default,
        )

    async def delete_llm(self, user_id: UUID, credential_id: UUID) -> None:
        """Совместимость `/me/llm-credentials`: удаляет только ключи моделей."""
        await self._own_llm(user_id, credential_id)
        await self.delete(user_id, credential_id)

    async def update(
        self,
        user_id: UUID,
        credential_id: UUID,
        *,
        label: str | None = None,
        default_model: str | None = None,
        is_default: bool | None = None,
        priority: int | None = None,
        enabled: bool | None = None,
        monthly_limit: dict[str, float] | None = None,
        clear_monthly_limit: bool = False,
    ) -> Credential:
        credential = await self._own(user_id, credential_id)
        title: str | None = None
        if label is not None:
            title = label.strip()[:MAX_LABEL_CHARS]
            if not title:
                raise InvalidInputError("Название не может быть пустым")
        model = default_model.strip()[:_MAX_MODEL_CHARS] if default_model is not None else None
        if is_default and not credential.is_llm:
            raise InvalidInputError("Ключ по умолчанию выбирается только среди ключей моделей")
        if priority is not None and not 0 <= priority <= MAX_PRIORITY:
            raise InvalidInputError(f"Приоритет — от 0 до {MAX_PRIORITY}: меньше — раньше")
        limit: dict[str, float] | None = None
        if monthly_limit is not None:
            try:
                limit = checked_monthly_limit(monthly_limit)
            except ValueError as error:
                raise InvalidInputError(str(error)) from None
        # Только изменённые колонки: целая строка затёрла бы параллельный `mark_used`.
        updated = await self._repo.update_fields(
            credential_id,
            label=title,
            default_model=model or None,
            is_default=is_default,
            clear_default_model=default_model is not None and not model,
            priority=priority,
            enabled=enabled,
            monthly_limit=limit,
            clear_monthly_limit=clear_monthly_limit,
        )
        if updated is None:
            raise NotFoundError("Ключ не найден")
        return updated

    async def delete(self, user_id: UUID, credential_id: UUID) -> None:
        await self._own(user_id, credential_id)
        await self._repo.delete(credential_id)
        self._models.pop(credential_id, None)
        self._model_errors.pop(credential_id, None)

    async def models(self, user_id: UUID, credential_id: UUID) -> list[ModelInfo]:
        """Список моделей LLM-ключа с возможностями (ADR-0011); только для типа `llm`."""
        credential = await self._own_llm(user_id, credential_id)
        cached = self._models.get(credential_id)
        now = self._monotonic()
        if cached is not None and now - cached[0] < self._cache_sec:
            return cached[1]
        # Неработающий ключ: шапка проекта спрашивает список при каждом показе, поэтому ошибка
        # помнится недолго — без нового запроса к провайдеру и новой записи `last_error`.
        failed = self._model_errors.get(credential_id)
        if failed is not None and now - failed[0] < min(self._cache_sec, MODELS_ERROR_CACHE_SEC):
            raise InvalidInputError(failed[1])
        try:
            api_key = self._cipher.decrypt(credential.user_id, credential.encrypted_key)
        except CredentialCipherError as error:
            raise InvalidInputError(str(error)) from None
        try:
            models = await self._fetch_models(
                LlmConfig(
                    provider=credential.provider,
                    model=credential.default_model or "-",
                    api_key=api_key,
                    base_url=credential.base_url,
                )
            )
        except CapabilityError as error:
            self._model_errors[credential_id] = (now, error.message)
            await self._record_failure(credential, error)
            raise InvalidInputError(error.message) from None
        self._model_errors.pop(credential_id, None)
        self._models[credential_id] = (now, models)
        return models

    def default_llm_capability(self) -> Capability:
        return Capability.LLM


# Совместимость с прежним именем сервиса (ADR-0011): ключ модели — частный случай RFC-0006.
LlmCredentialService = CredentialService
