"""SQL-реализация онбординга: состояние тура и отмеченные пункты чек-листа."""

import logging
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, and_, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.domain.access import ProjectRole
from app.domain.onboarding import (
    ChecklistItem,
    CompletedItem,
    ItemSource,
    ProjectFacts,
    TourStatus,
    TourStepKey,
    UserOnboarding,
)
from app.infra.db_models import (
    DiagramVersionRow,
    ProjectMemberRow,
    ProjectRow,
    QuestionRow,
    SourceRow,
    UserOnboardingItemRow,
    UserOnboardingRow,
)
from app.infra.repositories.session import SessionFactory

logger = logging.getLogger(__name__)


def _state(row: UserOnboardingRow) -> UserOnboarding:
    """Строка в домен. Неизвестные значения (запись новее этого релиза) не роняют запрос:
    шаг сбрасывается, статус считается `dismissed`, чтобы тур не навязывался."""
    try:
        status = TourStatus(row.tour_status)
    except ValueError:
        logger.warning("Неизвестный статус тура %r у пользователя %s", row.tour_status, row.user_id)
        status = TourStatus.DISMISSED
    step: TourStepKey | None = None
    if row.tour_step:
        try:
            step = TourStepKey(row.tour_step)
        except ValueError:
            logger.warning("Неизвестный шаг тура %r у пользователя %s", row.tour_step, row.user_id)
    return UserOnboarding(
        user_id=row.user_id,
        tour_status=status,
        tour_step=step,
        tour_project_id=row.tour_project_id,
        checklist_hidden=row.checklist_hidden,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlOnboardingRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    async def get(self, user_id: UUID) -> UserOnboarding | None:
        async with self.sessions() as session:
            row = await session.get(UserOnboardingRow, user_id)
            return _state(row) if row else None

    async def get_or_create(self, user_id: UUID, now: datetime) -> UserOnboarding:
        existing = await self.get(user_id)
        if existing is not None:
            return existing
        async with self.sessions.begin() as session:
            # Гонка двух первых запросов безопасна: второй вставляет «ничего» и читает строку.
            await session.execute(
                insert(UserOnboardingRow)
                .values(
                    user_id=user_id,
                    tour_status=TourStatus.PENDING.value,
                    checklist_hidden=False,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=[UserOnboardingRow.user_id])
            )
            row = await session.scalar(
                select(UserOnboardingRow)
                .where(UserOnboardingRow.user_id == user_id)
                .execution_options(populate_existing=True)
            )
            if row is None:  # строка исчезла между вставкой и чтением: пользователь удалён
                raise LookupError(f"Нет пользователя {user_id}")
            return _state(row)

    async def project_facts(self, user_id: UUID, *, limit: int) -> list[ProjectFacts]:
        project = ProjectRow
        material = and_(
            SourceRow.project_id == project.id,
            SourceRow.active.is_(True),
            SourceRow.kind != "answer",
        )
        has_sources = exists().where(material, SourceRow.status != "failed")
        has_ready = exists().where(material, SourceRow.status == "ready")
        first_open = (
            select(QuestionRow.id)
            .where(QuestionRow.project_id == project.id, QuestionRow.status == "open")
            .order_by(QuestionRow.created_at, func.length(QuestionRow.code), QuestionRow.code)
            .limit(1)
            .scalar_subquery()
        )
        last_version = (
            select(func.max(DiagramVersionRow.created_at))
            .where(DiagramVersionRow.project_id == project.id)
            .scalar_subquery()
        )
        answered_after = exists().where(
            SourceRow.project_id == project.id,
            SourceRow.kind == "answer",
            SourceRow.created_at > last_version,
        )
        # В `project_members` лежат и зрители (ссылки на чтение): цель — только где можно править.
        editor = exists().where(
            ProjectMemberRow.project_id == project.id,
            ProjectMemberRow.user_id == user_id,
            ProjectMemberRow.role == ProjectRole.EDITOR.value,
        )
        statement = (
            select(
                project.id,
                project.updated_at,
                (project.owner_id == user_id).label("owned"),
                has_sources.label("has_sources"),
                has_ready.label("has_ready"),
                first_open.label("first_open"),
                last_version.label("last_version"),
                answered_after.label("answered_after"),
            )
            .where(or_(project.owner_id == user_id, editor))
            .order_by(project.updated_at.desc(), project.id.desc())
            .limit(limit)
        )
        async with self.sessions() as session:
            rows = (await session.execute(statement)).all()
        return [
            ProjectFacts(
                project_id=row.id,
                updated_at=row.updated_at,
                owned=bool(row.owned),
                has_sources=bool(row.has_sources),
                has_ready_sources=bool(row.has_ready),
                has_diagram=row.last_version is not None,
                open_question_id=row.first_open,
                answered_after_diagram=bool(row.answered_after),
            )
            for row in rows
        ]

    async def save_tour(
        self,
        user_id: UUID,
        *,
        expected_status: TourStatus,
        status: TourStatus,
        step: TourStepKey | None,
        project_id: UUID | None,
        now: datetime,
    ) -> bool:
        async with self.sessions.begin() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(UserOnboardingRow)
                    .where(
                        UserOnboardingRow.user_id == user_id,
                        UserOnboardingRow.tour_status == expected_status.value,
                    )
                    .values(
                        tour_status=status.value,
                        tour_step=step.value if step else None,
                        tour_project_id=project_id,
                        updated_at=now,
                    )
                ),
            )
        return result.rowcount > 0

    async def set_checklist_hidden(self, user_id: UUID, hidden: bool, now: datetime) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(UserOnboardingRow)
                .where(UserOnboardingRow.user_id == user_id)
                .values(checklist_hidden=hidden, updated_at=now)
            )

    async def list_items(self, user_id: UUID) -> list[CompletedItem]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(UserOnboardingItemRow)
                    .where(UserOnboardingItemRow.user_id == user_id)
                    .order_by(UserOnboardingItemRow.completed_at, UserOnboardingItemRow.item_key)
                )
            ).all()
            known = {
                item.value for item in ChecklistItem
            }  # пункты, убранные из продукта, пропускаем
            return [
                CompletedItem(
                    item=ChecklistItem(row.item_key),
                    completed_at=row.completed_at,
                    source=ItemSource(row.source),
                )
                for row in rows
                if row.item_key in known
            ]

    async def add_item(
        self, user_id: UUID, item: ChecklistItem, source: ItemSource, at: datetime
    ) -> bool:
        async with self.sessions.begin() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    insert(UserOnboardingItemRow)
                    .values(
                        user_id=user_id, item_key=item.value, completed_at=at, source=source.value
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            UserOnboardingItemRow.user_id,
                            UserOnboardingItemRow.item_key,
                        ]
                    )
                ),
            )
        return result.rowcount > 0
