"""Оценка прогона до запуска (RFC-0005, шаг 4): запросы, токены, деньги и время.

Сервис собирает всё, что видит модель: объём доступных источников, вопросы и текущую схему,
возможности выбранной модели и её цены. Сам расчёт — в чистом `llm/estimate.py`, здесь только
доступ к проекту и уточнение знаков на токен через бесплатный `count_tokens` Anthropic.

Оценка не создаёт прогон и ничего не пишет в БД. Ключ пользователя используется только для
счётчика токенов и отпускается сразу после ответа.
"""

import logging
from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from app.config import Settings
from app.domain.models import RunMode, Source
from app.infra.repositories.base import Repositories
from app.llm.capabilities import ModelCapabilities, RunProfile
from app.llm.estimate import EstimateInput, RunEstimate, estimate_run
from app.services.common import Runtime, get_project
from app.services.errors import InvalidInputError
from app.services.model_resolver import ModelResolver, pipeline_budget, pipeline_limits

logger = logging.getLogger(__name__)

# Образец текста для калибровки `count_tokens`: больше не нужно, счётчик стоит ноль.
CALIBRATION_SAMPLE_CHARS = 20_000
# Правдоподобные границы знаков на токен: вне них калибровку не используем.
CHARS_PER_TOKEN_BOUNDS = (0.5, 10.0)
_CALIBRATION_SYSTEM = (
    "Ты — аналитик бизнес-процессов. Извлеки участников, шаги, условия и результаты процесса."
)
_TOOLS_NOTE = (
    "Стоимость обработки аудио, видео и внешних инструментов (RFC-0006) не входит: "
    "она считается отдельно от вызовов модели"
)


class EstimateService:
    """Оценка прогона по текущим материалам проекта и выбранной модели."""

    def __init__(
        self,
        repos: Repositories,
        *,
        resolver: ModelResolver,
        settings: Settings,
        runtime: Runtime | None = None,
    ) -> None:
        self._repos = repos
        self._resolver = resolver
        self._settings = settings
        self._rt = runtime or Runtime()

    async def estimate(
        self,
        project_id: UUID,
        *,
        mode: RunMode,
        created_by: UUID | None,
        credential_id: UUID | None = None,
        model: str | None = None,
        profile: RunProfile | None = None,
    ) -> RunEstimate:
        """Оценка с профилем: неверный effort или неизвестная модель — `InvalidInputError`."""
        await get_project(self._repos, project_id)  # 404, если проекта нет
        sources = await self._repos.sources.list_by_project(project_id)
        usable = [source for source in sources if source.feeds_model]
        source_chars = sum(len(source.content) for source in usable)
        if source_chars == 0:
            raise InvalidInputError("Добавьте хотя бы один источник с текстом")
        questions = await self._repos.questions.list_by_project(project_id)
        latest = await self._repos.versions.latest(project_id)
        resolved = await self._resolver.resolve(
            created_by, credential_id=credential_id, model=model, profile=profile
        )
        try:
            pipeline = resolved.pipeline
            capabilities = resolved.capabilities
            chars_per_token = await self._calibrate(pipeline, usable, capabilities)
            limits = pipeline_limits(pipeline) or {}
            result = estimate_run(
                EstimateInput(
                    mode=mode,
                    source_chars=source_chars,
                    budget_chars=pipeline_budget(pipeline) or self._settings.context_budget_chars(),
                    chunk_chars=self._settings.llm_chunk_chars,
                    current_xml_chars=len(latest.xml) if latest and latest.xml else 0,
                    questions=len(questions),
                    semantic_review=_semantic_review(pipeline, resolved.profile),
                    json_max_tokens=_positive_int(
                        limits.get("json_max_tokens"), self._settings.llm_json_max_tokens
                    ),
                    chunk_max_tokens=_positive_int(
                        getattr(pipeline, "chunk_max_tokens", None),
                        self._settings.llm_chunk_max_tokens,
                    ),
                    capabilities=capabilities,
                    effort=resolved.profile.effort,
                    chars_per_token=chars_per_token,
                )
            )
        finally:
            await resolved.release()
        notes = [*result.notes, _TOOLS_NOTE]
        if chars_per_token is not None:
            notes.append(
                f"Калибровка count_tokens: {chars_per_token:.2f} знака на токен "
                f"(образец {min(source_chars, CALIBRATION_SAMPLE_CHARS)} знаков)"
            )
        return replace(result, notes=notes, model=resolved.model, provider=resolved.provider)

    async def _calibrate(
        self,
        pipeline: object,
        sources: Sequence[Source],
        capabilities: ModelCapabilities,
    ) -> float | None:
        """Уточняет знаки на токен бесплатным `count_tokens`; сбой счётчика не ломает оценку."""
        count_tokens = getattr(pipeline, "count_tokens", None)
        if count_tokens is None or capabilities.prices is None:
            return None
        sample = _sample([source.content for source in sources])
        if not sample:
            return None
        try:
            tokens = await count_tokens(_CALIBRATION_SYSTEM, sample)
        except Exception:
            logger.warning(
                "Оценка прогона: count_tokens не сработал, беру справочник", exc_info=True
            )
            return None
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens <= 0:
            return None
        value = len(sample) / tokens
        low, high = CHARS_PER_TOKEN_BOUNDS
        return round(value, 3) if low <= value <= high else None


def _sample(texts: list[str]) -> str:
    """Начало доступных текстов до `CALIBRATION_SAMPLE_CHARS` знаков."""
    parts: list[str] = []
    size = 0
    for text in texts:
        if size >= CALIBRATION_SAMPLE_CHARS:
            break
        part = text[: CALIBRATION_SAMPLE_CHARS - size]
        parts.append(part)
        size += len(part)
    return "".join(parts)


def _semantic_review(pipeline: object, profile: RunProfile) -> bool:
    """Включена ли смысловая сверка: профиль прогона, затем настройка пайплайна и сервера."""
    if profile.semantic_review is not None:
        return profile.semantic_review
    value = getattr(pipeline, "semantic_review", None)
    return value if isinstance(value, bool) else True


def _positive_int(value: object, fallback: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return fallback
