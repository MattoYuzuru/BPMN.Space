"""Сборщик контекста прогона (RFC §5.2): что видит модель за один прогон.

В контекст идут активные разобранные источники (с id для цитат), вопросы с ответами
и допущениями и текущая схема, если аналитик её правил.
TODO(real): #6 бюджет ~60k токенов: для больших документов один раз строится и кэшируется
дайджест (`Source.digest`) со ссылками на цитаты; ProcessGraph ручной правки — текстом
с пометкой «правки аналитика приоритетнее».
"""

from collections.abc import Sequence

from app.domain.analysis import ContextSource, RunContext
from app.domain.models import (
    Project,
    Question,
    Source,
    SourceStatus,
    Version,
    VersionOrigin,
)


def build_run_context(
    *,
    project: Project,
    sources: Sequence[Source],
    questions: Sequence[Question],
    versions: Sequence[Version],
) -> RunContext:
    latest = versions[0] if versions else None
    return RunContext(
        project_id=project.id,
        project_title=project.title,
        sources=[
            ContextSource(
                id=s.id, kind=s.kind, title=s.title, content=s.content, created_at=s.created_at
            )
            for s in sources
            if s.active and s.status is SourceStatus.READY and s.content.strip()
        ],
        questions=list(questions),
        current_xml=latest.xml if latest else None,
        current_is_manual=latest is not None and latest.origin is VersionOrigin.MANUAL,
        generated_versions=sum(1 for v in versions if v.origin is VersionOrigin.GENERATED),
    )
