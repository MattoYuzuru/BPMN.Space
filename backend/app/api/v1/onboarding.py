"""Онбординг: состояние тура и чек-листа, отметки клиента, место для пункта; учебные материалы."""

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.schemas.common import errors
from app.api.schemas.onboarding import (
    ChecklistEntry,
    ChecklistState,
    ChecklistUpdate,
    OnboardingEvent,
    OnboardingState,
    OnboardingTarget,
    Sample,
    TourState,
    TourUpdate,
)
from app.container import Container
from app.domain.onboarding import ChecklistItem
from app.services.auth import UserRow
from app.services.errors import NotFoundError, UnauthorizedError
from app.services.onboarding import OnboardingView

router = APIRouter(tags=["onboarding"])


def _account(container: Container, user: UserRow | None) -> UUID:
    """Вошедший пользователь; без онбординга ручки отвечают 404, без сессии — 401."""
    if not container.onboarding.enabled:
        raise NotFoundError("Обучение отключено")
    if user is None:
        raise UnauthorizedError("Войдите в аккаунт")
    return user.id


def _state(view: OnboardingView) -> OnboardingState:
    state = view.state
    return OnboardingState(
        enabled=True,
        tour=TourState(
            status=state.tour_status,
            step=state.tour_step,
            project_id=state.tour_project_id,
            updated_at=state.updated_at,
        ),
        checklist=ChecklistState(
            hidden=state.checklist_hidden,
            items=[
                ChecklistEntry(key=item.item, completed_at=item.completed_at, source=item.source)
                for item in view.items
            ],
        ),
        tour_text_suggestion=view.tour_text_suggestion,
    )


@router.get("/me/onboarding")
async def get_onboarding(container: ContainerDep, user: OptionalUserDep) -> OnboardingState:
    """Состояние обучения и чек-листа «Начало работы». Строка пользователя создаётся при
    первом запросе. Всегда `200`: без сессии или при выключенном онбординге — `enabled=false`."""
    if user is None or not container.onboarding.enabled:
        return OnboardingState(enabled=False)
    return _state(await container.onboarding.state(user.id))


@router.patch("/me/onboarding/tour", responses=errors(401, 404, 409, 422))
async def update_tour(
    body: TourUpdate, container: ContainerDep, user: OptionalUserDep
) -> OnboardingState:
    """Сменить шаг или статус тура. Недопустимый переход — 409; чужой или несуществующий
    `project_id` — 404; неизвестный ключ шага — 422."""
    user_id = _account(container, user)
    return _state(
        await container.onboarding.update_tour(
            user_id,
            status=body.status,
            step=body.step,
            project_id=body.project_id,
            project_given="project_id" in body.model_fields_set,
        )
    )


@router.post("/me/onboarding/tour/restart", responses=errors(401, 404))
async def restart_tour(container: ContainerDep, user: OptionalUserDep) -> OnboardingState:
    """Начать тур заново: `active`, шаг `project.create`, без учебного проекта."""
    return _state(await container.onboarding.restart(_account(container, user)))


@router.patch("/me/onboarding/checklist", responses=errors(401, 404, 422))
async def update_checklist(
    body: ChecklistUpdate, container: ContainerDep, user: OptionalUserDep
) -> OnboardingState:
    """Скрыть или вернуть плашку и чек-лист «Начало работы»."""
    user_id = _account(container, user)
    return _state(await container.onboarding.set_checklist_hidden(user_id, hidden=body.hidden))


@router.post(
    "/me/onboarding/events",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=errors(401, 404, 422),
)
async def report_event(
    body: OnboardingEvent, container: ContainerDep, user: OptionalUserDep
) -> Response:
    """Клиент сообщает о действии, которого не видит сервер (`simulation_run`,
    `diagram_exported`). Другие ключи — 422; повтор безопасен."""
    await container.onboarding.report_event(_account(container, user), body.item)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/onboarding/items/{item}/target", responses=errors(401, 404, 422))
async def item_target(
    item: ChecklistItem, container: ContainerDep, user: OptionalUserDep
) -> OnboardingTarget:
    """Куда вести по невыполненному пункту чек-листа: проекты, которые пользователь может
    редактировать (свои и по ссылке на редактирование); демо только для чтения не считаются."""
    target = await container.onboarding.target(_account(container, user), item)
    return OnboardingTarget(
        route=target.route,
        project_id=target.project_id,
        question_id=target.question_id,
        hint=target.hint,
    )


@router.get("/samples", tags=["samples"])
async def list_samples(container: ContainerDep) -> list[Sample]:
    """Учебные материалы для «Примеров» в меню источника; доступ — как у `/examples`."""
    return [Sample.model_validate(item, from_attributes=True) for item in container.samples.list()]
