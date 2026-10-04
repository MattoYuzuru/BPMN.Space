"""SQL-реализация онбординга: состояние тура и отмеченные пункты чек-листа."""

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.dialects.postgresql import insert

from app.domain.onboarding import (
    ChecklistItem,
    CompletedItem,
    ItemSource,
    TourStatus,
    TourStepKey,
    UserOnboarding,
)
from app.infra.db_models import UserOnboardingItemRow, UserOnboardingRow
from app.infra.repositories.session import SessionFactory


def _state(row: UserOnboardingRow) -> UserOnboarding:
    return UserOnboarding(
        user_id=row.user_id,
        tour_status=TourStatus(row.tour_status),
        tour_step=TourStepKey(row.tour_step) if row.tour_step else None,
        tour_project_id=row.tour_project_id,
        checklist_hidden=row.checklist_hidden,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlOnboardingRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    async def get_or_create(self, user_id: UUID, now: datetime) -> UserOnboarding:
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
