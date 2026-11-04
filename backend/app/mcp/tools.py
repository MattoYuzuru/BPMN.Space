"""Инструменты MCP (RFC-0007, шаг 2): тонкий слой над `services/`, без прямого `infra`.

Каждый инструмент: (1) проверяет право по таблице «инструмент → право» (`begin_tool`, закрыто по
умолчанию), (2) проверяет доступ к проекту/объекту как REST (чужой проект — `404`, viewer на
изменение — `403`), (3) вызывает сервис, (4) отдаёт компактный ответ без ключей и внутренних
полей. Ошибки сервисов превращаются в ожидаемые ошибки инструмента (`ToolError`): модель видит
русскую причину и может её исправить, трейсбек наружу не уходит.

Разрушающее удаление требует `confirm=true` — отдельный шаг против случайных вызовов агента.
Файл через MCP не передаётся: base64 в аргументе — плохой путь для больших документов, поэтому
v1 честно документирует загрузку файла через REST (`POST /projects/{id}/sources/file`).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from app.domain.access import ProjectScope, ResourceKind
from app.domain.bpmn.document import BpmnFormatError
from app.domain.models import (
    ANSWER_VIA_AGENT,
    RunMode,
    SourceDerivation,
    SourceKind,
    SourceOrigin,
    SourceTrust,
    Version,
)
from app.mcp.auth import (
    as_tool_error,
    begin_tool,
    ensure_project,
    ensure_resource,
)
from app.mcp.diagram import (
    lane_selection,
    latest_version,
    parse_document_async,
    project_ir_summary,
)
from app.mcp.estimate import (
    EstimateTicket,
    RedeemedEstimates,
    RunEstimate,
    RunEstimator,
    TicketSigner,
)
from app.mcp.serializers import (
    project_card,
    project_detail,
    question_view,
    run_cost_view,
    run_view,
    source_view,
    uuid_or_404,
    version_summary,
)
from app.services.common import utc_now
from app.services.errors import InvalidInputError, ServiceError, StaleVersionError
from app.services.runs import Budget, RunProfile

__all__ = ["MAX_READ_CHARS", "register_tools"]

#: Порция текста источника за один вызов `read_source`: модель не должна получить мегабайты.
MAX_READ_CHARS = 20_000
#: Предел элементов в списке — как у REST-пагинации, но без курсоров: агенту хватает сводки.
MAX_LIST = 100
_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
_PROFILE_KEYS = frozenset({"effort", "semantic_review", "budget"})
_BUDGET_FIELDS = frozenset({"tokens", "cost_usd"})
_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_READ_SAFE = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)

#: Как загрузить файл: MCP v1 не принимает содержимое файла аргументом.
FILE_HINT = (
    "Файл через MCP не передаётся (v1): загрузите документ или запись через REST "
    "`POST /api/v1/projects/{project_id}/sources/file` с токеном доступа, затем читайте его "
    "инструментом read_source. Текст и ссылки можно добавить через add_source"
)


@contextmanager
def service_errors() -> Iterator[None]:
    """Ожидаемые ошибки сервисов → ошибка инструмента с русским текстом, без трейсбека."""
    try:
        yield
    except ServiceError as error:
        raise as_tool_error(error) from None


def _clean_budget(value: Any) -> dict[str, Any] | None:
    """Бюджет агента: только ограничивающие положительные границы токенов и/или денег.

    Настроек бюджета у пользователя пока нет, поэтому «повышать» нечего: агент может задать
    лишь собственный лимит, который мягко останавливает прогон (RFC-0005, шаг 5). Прогон
    переходит в `waiting` с техническим вопросом, а не молча тратит больше.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InvalidInputError("budget: объект с полями tokens и/или cost_usd")
    unknown = set(value) - _BUDGET_FIELDS
    if unknown:
        raise InvalidInputError(
            "budget содержит неподдерживаемые поля: " + ", ".join(sorted(unknown))
        )
    tokens = value.get("tokens")
    cost_usd = value.get("cost_usd")
    if tokens is not None and (
        not isinstance(tokens, int) or isinstance(tokens, bool) or tokens <= 0
    ):
        raise InvalidInputError("budget.tokens: целое число больше нуля")
    if cost_usd is not None and (
        not isinstance(cost_usd, (int, float)) or isinstance(cost_usd, bool) or cost_usd <= 0
    ):
        raise InvalidInputError("budget.cost_usd: число больше нуля")
    if tokens is None and cost_usd is None:
        raise InvalidInputError("Укажите бюджет в токенах и/или стоимость в долларах")
    return {
        "tokens": tokens,
        "cost_usd": float(cost_usd) if cost_usd is not None else None,
    }


