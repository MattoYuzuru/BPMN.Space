"""Онбординг: состояние тура, учёт первых действий и выбор места для пунктов чек-листа.

Учёт — «лучшее усилие»: `record` вызывается после успешного основного действия и никогда не
пробрасывает исключения (сбой учёта не ломает действие пользователя). Действия, которых сервер
не видит, клиент сообщает через `report_event` (белый список `CLIENT_REPORTABLE`).
"""

import logging
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from app.domain.onboarding import (
    CLIENT_REPORTABLE,
    FIRST_STEP,
    ChecklistItem,
    CompletedItem,
    ItemSource,
    ProjectFacts,
    Target,
    TourStatus,
    TourStepKey,
    TourTransitionError,
    UserOnboarding,
    check_transition,
    resolve_target,
)
from app.fixtures.samples import tour_text_suggestion
from app.infra.repositories.base import OnboardingRepository, Repositories
from app.services.common import Runtime
from app.services.errors import ConflictError, InvalidInputError, NotFoundError

logger = logging.getLogger(__name__)

# Сколько последних проектов (свои и где я редактор) смотрим при выборе места.
_CANDIDATES = 30


@dataclass(frozen=True, slots=True, kw_only=True)
class OnboardingView:
    state: UserOnboarding
    items: list[CompletedItem]
    tour_text_suggestion: str


