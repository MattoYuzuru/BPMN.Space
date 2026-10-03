"""SQLAlchemy-репозитории PostgreSQL, сохраняющие публичные dataclass-ы domain."""

from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.models import (
    Answer,
    AssumptionMark,
    LintIssue,
    LintSeverity,
    LlmCall,
    Project,
    Question,
    QuestionKind,
    QuestionStatus,
    Quote,
    Report,
    Run,
    RunMode,
    RunStage,
    RunStatus,
    RunSummary,
    Severity,
    Source,
    SourceKind,
    SourceStatus,
    Version,
    VersionDiff,
    VersionOrigin,
)
from app.domain.questions import normalize
from app.domain.runs import ACTIVE_STATUSES
from app.infra.db_models import (
    DiagramVersionRow,
    LlmCallRow,
    ProjectRow,
    QuestionRow,
    RunRow,
    SourceRow,
)
from app.infra.repositories.base import ActiveRunConflictError, PageKey, Repositories

type SessionFactory = async_sessionmaker[AsyncSession]


def _quote(value: dict[str, Any] | None) -> Quote | None:
    return Quote(source_id=UUID(value["source_id"]), quote=value["quote"]) if value else None


def _quote_json(value: Quote | None) -> dict[str, str] | None:
    return {"source_id": str(value.source_id), "quote": value.quote} if value else None


def _project(row: ProjectRow) -> Project:
    return Project(
        id=row.id,
        title=row.title,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _source(row: SourceRow) -> Source:
    return Source(
        id=row.id,
        project_id=row.project_id,
        kind=SourceKind(row.kind),
        title=row.title,
        content=row.content,
        status=SourceStatus(row.status),
        active=row.active,
        created_at=row.created_at,
        file_name=row.file_name,
        mime=row.mime,
        size_bytes=row.size_bytes,
        duration_sec=row.duration_sec,
        question_id=row.question_id,
        error=row.error,
        file_key=row.file_key,
        digest=row.digest,
    )


def _question(row: QuestionRow) -> Question:
    answer = (
        Answer(source_id=row.answer_source_id, text=row.answer_text or "")
        if row.answer_source_id
        else None
    )
    return Question(
        id=row.id,
        project_id=row.project_id,
        code=row.code,
        kind=QuestionKind(row.kind),
        severity=Severity(row.severity),
        status=QuestionStatus(row.status),
        text=row.text,
        assumption=row.assumption,
        created_at=row.created_at,
        updated_at=row.updated_at,
        about=_quote(row.about),
        evidence=_quote(row.evidence),
        element_ids=list(row.element_ids),
        answer=answer,
        run_id=row.run_id,
    )


def _run(row: RunRow) -> Run:
    summary = RunSummary(**row.summary) if row.summary else None
    return Run(
        id=row.id,
        project_id=row.project_id,
        mode=RunMode(row.mode),
        status=RunStatus(row.status),
        started_at=row.started_at,
        stage=RunStage(row.stage) if row.stage else None,
        progress=row.progress,
        finished_at=row.finished_at,
        summary=summary,
        version_id=row.version_id,
        error=row.error,
        analysis=row.analysis,
        ir=row.ir,
        report=row.report,
        model=row.model,
        latency_ms=row.latency_ms,
    )


def _version(row: DiagramVersionRow) -> Version:
    report_json = row.report
    report = Report(
        xsd_valid=report_json["xsd_valid"],
        lint=[
            LintIssue(
                rule=item["rule"],
                message=item["message"],
                severity=LintSeverity(item["severity"]),
                element_id=item.get("element_id"),
            )
            for item in report_json.get("lint", [])
        ],
        assumptions=[
            AssumptionMark(
                element_id=item["element_id"],
                question_id=UUID(item["question_id"]),
                text=item["text"],
            )
            for item in report_json.get("assumptions", [])
        ],
    )
    trace = {
        element_id: Quote(source_id=UUID(value["source_id"]), quote=value["quote"])
        for element_id, value in row.trace.items()
    }
    return Version(
        id=row.id,
        project_id=row.project_id,
        number=row.number,
        origin=VersionOrigin(row.origin),
        created_at=row.created_at,
        xml=row.bpmn_xml,
        diff=VersionDiff(**row.diff),
        report=report,
        trace=trace,
        lanes=list(row.lanes),
        run_id=row.run_id,
    )


class SqlProjectRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    async def add(self, project: Project) -> None:
        async with self.sessions.begin() as session:
            session.add(
                ProjectRow(
                    id=project.id,
                    title=project.title,
                    description=project.description,
                    created_at=project.created_at,
                    updated_at=project.updated_at,
                )
            )

    async def get(self, project_id: UUID) -> Project | None:
        async with self.sessions() as session:
            row = await session.get(ProjectRow, project_id)
            return _project(row) if row else None

    async def update(self, project: Project) -> None:
        async with self.sessions.begin() as session:
            await session.merge(
                ProjectRow(
                    id=project.id,
                    title=project.title,
                    description=project.description,
                    created_at=project.created_at,
                    updated_at=project.updated_at,
                )
            )

    async def delete(self, project_id: UUID) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(ProjectRow, project_id)
            if row:
                await session.delete(row)

    def _filters(self, query: str | None) -> list[Any]:
        if not query:
            return []
        normalized = normalize(query)
        title = func.replace(func.lower(ProjectRow.title), "ё", "е")
        return [title.contains(normalized)]

    async def list_page(
        self, *, query: str | None, after: PageKey | None, limit: int
    ) -> list[Project]:
        async with self.sessions() as session:
            statement = select(ProjectRow).where(*self._filters(query))
            if after:
                statement = statement.where(
                    or_(
                        ProjectRow.updated_at < after[0],
                        and_(ProjectRow.updated_at == after[0], ProjectRow.id < after[1]),
                    )
                )
            rows = (
                await session.scalars(
                    statement.order_by(ProjectRow.updated_at.desc(), ProjectRow.id.desc()).limit(
                        limit
                    )
                )
            ).all()
            return [_project(row) for row in rows]

    async def count(self, *, query: str | None) -> int:
        async with self.sessions() as session:
            return int(
                await session.scalar(
                    select(func.count()).select_from(ProjectRow).where(*self._filters(query))
                )
                or 0
            )


class SqlSourceRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    @staticmethod
    def _row(item: Source) -> SourceRow:
        return SourceRow(
            id=item.id,
            project_id=item.project_id,
            kind=item.kind.value,
            title=item.title,
            content=item.content,
            status=item.status.value,
            active=item.active,
            created_at=item.created_at,
            file_name=item.file_name,
            mime=item.mime,
            size_bytes=item.size_bytes,
            duration_sec=item.duration_sec,
            question_id=item.question_id,
            error=item.error,
            file_key=item.file_key,
            digest=item.digest,
        )

    async def add(self, source: Source) -> None:
        async with self.sessions.begin() as session:
            session.add(self._row(source))

    async def get(self, source_id: UUID) -> Source | None:
        async with self.sessions() as session:
            row = await session.get(SourceRow, source_id)
            return _source(row) if row else None

    async def update(self, source: Source) -> None:
        async with self.sessions.begin() as session:
            await session.merge(self._row(source))

    async def delete(self, source_id: UUID) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(SourceRow, source_id)
            if row:
                await session.delete(row)

    async def list_by_project(self, project_id: UUID) -> list[Source]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(SourceRow)
                    .where(SourceRow.project_id == project_id)
                    .order_by(SourceRow.created_at, SourceRow.id)
                )
            ).all()
            return [_source(row) for row in rows]

    async def delete_by_project(self, project_id: UUID) -> None:
        async with self.sessions.begin() as session:
            rows = (
                await session.scalars(select(SourceRow).where(SourceRow.project_id == project_id))
            ).all()
            for row in rows:
                await session.delete(row)


class SqlQuestionRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    @staticmethod
    def _row(item: Question) -> QuestionRow:
        return QuestionRow(
            id=item.id,
            project_id=item.project_id,
            code=item.code,
            kind=item.kind.value,
            severity=item.severity.value,
            status=item.status.value,
            text=item.text,
            assumption=item.assumption,
            created_at=item.created_at,
            updated_at=item.updated_at,
            about=_quote_json(item.about),
            evidence=_quote_json(item.evidence),
            element_ids=item.element_ids,
            answer_source_id=item.answer.source_id if item.answer else None,
            answer_text=item.answer.text if item.answer else None,
            run_id=item.run_id,
        )

    async def add(self, question: Question) -> None:
        async with self.sessions.begin() as session:
            session.add(self._row(question))

    async def get(self, question_id: UUID) -> Question | None:
        async with self.sessions() as session:
            row = await session.get(QuestionRow, question_id)
            return _question(row) if row else None

    async def update(self, question: Question) -> None:
        async with self.sessions.begin() as session:
            await session.merge(self._row(question))

    async def list_by_project(
        self, project_id: UUID, *, status: QuestionStatus | None = None
    ) -> list[Question]:
        async with self.sessions() as session:
            statement = select(QuestionRow).where(QuestionRow.project_id == project_id)
            if status:
                statement = statement.where(QuestionRow.status == status.value)
            rows = (await session.scalars(statement.order_by(QuestionRow.code))).all()
            return [_question(row) for row in rows]

    async def delete_by_project(self, project_id: UUID) -> None:
        async with self.sessions.begin() as session:
            rows = (
                await session.scalars(
                    select(QuestionRow).where(QuestionRow.project_id == project_id)
                )
            ).all()
            for row in rows:
                await session.delete(row)


class SqlRunRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    @staticmethod
    def _row(item: Run) -> RunRow:
        summary = (
            {
                name: getattr(item.summary, name)
                for name in ("resolved", "open", "new", "ignored", "answered")
            }
            if item.summary
            else None
        )
        return RunRow(
            id=item.id,
            project_id=item.project_id,
            mode=item.mode.value,
            status=item.status.value,
            started_at=item.started_at,
            stage=item.stage.value if item.stage else None,
            progress=item.progress,
            finished_at=item.finished_at,
            summary=summary,
            version_id=item.version_id,
            error=item.error,
            analysis=item.analysis,
            ir=item.ir,
            report=item.report,
            model=item.model,
            latency_ms=item.latency_ms,
        )

    async def add(self, run: Run) -> None:
        try:
            async with self.sessions.begin() as session:
                session.add(self._row(run))
        except IntegrityError as error:
            original = error.orig
            constraint_name = getattr(original, "constraint_name", None) or getattr(
                getattr(original, "diag", None), "constraint_name", None
            )
            if constraint_name == "uq_runs_active_project" or (
                "uq_runs_active_project" in str(original)
            ):
                raise ActiveRunConflictError from error
            raise

    async def get(self, run_id: UUID) -> Run | None:
        async with self.sessions() as session:
            row = await session.get(RunRow, run_id)
            return _run(row) if row else None

    async def update(self, run: Run) -> None:
        async with self.sessions.begin() as session:
            await session.merge(self._row(run))

    async def list_by_project(self, project_id: UUID) -> list[Run]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(RunRow)
                    .where(RunRow.project_id == project_id)
                    .order_by(RunRow.started_at, RunRow.id)
                )
            ).all()
            return [_run(row) for row in rows]

    async def active_for_project(self, project_id: UUID) -> Run | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(RunRow)
                .where(
                    RunRow.project_id == project_id,
                    RunRow.status.in_([status.value for status in ACTIVE_STATUSES]),
                )
                .limit(1)
            )
            return _run(row) if row else None

    async def delete_by_project(self, project_id: UUID) -> None:
        async with self.sessions.begin() as session:
            rows = (
                await session.scalars(select(RunRow).where(RunRow.project_id == project_id))
            ).all()
            for row in rows:
                await session.delete(row)


class SqlVersionRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    @staticmethod
    def _row(item: Version) -> DiagramVersionRow:
        return DiagramVersionRow(
            id=item.id,
            project_id=item.project_id,
            number=item.number,
            origin=item.origin.value,
            created_at=item.created_at,
            bpmn_xml=item.xml,
            diff={name: getattr(item.diff, name) for name in ("added", "removed", "changed")},
            report={
                "xsd_valid": item.report.xsd_valid,
                "lint": [
                    {
                        "rule": issue.rule,
                        "message": issue.message,
                        "severity": issue.severity.value,
                        "element_id": issue.element_id,
                    }
                    for issue in item.report.lint
                ],
                "assumptions": [
                    {
                        "element_id": mark.element_id,
                        "question_id": str(mark.question_id),
                        "text": mark.text,
                    }
                    for mark in item.report.assumptions
                ],
            },
            trace={key: _quote_json(value) for key, value in item.trace.items()},
            lanes=item.lanes,
            run_id=item.run_id,
        )

    async def add(self, version: Version) -> None:
        async with self.sessions.begin() as session:
            session.add(self._row(version))

    async def get(self, version_id: UUID) -> Version | None:
        async with self.sessions() as session:
            row = await session.get(DiagramVersionRow, version_id)
            return _version(row) if row else None

    async def list_by_project(self, project_id: UUID) -> list[Version]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(DiagramVersionRow)
                    .where(DiagramVersionRow.project_id == project_id)
                    .order_by(DiagramVersionRow.number.desc())
                )
            ).all()
            return [_version(row) for row in rows]

    async def latest(self, project_id: UUID) -> Version | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(DiagramVersionRow)
                .where(DiagramVersionRow.project_id == project_id)
                .order_by(DiagramVersionRow.number.desc())
                .limit(1)
            )
            return _version(row) if row else None

    async def delete_by_project(self, project_id: UUID) -> None:
        async with self.sessions.begin() as session:
            rows = (
                await session.scalars(
                    select(DiagramVersionRow).where(DiagramVersionRow.project_id == project_id)
                )
            ).all()
            for row in rows:
                await session.delete(row)


class SqlLlmCallRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    async def add(self, call: LlmCall) -> None:
        async with self.sessions.begin() as session:
            session.add(
                LlmCallRow(
                    id=call.id,
                    run_id=call.run_id,
                    stage=call.stage,
                    request=call.request,
                    response=call.response,
                    tokens_in=call.tokens_in,
                    tokens_out=call.tokens_out,
                    latency_ms=call.latency_ms,
                )
            )


class SqlStore:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def repositories(self) -> Repositories:
        return Repositories(
            projects=SqlProjectRepository(self._sessions),
            sources=SqlSourceRepository(self._sessions),
            questions=SqlQuestionRepository(self._sessions),
            runs=SqlRunRepository(self._sessions),
            versions=SqlVersionRepository(self._sessions),
            llm_calls=SqlLlmCallRepository(self._sessions),
        )
