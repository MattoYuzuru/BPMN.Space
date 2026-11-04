"""Компактные представления REST-сущностей для MCP (RFC-0007).

MCP-инструменты отдают агенту сводки, а не полные REST-схемы: без внутренних полей
(`file_key`, `digest`, `answer_source_id`), без ключей, адресов и текстов ошибок провайдеров.
Тексты — на русском, идентификаторы полей — на английском, как в REST.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import UUID

from app.domain.models import Question, Run, RunStage, RunStatus, Source, Version, VersionSummary
from app.domain.runs import RunCost, stage_label
from app.services.errors import InvalidInputError
from app.services.projects import ProjectDetail, ProjectView

__all__ = [
    "project_card",
    "project_detail",
    "question_view",
    "run_cost_view",
    "run_view",
    "source_view",
    "version_summary",
]


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _counts(view: ProjectView) -> dict[str, int]:
    counts = view.counts
    return {
        "sources": counts.sources,
        "questions_open": counts.questions_open,
        "questions_resolved": counts.questions_resolved,
        "versions": counts.versions,
    }


def project_card(view: ProjectView, role: str) -> dict[str, Any]:
    project = view.project
    return {
        "id": str(project.id),
        "title": project.title,
        "description": project.description,
        "status": view.status.value,
        "created_at": _iso(project.created_at),
        "updated_at": _iso(project.updated_at),
        "counts": _counts(view),
        "lanes": list(view.lanes),
        "access": role,
    }


def source_view(source: Source, *, content: bool = False) -> dict[str, Any]:
    """Карточка источника. `content` — только для одного источника, список без текстов."""
    data: dict[str, Any] = {
        "id": str(source.id),
        "project_id": str(source.project_id),
        "kind": source.kind.value,
        "title": source.title,
        "status": source.status.value,
        "active": source.active,
        "origin": source.origin.value,
        "trust": source.trust.value,
        "created_at": _iso(source.created_at),
        "file_name": source.file_name,
        "mime": source.mime,
        "size_bytes": source.size_bytes,
        "duration_sec": source.duration_sec,
        "warning": source.warning,
        "unreadable_pages": list(source.unreadable_pages),
        "edited_by_human": source.edited_by_human,
        "content_chars": len(source.content),
    }
    if source.derivation is not None:
        data["derivation"] = {
            "capability": source.derivation.capability,
            "provider": source.derivation.provider,
            "model": source.derivation.model,
            "params": dict(source.derivation.params),
        }
    if content:
        data["content"] = source.content
    return data


def question_view(question: Question) -> dict[str, Any]:
    answer = question.answer
    return {
        "id": str(question.id),
        "project_id": str(question.project_id),
        "code": question.code,
        "kind": question.kind.value,
        "category": question.category.value,
        "severity": question.severity.value,
        "status": question.status.value,
        "text": question.text,
        "assumption": question.assumption,
        "about": _quote(question.about),
        "evidence": _quote(question.evidence),
        "element_ids": list(question.element_ids),
        "actions": [
            {"kind": action.kind.value, "label": action.label, "payload": dict(action.payload)}
            for action in question.actions
        ],
        "blocking": question.blocking,
        "answer": (
            {
                "text": answer.text,
                "source_id": str(answer.source_id),
                "via": answer.via,
                "via_name": answer.via_name,
            }
            if answer is not None
            else None
        ),
        "created_at": _iso(question.created_at),
        "updated_at": _iso(question.updated_at),
    }


def _quote(quote: Any) -> dict[str, str] | None:
    if quote is None:
        return None
    return {"source_id": str(quote.source_id), "quote": quote.quote}


def run_view(run: Run) -> dict[str, Any]:
    """Прогон без внутренних полей и без текста ошибки провайдера (RFC-0007, «Утечки»)."""
    return {
        "id": str(run.id),
        "project_id": str(run.project_id),
        "mode": run.mode.value,
        "status": run.status.value,
        "stage": run.stage.value if isinstance(run.stage, RunStage) else None,
        "stage_label": stage_label(run.status, run.stage),
        "progress": run.progress,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "summary": asdict(run.summary) if run.summary is not None else None,
        "version_id": str(run.version_id) if run.version_id else None,
        "failed": run.status is RunStatus.FAILED,
        "warnings": list(run.warnings),
    }


def run_cost_view(cost: RunCost) -> dict[str, Any]:
    """Потрачено на прогон: токены, кеш, деньги и этапы (RFC-0005 шаг 4).

    `complete=false` — часть вызовов без токенов (mock) или цен; `cost_usd=null` — цены
    неизвестны. Ключей и внутренних адресов здесь нет.
    """
    return {
        "tokens_in": cost.tokens_in,
        "tokens_out": cost.tokens_out,
        "cache_read_tokens": cost.cache_read_tokens,
        "cache_write_tokens": cost.cache_write_tokens,
        "calls": cost.calls,
        "cost_usd": cost.cost_usd,
        "currency": "USD",
        "complete": cost.complete,
        "by_stage": [
            {
                "stage": stage.stage,
                "label": stage.label,
                "calls": stage.calls,
                "tokens_in": stage.tokens_in,
                "tokens_out": stage.tokens_out,
                "cost_usd": stage.cost_usd,
            }
            for stage in cost.by_stage
        ],
    }


def version_summary(version: Version | VersionSummary) -> dict[str, Any]:
    summary = version.summary() if isinstance(version, Version) else version
    return {
        "id": str(summary.id),
        "number": summary.number,
        "origin": summary.origin.value,
        "created_at": _iso(summary.created_at),
        "label": summary.label,
        "checkpoint": summary.checkpoint,
        "lint_count": summary.lint_count,
        "assumption_count": summary.assumption_count,
        "run_id": str(summary.run_id) if summary.run_id else None,
    }


def project_detail(detail: ProjectDetail, role: str) -> dict[str, Any]:
    data = project_card(detail.view, role)
    data.update(
        {
            "sources": [source_view(source) for source in detail.sources],
            "questions": [question_view(question) for question in detail.questions],
            "latest_version": (
                version_summary(detail.latest_version) if detail.latest_version else None
            ),
            "active_run": run_view(detail.active_run) if detail.active_run else None,
            "questions_summary": asdict(detail.summary),
        }
    )
    return data


def uuid_or_404(value: str, what: str) -> UUID:
    """Идентификатор из аргумента MCP; кривой — понятная ошибка, а не трейсбек."""
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError) as error:
        raise InvalidInputError(f"Некорректный идентификатор: {what}") from error