class OnboardingService:
    def __init__(self, repos: Repositories, *, runtime: Runtime, enabled: bool) -> None:
        self._repos = repos
        self._rt = runtime
        # Онбординг есть только у вошедших пользователей и только если хранилище его умеет.
        self._enabled = enabled and repos.onboarding is not None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def _store(self) -> OnboardingRepository:
        store = self._repos.onboarding
        if store is None:
            raise NotFoundError("Обучение недоступно")
        return store

    async def state(self, user_id: UUID) -> OnboardingView:
        state = await self._store.get_or_create(user_id, self._rt.clock())
        return await self._view(state)

    async def _view(self, state: UserOnboarding) -> OnboardingView:
        return OnboardingView(
            state=state,
            items=await self._store.list_items(state.user_id),
            tour_text_suggestion=tour_text_suggestion(),
        )

    async def update_tour(
        self,
        user_id: UUID,
        *,
        status: TourStatus | None,
        step: TourStepKey | None,
        project_id: UUID | None,
        project_given: bool,
    ) -> OnboardingView:
        """Смена статуса или шага тура. Недопустимый переход — 409, чужой проект — 404."""
        now = self._rt.clock()
        current = await self._store.get_or_create(user_id, now)
        target = status or current.tour_status
        try:
            check_transition(current.tour_status, target)
        except TourTransitionError as error:
            raise ConflictError(str(error)) from error

        new_project = current.tour_project_id
        if project_given:
            new_project = project_id
            if (
                project_id is not None
                and await self._repos.projects.owner_of(project_id) != user_id
            ):
                raise NotFoundError("Проект не найден")
        new_step = (
            (step or current.tour_step or FIRST_STEP) if target is TourStatus.ACTIVE else None
        )
        await self._save_tour(
            current, status=target, step=new_step, project_id=new_project, now=now
        )
        self._log_transition(current, target, new_step, now)
        return await self._view(
            replace(
                current,
                tour_status=target,
                tour_step=new_step,
                tour_project_id=new_project,
                updated_at=now,
            )
        )

    async def restart(self, user_id: UUID) -> OnboardingView:
        """Начать тур заново: `active`, первый шаг, без учебного проекта."""
        now = self._rt.clock()
        current = await self._store.get_or_create(user_id, now)
        check_transition(current.tour_status, TourStatus.ACTIVE, restart=True)
        await self._save_tour(
            current, status=TourStatus.ACTIVE, step=FIRST_STEP, project_id=None, now=now
        )
        logger.info("onboarding.tour_started user_id=%s restart=true", user_id)
        return await self._view(
            replace(
                current,
                tour_status=TourStatus.ACTIVE,
                tour_step=FIRST_STEP,
                tour_project_id=None,
                updated_at=now,
            )
        )

    async def _save_tour(
        self,
        current: UserOnboarding,
        *,
        status: TourStatus,
        step: TourStepKey | None,
        project_id: UUID | None,
        now: datetime,
    ) -> None:
        saved = await self._store.save_tour(
            current.user_id,
            expected_status=current.tour_status,
            status=status,
            step=step,
            project_id=project_id,
            now=now,
        )
        if not saved:  # другая вкладка успела сменить статус
            raise ConflictError(
                "Состояние обучения изменилось в другой вкладке — обновите страницу"
            )

    @staticmethod
    def _log_transition(
        current: UserOnboarding, target: TourStatus, step: TourStepKey | None, now: datetime
    ) -> None:
        seconds = max(0.0, (now - current.updated_at).total_seconds())
        user_id = current.user_id
        match target:
            case TourStatus.ACTIVE if current.tour_status is not TourStatus.ACTIVE:
                logger.info("onboarding.tour_started user_id=%s restart=false", user_id)
            case TourStatus.ACTIVE if step != current.tour_step:
                logger.info(
                    "onboarding.step user_id=%s step=%s previous_step=%s previous_step_sec=%.1f",
                    user_id,
                    step.value if step else None,
                    current.tour_step.value if current.tour_step else None,
                    seconds,
                )
            case TourStatus.COMPLETED:
                logger.info(
                    "onboarding.tour_completed user_id=%s last_step=%s last_step_sec=%.1f",
                    user_id,
                    current.tour_step.value if current.tour_step else None,
                    seconds,
                )
            case TourStatus.DISMISSED:
                logger.info(
                    "onboarding.tour_dismissed user_id=%s step=%s step_sec=%.1f",
                    user_id,
                    current.tour_step.value if current.tour_step else None,
                    seconds,
                )
            case _:
                pass

    async def set_checklist_hidden(self, user_id: UUID, *, hidden: bool) -> OnboardingView:
        now = self._rt.clock()
        current = await self._store.get_or_create(user_id, now)
        await self._store.set_checklist_hidden(user_id, hidden, now)
        return await self._view(replace(current, checklist_hidden=hidden, updated_at=now))

    async def report_event(self, user_id: UUID, item: ChecklistItem) -> None:
        """Отметка от клиента. Принимаются только пункты из белого списка; повтор — не ошибка."""
        if item not in CLIENT_REPORTABLE:
            raise InvalidInputError("Этот пункт отмечается автоматически, сообщать о нём не нужно")
        await self._insert(user_id, item, ItemSource.CLIENT)

    async def record(
        self, user_id: UUID | None, item: ChecklistItem, source: ItemSource = ItemSource.SERVER
    ) -> bool:
        """Отмечает пункт чек-листа; `True` — отмечен впервые.

        Без пользователя (нет аккаунтов), при выключенном онбординге и при любой ошибке
        хранилища ничего не делает и не пробрасывает исключение: основное действие уже выполнено.
        """
        if user_id is None or not self._enabled:
            return False
        try:
            return await self._insert(user_id, item, source)
        except Exception:
            logger.exception(
                "Не удалось отметить пункт %s онбординга пользователя %s", item, user_id
            )
            return False

    async def _insert(self, user_id: UUID, item: ChecklistItem, source: ItemSource) -> bool:
        if not self._enabled:
            return False
        first = await self._store.add_item(user_id, item, source, self._rt.clock())
        if first:
            in_tour = await self._in_tour(user_id)
            logger.info(
                "onboarding.item_completed user_id=%s item=%s source=%s in_tour=%s",
                user_id,
                item.value,
                source.value,
                str(in_tour).lower(),
            )
        return first

    async def _in_tour(self, user_id: UUID) -> bool:
        try:
            state = await self._store.get(user_id)
        except Exception:  # поле журнала не стоит отказа учёта
            return False
        return state is not None and state.tour_status is TourStatus.ACTIVE

    async def target(self, user_id: UUID, item: ChecklistItem) -> Target:
        """Куда вести по пункту: по проектам, которые пользователь может редактировать."""
        return resolve_target(item, await self._facts(user_id))

    async def _facts(self, user_id: UUID) -> list[ProjectFacts]:
        return await self._store.project_facts(user_id, limit=_CANDIDATES)
