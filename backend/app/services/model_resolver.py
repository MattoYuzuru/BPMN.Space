"""Выбор модели на один прогон или запрос помощника (ADR-0011).

Порядок: явный ключ из запроса → ключ пользователя по умолчанию → модель сервера из `LLM_*` →
mock (только вне production). Ключ расшифровывается здесь, на время одного вызова, и сразу уходит
в клиент провайдера; наружу, в БД прогонов и журналы он не попадает. Прогон хранит только
`provider`, `model` и `credential_id`.

Здесь же к модели применяется профиль прогона (RFC-0005): effort проверяется по возможностям
модели, у модели без рассуждения отбрасывается. Пределы прогона (бюджет источников,
`max_tokens`) пайплайн получил из справочника при сборке в `llm/factory.py`.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from uuid import UUID

from app.domain.credentials import Credential
from app.infra.crypto import CredentialCipher, CredentialCipherError
from app.infra.repositories.base import Repositories
from app.llm.base import ProcessPipeline
from app.llm.capabilities import (
    EFFORT_LABELS,
    EFFORT_LEVELS,
    ModelCapabilities,
    RunProfile,
    UnsupportedEffortError,
    checked_profile,
)
from app.llm.client import PROVIDER_MOCK, LlmConfig, redact_secrets
from app.llm.pipeline import LlmPipeline
from app.services.common import Runtime
from app.services.errors import InvalidInputError, NotFoundError, UnavailableError

logger = logging.getLogger(__name__)

SOURCE_USER = "user"
SOURCE_SERVER = "server"
SOURCE_MOCK = "mock"
NO_KEY_MESSAGE = "Добавьте ключ модели в настройках"

type PipelineFactory = Callable[[LlmConfig, Credential], ProcessPipeline]


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    pipeline: ProcessPipeline
    provider: str
    model: str
    credential_id: UUID | None
    source: str
    # Профиль после проверки: effort, которого модель не умеет, здесь уже отброшен.
    profile: RunProfile = field(default_factory=RunProfile)

    @property
    def capabilities(self) -> ModelCapabilities:
        return pipeline_capabilities(self.pipeline)

    async def release(self) -> None:
        """Закрывает соединения клиента пользователя; общий пайплайн сервера остаётся жить."""
        if self.source == SOURCE_USER:
            await self.pipeline.aclose()


def pipeline_provider(pipeline: object) -> str:
    return str(getattr(pipeline, "provider", PROVIDER_MOCK))


def pipeline_model(pipeline: object) -> str:
    return str(getattr(pipeline, "model_name", type(pipeline).__name__))


def pipeline_capabilities(pipeline: object) -> ModelCapabilities:
    caps = getattr(pipeline, "capabilities", None)
    return caps if isinstance(caps, ModelCapabilities) else ModelCapabilities()


def pipeline_limits(pipeline: object) -> dict[str, int | str | None] | None:
    """Пределы, которые реально уйдут провайдеру; `None` — у mock и тестовых пайплайнов."""
    limits = getattr(pipeline, "limits", None)
    return dict(limits) if isinstance(limits, dict) else None


def pipeline_budget(pipeline: object) -> int | None:
    """Бюджет источников, рассчитанный из окна модели; `None` — у mock и тестовых пайплайнов."""
    budget = getattr(pipeline, "context_budget_chars", None)
    return budget if isinstance(budget, int) and not isinstance(budget, bool) else None


class ModelResolver:
    def __init__(
        self,
        repos: Repositories | None,
        *,
        server_pipeline: ProcessPipeline | None,
        cipher: CredentialCipher | None = None,
        factory: PipelineFactory | None = None,
        runtime: Runtime | None = None,
        production: bool = False,
        server_max_effort: str | None = None,
    ) -> None:
        self._repos = repos
        self._server = server_pipeline
        self._cipher = cipher
        self._factory = factory
        self._rt = runtime or Runtime()
        self._production = production
        # Потолок effort для модели сервера (`LLM_SERVER_MAX_EFFORT`): ключ оператора общий.
        self._server_max_effort = server_max_effort

    @property
    def server_pipeline(self) -> ProcessPipeline | None:
        return self._server

    @server_pipeline.setter
    def server_pipeline(self, value: ProcessPipeline | None) -> None:
        self._server = value

    def _server_choice(self, *, allow_mock: bool) -> ResolvedModel:
        server = self._server
        if server is None:
            raise InvalidInputError(NO_KEY_MESSAGE)
        provider = pipeline_provider(server)
        if provider == PROVIDER_MOCK:
            if not allow_mock:
                raise UnavailableError(
                    NO_KEY_MESSAGE
                    if self._production
                    else "Помощник не подключён. Настройте LLM_PROVIDER и ключ провайдера "
                    "в окружении или добавьте свой ключ в настройках."
                )
            if self._production:
                raise InvalidInputError(NO_KEY_MESSAGE)
            return ResolvedModel(server, provider, pipeline_model(server), None, SOURCE_MOCK)
        return ResolvedModel(server, provider, pipeline_model(server), None, SOURCE_SERVER)

    async def resolve(
        self,
        user_id: UUID | None,
        *,
        credential_id: UUID | None = None,
        model: str | None = None,
        allow_mock: bool = True,
        profile: RunProfile | None = None,
    ) -> ResolvedModel:
        """Модель прогона; `profile` проверяется по её возможностям (422 при неверном effort)."""
        return await self._with_profile(
            await self._resolve(
                user_id, credential_id=credential_id, model=model, allow_mock=allow_mock
            ),
            profile,
            validate=True,
        )

    async def _resolve(
        self,
        user_id: UUID | None,
        *,
        credential_id: UUID | None,
        model: str | None,
        allow_mock: bool,
    ) -> ResolvedModel:
        repo = self._repos.credentials if self._repos else None
        credential: Credential | None = None
        if user_id is not None and repo is not None:
            if credential_id is not None:
                credential = await repo.get(credential_id)
                if credential is None or credential.user_id != user_id or not credential.is_llm:
                    # Чужой ключ неотличим от несуществующего.
                    raise NotFoundError("Ключ модели не найден")
            else:
                # Выключенный или исчерпанный ключ модели не берём: работает следующий по
                # приоритету, затем — модель сервера. Так же поступает маршрутизатор.
                candidates = [
                    item
                    for item in await repo.list_by_user(user_id)
                    if item.is_llm and item.enabled and not item.is_exhausted(self._rt.clock())
                ]
                credential = next(
                    (item for item in candidates if item.is_default),
                    candidates[0] if candidates else None,
                )
        elif credential_id is not None:
            raise NotFoundError("Ключ модели не найден")
        if credential is None:
            if model:
                raise InvalidInputError("Модель выбирается вместе с ключом")
            return self._server_choice(allow_mock=allow_mock)
        return self._for_credential(credential, model or credential.default_model)

    async def restore(
        self,
        user_id: UUID | None,
        credential_id: UUID | None,
        model: str | None,
        profile: RunProfile | None = None,
        limits: object = None,
    ) -> ResolvedModel:
        """Выбор, профиль и пределы, записанные в прогоне (после рестарта), без подмены.

        `limits` — `ir.execution.limits`: бюджет источников, `max_tokens` и отправляемый уровень,
        рассчитанные при запуске. У прогонов до их записи пределы считаются заново.
        """
        if credential_id is None:
            resolved = self._server_choice(allow_mock=True)
        else:
            repo = self._repos.credentials if self._repos else None
            credential = await repo.get(credential_id) if repo else None
            if credential is None or credential.user_id != user_id or not credential.is_llm:
                raise NotFoundError("Ключ модели удалён. Запустите прогон заново")
            resolved = self._for_credential(credential, model)
        # Записанный профиль проверен при запуске; после рестарта уточнения Models API могут
        # ещё не загрузиться, поэтому он не перепроверяется, а пределы берутся из записи.
        restored = await self._with_profile(resolved, profile, validate=False)
        if isinstance(restored.pipeline, LlmPipeline) and isinstance(limits, dict):
            return replace(restored, pipeline=restored.pipeline.restored(limits))
        return restored

    async def _with_profile(
        self, resolved: ResolvedModel, profile: RunProfile | None, *, validate: bool
    ) -> ResolvedModel:
        """Проверяет профиль по модели и даёт пайплайн прогона с этим профилем."""
        checked = profile or RunProfile()
        if validate:
            try:
                checked = checked_profile(checked, resolved.capabilities, resolved.model)
                if resolved.source == SOURCE_SERVER:
                    self._check_server_profile(checked, resolved)
            except (UnsupportedEffortError, InvalidInputError) as error:
                await resolved.release()
                raise InvalidInputError(str(error)) from None
        pipeline = resolved.pipeline
        if isinstance(pipeline, LlmPipeline):
            pipeline = pipeline.with_profile(checked)
        return ResolvedModel(
            pipeline,
            resolved.provider,
            resolved.model,
            resolved.credential_id,
            resolved.source,
            checked,
        )

    def _check_server_profile(self, profile: RunProfile, resolved: ResolvedModel) -> None:
        """Модель сервера платит оператор: глубже его потолка и со сверкой, которую он
        выключил, её не запускают. Выключить сверку или взять уровень ниже можно."""
        pipeline = resolved.pipeline
        if profile.semantic_review and not getattr(pipeline, "semantic_review", False):
            raise InvalidInputError(
                "Смысловая сверка на модели сервера выключена администратором. "
                "Включить её можно на своём ключе модели"
            )
        if profile.effort is None:
            return
        caps = resolved.capabilities
        ceiling = self._server_max_effort or getattr(pipeline, "effort", None)
        ceiling = ceiling or caps.effort_default
        if ceiling is None:
            return
        order = {level: index for index, level in enumerate(EFFORT_LEVELS)}
        if order[profile.effort] > order.get(ceiling, 0):
            raise InvalidInputError(
                f"Модель сервера работает не глубже уровня «{EFFORT_LABELS[ceiling]}». "
                "Для более тщательной работы добавьте свой ключ модели в настройках"
            )

    def _for_credential(self, credential: Credential, model: str | None) -> ResolvedModel:
        if self._cipher is None or self._factory is None:
            raise UnavailableError("Ключи моделей на сервере не поддерживаются")
        if not model:
            raise InvalidInputError("Выберите модель для этого ключа")
        try:
            api_key = self._cipher.decrypt(credential.user_id, credential.encrypted_key)
        except CredentialCipherError as error:
            raise InvalidInputError(str(error)) from None
        config = LlmConfig(
            provider=credential.provider,
            model=model,
            api_key=api_key,
            base_url=credential.base_url,
        )
        pipeline = self._factory(config, credential)
        return ResolvedModel(pipeline, credential.provider, model, credential.id, SOURCE_USER)

    async def mark(self, credential_id: UUID | None, error: str | None) -> None:
        """Запоминает итог использования ключа; сбой учёта не ломает прогон."""
        repo = self._repos.credentials if self._repos else None
        if credential_id is None or repo is None:
            return
        try:
            await repo.mark_used(
                credential_id,
                self._rt.clock(),
                redact_secrets(error) if error else None,
                error_code="fatal" if error else None,
            )
        except Exception:
            logger.exception("Не удалось записать использование ключа модели")
