"""Мост «отказ инструмента → технический вопрос» (RFC-0006, шаги 1–2).

Источник уже сохранил структурный результат отказа (`derivation.params.routing`, предупреждение
и понятный текст ошибки). Здесь это событие превращается в технический вопрос проекта с
действиями: «Открыть настройки», «Повторить», «Продолжить без этого». Так волны 2B и 2C связаны
по-настоящему: технический вопрос создаёт `TechnicalQuestionService`, а не сам маршрутизатор.

Вопрос из фоновой обработки источника неблокирующий: он не останавливает прогон, а появляется
в списке технических вопросов проекта. Временный сбой (`transient`) и фатальная ошибка (`fatal`)
вопроса не создают: в RFC-0006 для них нет типа, пользователь видит их в ошибке источника и в
настройках ключа.
"""

from uuid import UUID

from app.domain.capabilities import CapabilityIncident
from app.domain.models import TechnicalQuestionKind
from app.infra.repositories.base import Repositories
from app.services.technical_questions import CapabilityFailure, TechnicalQuestionService

# Классы отказа маршрутизации, для которых в RFC-0006 есть тип технического вопроса.
_KIND_BY_REASON: dict[str, TechnicalQuestionKind] = {
    "quota_exhausted": TechnicalQuestionKind.QUOTA_EXHAUSTED,
    "auth": TechnicalQuestionKind.CREDENTIAL_INVALID,
    "unsupported": TechnicalQuestionKind.CAPABILITY_MISSING,
    "capability_missing": TechnicalQuestionKind.CAPABILITY_MISSING,
}
_MAX_SOURCE_TITLE_CHARS = 120


class TechnicalQuestionIncidentSink:
    """`CapabilityIncidentSink` поверх `TechnicalQuestionService` (волна 2B)."""

    def __init__(self, questions: TechnicalQuestionService, repos: Repositories) -> None:
        self._questions = questions
        self._repos = repos

    async def report(self, incident: CapabilityIncident) -> None:
        """Создаёт технический вопрос из отказа возможности; без проекта — пропускает."""
        if incident.project_id is None:
            return
        kind = _KIND_BY_REASON.get(incident.reason or "")
        if kind is None:
            return
        await self._questions.report_failure(
            incident.project_id,
            CapabilityFailure(
                kind=kind,
                text=await self._text(incident),
                capability=incident.capability.value,
                provider=self._provider(incident),
                blocking=False,
            ),
        )

    async def _text(self, incident: CapabilityIncident) -> str:
        """Понятный текст: причина, материал и что уже обработано."""
        parts = [incident.message.strip().rstrip(".")]
        title = await self._source_title(incident.source_id)
        if title:
            parts.append(f"Материал «{title[:_MAX_SOURCE_TITLE_CHARS]}»")
        progress: list[str] = []
        if incident.done:
            progress.append(f"обработано {incident.done}")
        if incident.remaining:
            progress.append(f"осталось {incident.remaining}")
        if progress:
            parts.append(", ".join(progress).capitalize())
        return ". ".join(parts) + "."

    async def _source_title(self, source_id: UUID | None) -> str | None:
        if source_id is None:
            return None
        source = await self._repos.sources.get(source_id)
        return source.title if source is not None else None

    @staticmethod
    def _provider(incident: CapabilityIncident) -> str | None:
        derivation = incident.derivation
        if not isinstance(derivation, dict):
            return None
        provider = derivation.get("provider")
        return provider if isinstance(provider, str) else None