def _profile_json(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    """Профиль из аргументов MCP: effort, смысловая сверка и ограничивающий бюджет."""
    if profile is None:
        return None
    unknown = set(profile) - _PROFILE_KEYS
    if unknown:
        raise InvalidInputError(
            "Профиль содержит неподдерживаемые поля: " + ", ".join(sorted(unknown))
        )
    effort = profile.get("effort")
    if effort is not None and effort not in _EFFORTS:
        raise InvalidInputError("effort: low, medium, high, xhigh или max")
    review = profile.get("semantic_review")
    if review is not None and not isinstance(review, bool):
        raise InvalidInputError("semantic_review: true или false")
    cleaned: dict[str, Any] = {}
    if effort is not None:
        cleaned["effort"] = effort
    if review is not None:
        cleaned["semantic_review"] = review
    budget = _clean_budget(profile.get("budget"))
    if budget is not None:
        cleaned["budget"] = budget
    return cleaned or None


def _service_profile(profile: dict[str, Any] | None) -> RunProfile:
    payload = profile or {}
    raw_budget = payload.get("budget")
    budget = (
        Budget(
            tokens=raw_budget.get("tokens"),
            cost_usd=raw_budget.get("cost_usd"),
        )
        if isinstance(raw_budget, dict)
        else None
    )
    return RunProfile(
        effort=payload.get("effort"),
        semantic_review=payload.get("semantic_review"),
        budget=budget,
    )


def _run_mode(value: str) -> RunMode:
    try:
        return RunMode(value)
    except ValueError as error:
        raise InvalidInputError(
            "kind: analyze — только вопросы, build — вопросы и схема"
        ) from error


def _bpmn_format_error(error: BpmnFormatError) -> ToolError:
    return ToolError(str(error))


def register_tools(  # noqa: PLR0915 — регистрация всех инструментов в одном месте
    server: MCPServer,
    *,
    container: Any,
    estimator: RunEstimator,
    signer: TicketSigner,
    redeemed: RedeemedEstimates,
) -> None:
    """Зарегистрировать инструменты RFC-0007. Права — в `app.mcp.auth.TOOL_POLICIES`."""

    # --- Проекты -------------------------------------------------------------------------
    @server.tool(
        name="list_projects",
        title="Список проектов",
        description=(
            "Проекты, доступные владельцу токена: название, статус, число источников и "
            "открытых вопросов, дорожки последней схемы, роль. Ограничен проектами токена."
        ),
        annotations=_READ,
    )
    async def list_projects(
        ctx: Context,
        limit: Annotated[
            int, Field(ge=1, le=MAX_LIST, description="Сколько проектов вернуть")
        ] = 20,
        query: Annotated[str | None, Field(description="Поиск по названию")] = None,
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "list_projects")
        with service_errors():
            token_ids = identity.token.project_ids
            page = await container.projects.list(
                cursor=None,
                limit=limit,
                query=query,
                owner_id=identity.user.id,
                scope_to_user=True,
                scope=ProjectScope.ALL,
                only_ids=frozenset(token_ids) if token_ids is not None else None,
            )
            roles = await container.access.project_roles(
                [view.project.id for view in page.items], identity.user.id
            )
            return {
                "items": [
                    project_card(view, roles.get(view.project.id, "viewer")) for view in page.items
                ],
                "total": page.total,
            }

    @server.tool(
        name="get_project",
        title="Проект целиком",
        description=(
            "Проект с источниками, вопросами, последней версией и активным прогоном. "
            "Начните с него, чтобы понять, что уже есть."
        ),
        annotations=_READ,
    )
    async def get_project(
        ctx: Context,
        project_id: Annotated[str, Field(description="UUID проекта")],
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "get_project")
        with service_errors():
            pid = uuid_or_404(project_id, "project_id")
            role = await ensure_project(identity, pid, write=False)
            detail = await container.projects.detail(pid)
            return project_detail(detail, role.value)

    @server.tool(
        name="create_project",
        title="Создать проект",
        description="Создать новый проект процесса. Нужен токен без ограничения проектами.",
        annotations=_WRITE,
    )
    async def create_project(
        ctx: Context,
        title: Annotated[str, Field(min_length=1, max_length=200, description="Название")],
        description: Annotated[
            str | None, Field(max_length=2000, description="Описание процесса")
        ] = None,
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "create_project")
        with service_errors():
            view = await container.projects.create(
                title=title, description=description, owner_id=identity.user.id
            )
            return project_card(view, "owner")

    # --- Источники -----------------------------------------------------------------------
    @server.tool(
        name="list_sources",
        title="Источники проекта",
        description=(
            "Дерево материалов проекта: тип, происхождение и доверие, статус обработки, "
            "размер текста. Тексты читаются по одному через read_source."
        ),
        annotations=_READ,
    )
    async def list_sources(
        ctx: Context,
        project_id: Annotated[str, Field(description="UUID проекта")],
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "list_sources")
        with service_errors():
            pid = uuid_or_404(project_id, "project_id")
            await ensure_project(identity, pid, write=False)
            sources = await container.sources.list(pid)
            return {
                "items": [source_view(source) for source in sources[:MAX_LIST]],
                "total": len(sources),
            }

    @server.tool(
        name="read_source",
        title="Прочитать источник порцией",
        description=(
            "Текст источника порцией до 20 000 символов: `from_` — смещение, `to` — конец "
            "(не включая). Ответ содержит `next_from` для следующей порции; `null` — конец."
        ),
        annotations=_READ,
    )
    async def read_source(
        ctx: Context,
        source_id: Annotated[str, Field(description="UUID источника")],
        from_: Annotated[int, Field(ge=0, description="Смещение в символах, 0 — начало")] = 0,
        to: Annotated[int | None, Field(ge=1, description="Конец, не включая")] = None,
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "read_source")
        with service_errors():
            sid = uuid_or_404(source_id, "source_id")
            await ensure_resource(identity, ResourceKind.SOURCE, sid, write=False)
            source = await container.sources.get(sid)
            total = len(source.content)
            if from_ > total:
                raise InvalidInputError(
                    f"Смещение from_={from_} больше длины текста ({total} символов)"
                )
            end = min(
                to if to is not None else from_ + MAX_READ_CHARS, from_ + MAX_READ_CHARS, total
            )
            if end <= from_ < total:
                raise InvalidInputError("to должен быть больше from_")
            return {
                "source": source_view(source),
                "from": from_,
                "to": end,
                "total_chars": total,
                "next_from": end if end < total else None,
                "content": source.content[from_:end],
            }

    @server.tool(
        name="add_source",
        title="Добавить материал",
        description=(
            "Добавить текст или ссылку в проект от имени агента (origin=agent, trust=agent, "
            "пометка «через агента»). `url` — провенанс: сервер страницу не скачивает, "
            "пришлите извлечённый текст в `text`. Файлы — только через REST-загрузку (v1)."
        ),
        annotations=_WRITE,
    )
    async def add_source(  # noqa: PLR0917 — аргументы MCP-инструмента
        ctx: Context,
        project_id: Annotated[str, Field(description="UUID проекта")],
        text: Annotated[str, Field(description="Текст материала (не пустой)")],
        title: Annotated[
            str | None, Field(max_length=200, description="Название источника")
        ] = None,
        kind: Annotated[str, Field(description="text — текст, voice — голосовая заметка")] = "text",
        url: Annotated[
            str | None,
            Field(
                description="Ссылка на первоисточник для провенанса (например, страница Confluence)"
            ),
        ] = None,
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "add_source")
        with service_errors():
            if kind == SourceKind.FILE.value:
                raise InvalidInputError(FILE_HINT)
            try:
                source_kind = SourceKind(kind)
            except ValueError as error:
                raise InvalidInputError(
                    "kind: text — текст, voice — голосовая заметка. " + FILE_HINT
                ) from error
            if source_kind not in {SourceKind.TEXT, SourceKind.VOICE}:
                raise InvalidInputError("kind: text или voice. " + FILE_HINT)
            pid = uuid_or_404(project_id, "project_id")
            await ensure_project(identity, pid, write=True)
            params: dict[str, Any] = {"token_name": identity.token.name}
            if url:
                params["url"] = url
            derivation = SourceDerivation(
                capability="agent",
                provider="mcp",
                params=params,
                created_at=utc_now(),
            )
            source = await container.sources.create_text(
                pid,
                content=text,
                title=title,
                kind=source_kind,
                duration_sec=None,
                origin=SourceOrigin.AGENT,
                trust=SourceTrust.AGENT,
                derivation=derivation,
            )
            return {"source": source_view(source), "origin": SourceOrigin.AGENT.value}

    @server.tool(
        name="update_source",
        title="Изменить источник",
        description=(
            "Поправить название, текст или включить/выключить источник проекта. Текст через "
            "MCP правится только у материалов, добавленных агентом (origin=agent): иначе "
            "правка переписала бы материал человека без видимой пометки «через агента»."
        ),
        annotations=_WRITE,
    )
    async def update_source(
        ctx: Context,
        source_id: Annotated[str, Field(description="UUID источника")],
        title: Annotated[str | None, Field(max_length=200)] = None,
        content: Annotated[str | None, Field(description="Новый текст источника")] = None,
        active: Annotated[
            bool | None, Field(description="Участвует ли источник в прогонах")
        ] = None,
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "update_source")
        with service_errors():
            sid = uuid_or_404(source_id, "source_id")
            await ensure_resource(identity, ResourceKind.SOURCE, sid, write=True)
            if content is not None:
                source = await container.sources.get(sid)
                if source.origin is not SourceOrigin.AGENT:
                    raise ToolError(
                        "Через MCP можно править текст только материалов, добавленных агентом "
                        "(origin=agent): иначе правка изменит источник человека без пометки "
                        "«через агента». Название и включение/выключение менять можно; текст "
                        "источника человека правится в интерфейсе"
                    )
            fields: set[str] = set()
            if title is not None:
                fields.add("title")
            if content is not None:
                fields.add("content")
            if active is not None:
                fields.add("active")
            if not fields:
                raise InvalidInputError("Укажите title, content или active")
            updated = await container.sources.update(
                sid, title=title, content=content, active=active, fields=fields
            )
            return {"source": source_view(updated)}

    @server.tool(
        name="delete_source",
        title="Удалить источник",
        description=(
            "Разрушающее действие: удаляет источник вместе с производными. Требует "
            "`confirm=true`; без него ничего не удаляется."
        ),
        annotations=_DESTRUCTIVE,
    )
    async def delete_source(
        ctx: Context,
        source_id: Annotated[str, Field(description="UUID источника")],
        confirm: Annotated[
            bool, Field(description="true — подтверждение разрушающего удаления")
        ] = False,
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "delete_source")
        if not confirm:
            raise ToolError(
                "Удаление источника разрушающе: повторите вызов с confirm=true, "
                "если действительно нужно удалить источник и его производные"
            )
        with service_errors():
            sid = uuid_or_404(source_id, "source_id")
            await ensure_resource(identity, ResourceKind.SOURCE, sid, write=True)
            await container.sources.delete(sid)
            return {"deleted": True, "id": str(sid)}

    # --- Вопросы -------------------------------------------------------------------------
    @server.tool(
        name="list_questions",
        title="Вопросы проекта",
        description=(
            "Открытые и отвеченные вопросы. `lane` сужает до дорожки схемы — для проверки "
            "своей части процесса."
        ),
        annotations=_READ,
    )
    async def list_questions(
        ctx: Context,
        project_id: Annotated[str, Field(description="UUID проекта")],
        lane: Annotated[
            str | None, Field(description="Название дорожки; без неё — все вопросы")
        ] = None,
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "list_questions")
        with service_errors():
            pid = uuid_or_404(project_id, "project_id")
            await ensure_project(identity, pid, write=False)
            questions = await container.questions.list(pid, status=None)
            selection = None
            if lane:
                version = await latest_version(container, pid)
                document = await parse_document_async(version.xml)
                selection = lane_selection(document, lane)
                questions = [
                    question
                    for question in questions
                    if selection.element_ids & set(question.element_ids)
                ]
            return {
                "items": [question_view(question) for question in questions[:MAX_LIST]],
                "total": len(questions),
                "lane": selection.to_json() if selection is not None else None,
            }

    @server.tool(
        name="answer_question",
        title="Ответить на вопрос",
        description=(
            "Ответить на вопрос от имени владельца токена. Ответ помечается «через агента» "
            "с названием токена: сервер не проверяет, читал ли человек ответ."
        ),
        annotations=_WRITE,
    )
    async def answer_question(
        ctx: Context,
        question_id: Annotated[str, Field(description="UUID вопроса")],
        text: Annotated[str, Field(min_length=1, description="Текст ответа")],
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "answer_question")
        with service_errors():
            qid = uuid_or_404(question_id, "question_id")
            await ensure_resource(identity, ResourceKind.QUESTION, qid, write=True)
            question = await container.questions.answer(
                qid,
                text=text,
                via=ANSWER_VIA_AGENT,
                via_name=identity.token.name,
            )
            return question_view(question)

    # --- Прогоны -------------------------------------------------------------------------
    @server.tool(
        name="estimate_run",
        title="Оценить прогон",
        description=(
            "Реальная оценка прогона (RFC-0005): диапазон токенов, запросов, денег и времени, "
            "разбивка по этапам, модель и провайдер. `complete=false` — цены модели неизвестны, "
            "стоимость не выдаётся. Возвращает `estimate_token` — допуск для start_run; "
            "без свежей оценки запуск невозможен."
        ),
        annotations=_READ,
    )
    async def estimate_run(
        ctx: Context,
        project_id: Annotated[str, Field(description="UUID проекта")],
        kind: Annotated[
            str, Field(description="analyze — вопросы, build — вопросы и схема")
        ] = "analyze",
        profile: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "Профиль прогона: effort (low…max), semantic_review (true/false) и "
                    "budget {tokens?, cost_usd?} — ограничивающий лимит прогона"
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "estimate_run")
        with service_errors():
            mode = _run_mode(kind)
            profile_json = _profile_json(profile)
            pid = uuid_or_404(project_id, "project_id")
            # Как REST `POST /projects/{id}/runs/estimate`: наблюдатель тоже может оценить,
            # запуск же остаётся за редактором (start_run).
            await ensure_project(identity, pid, write=False)
            estimate: RunEstimate = await estimator.estimate(
                project_id=pid,
                mode=mode,
                profile=profile_json,
                user_id=identity.user.id,
            )
            ticket, parsed = signer.issue(
                project_id=pid,
                user_id=identity.user.id,
                mode=mode,
                profile=profile_json,
                model=estimate.model,
                provider=estimate.provider,
            )
            return {
                "project_id": str(pid),
                "kind": mode.value,
                "profile": profile_json,
                "estimate": estimate.to_json(),
                "complete": estimate.complete,
                "cost_known": estimate.cost is not None,
                "estimate_token": ticket,
                "estimate_id": str(parsed.estimate_id),
                "expires_at": parsed.expires_at.isoformat(),
            }

    @server.tool(
        name="start_run",
        title="Запустить прогон",
        description=(
            "Запустить анализ или сборку по `estimate_token` из estimate_run: без свежей оценки "
            "запуск отклоняется. Прогон выполняется в фоне — следите через get_run."
        ),
        annotations=_WRITE,
    )
    async def start_run(
        ctx: Context,
        estimate_token: Annotated[str, Field(description="estimate_token из estimate_run")],
        project_id: Annotated[
            str | None, Field(description="UUID проекта (сверяется с оценкой)")
        ] = None,
        base_version_id: Annotated[
            str | None,
            Field(description="Голова схемы, которую видит агент; устаревшая — конфликт"),
        ] = None,
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "start_run")
        with service_errors():
            claims: EstimateTicket = signer.decode(estimate_token)
            if claims.user_id != identity.user.id:
                raise InvalidInputError(
                    "Оценка выдана другому владельцу токена — запросите её заново"
                )
            pid = claims.project_id
            if project_id is not None and uuid_or_404(project_id, "project_id") != pid:
                raise InvalidInputError(
                    "project_id не совпадает с оценкой: запросите оценку заново"
                )
            await ensure_project(identity, pid, write=True)
            # Допуск одноразовый: повторный запуск по той же оценке отклоняется.
            redeemed.redeem(claims.estimate_id)
            # Профиль (включая бюджет) и модель берутся из подписанного тикета; бюджет агента
            # только ограничивает прогон и мягко останавливает его на лимите (RFC-0005 шаг 5).
            run = await container.runs.start(
                pid,
                mode=claims.mode,
                created_by=identity.user.id,
                actor_email=getattr(identity.user, "email", None),
                base_version_id=(
                    uuid_or_404(base_version_id, "base_version_id")
                    if base_version_id is not None
                    else None
                ),
                profile=_service_profile(claims.profile),
                expected_model=claims.model,
                expected_provider=claims.provider,
            )
            return {"run": run_view(run), "budget": (claims.profile or {}).get("budget")}

    @server.tool(
        name="get_run",
        title="Состояние прогона",
        description=(
            "Статус, этап и прогресс прогона, итог по вопросам, собранная версия и потрачено "
            "по журналу вызовов (токены, кеш, деньги, этапы; `complete=false` — часть цен "
            "неизвестна). Текст ошибки провайдера наружу не отдаётся: только `failed`."
        ),
        annotations=_READ,
    )
    async def get_run(
        ctx: Context,
        run_id: Annotated[str, Field(description="UUID прогона")],
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "get_run")
        with service_errors():
            rid = uuid_or_404(run_id, "run_id")
            await ensure_resource(identity, ResourceKind.RUN, rid, write=False)
            run = await container.runs.get(rid)
            cost = await container.runs.cost(rid)
            return {
                "run": run_view(run),
                "cost": run_cost_view(cost) if cost is not None else None,
            }

    # --- Схема ---------------------------------------------------------------------------
    @server.tool(
        name="get_diagram",
        title="Схема BPMN",
        description=(
            "Последняя версия схемы: XML BPMN 2.0, сводка IR, дорожки, основания и вопросы. "
            "`lane` сужает основания и вопросы до выбранной дорожки (XML остаётся полным)."
        ),
        annotations=_READ,
    )
    async def get_diagram(
        ctx: Context,
        project_id: Annotated[str, Field(description="UUID проекта")],
        lane: Annotated[str | None, Field(description="Название дорожки")] = None,
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "get_diagram")
        with service_errors():
            pid = uuid_or_404(project_id, "project_id")
            await ensure_project(identity, pid, write=False)
            version = await latest_version(container, pid)
            try:
                document = await parse_document_async(version.xml)
            except BpmnFormatError as error:
                raise _bpmn_format_error(error) from None
            detail = await container.projects.detail(pid)
            selection = lane_selection(document, lane) if lane else None
            element_ids = selection.element_ids if selection is not None else None
            evidence = [
                {
                    "element_id": element_id,
                    "source_id": str(quote.source_id),
                    "quote": quote.quote,
                }
                for element_id, quote in version.trace.items()
                if element_ids is None or element_id in element_ids
            ]
            questions = detail.questions
            if element_ids is not None:
                questions = [
                    question for question in questions if element_ids & set(question.element_ids)
                ]
            return {
                "project_id": str(pid),
                "version": version_summary(version),
                "xml": version.xml,
                "lanes": [lane_item.name for lane_item in document.lanes],
                "ir": project_ir_summary(document, detail),
                "lane": selection.to_json() if selection is not None else None,
                "evidence": evidence[:MAX_LIST],
                "questions": [question_view(question) for question in questions[:MAX_LIST]],
            }

    @server.tool(
        name="check_diagram",
        title="Проверить схему",
        description=(
            "Проверить BPMN XML без сохранения: безопасность XML, официальная XSD и bpmnlint. "
            "Вернуть замечания, дорожки, число узлов и потоков."
        ),
        annotations=_READ_SAFE,
    )
    async def check_diagram(
        ctx: Context,
        xml: Annotated[str, Field(description="BPMN 2.0 XML целиком")],
    ) -> dict[str, Any]:
        begin_tool(ctx, "check_diagram")
        with service_errors():
            check = await container.versions.check(xml)
            return {
                "xsd_valid": check.xsd_valid,
                "lint": [
                    {
                        "rule": issue.rule,
                        "message": issue.message,
                        "severity": issue.severity.value,
                        "element_id": issue.element_id,
                    }
                    for issue in check.lint
                ],
                "lanes": check.lanes,
                "nodes": check.nodes,
                "flows": check.flows,
            }

    @server.tool(
        name="save_diagram",
        title="Сохранить правку схемы",
        description=(
            "Сохранить правку BPMN как новую ручную версию. `base_version_id` защищает от "
            "перезаписи чужой правки: устаревшая голова — конфликт, перечитайте get_diagram."
        ),
        annotations=_WRITE,
    )
    async def save_diagram(
        ctx: Context,
        project_id: Annotated[str, Field(description="UUID проекта")],
        xml: Annotated[str, Field(description="BPMN 2.0 XML новой версии")],
        base_version_id: Annotated[
            str | None,
            Field(description="id версии, которую правили; null — только если схемы ещё нет"),
        ] = None,
    ) -> dict[str, Any]:
        identity = begin_tool(ctx, "save_diagram")
        with service_errors():
            pid = uuid_or_404(project_id, "project_id")
            await ensure_project(identity, pid, write=True)
            try:
                saved: Version = await container.versions.save_manual(
                    pid,
                    xml=xml,
                    base_version_id=(
                        uuid_or_404(base_version_id, "base_version_id")
                        if base_version_id is not None
                        else None
                    ),
                    actor_email=getattr(identity.user, "email", None),
                )
            except StaleVersionError as error:
                raise ToolError(
                    f"{error.message}. Перечитайте схему через get_diagram и повторите правку"
                ) from None
            return {"version": version_summary(saved)}
