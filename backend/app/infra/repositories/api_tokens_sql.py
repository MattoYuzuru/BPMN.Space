"""SQL-реализация персональных токенов доступа (RFC-0007)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update

from app.domain.api_tokens import ApiScope, ApiToken
from app.infra.db_models import ApiTokenRow
from app.infra.repositories.session import SessionFactory


def _token(row: ApiTokenRow) -> ApiToken:
    return ApiToken(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        token_prefix=row.token_prefix,
        token_hash=row.token_hash,
        scopes=tuple(ApiScope(scope) for scope in row.scopes),
        project_ids=tuple(row.project_ids) if row.project_ids is not None else None,
        expires_at=row.expires_at,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
    )


class SqlApiTokenRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    async def list_by_user(self, user_id: UUID) -> list[ApiToken]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ApiTokenRow)
                .where(ApiTokenRow.user_id == user_id, ApiTokenRow.revoked_at.is_(None))
                .order_by(ApiTokenRow.created_at.desc(), ApiTokenRow.id.desc())
            )
            return [_token(row) for row in rows]

    async def get(self, token_id: UUID) -> ApiToken | None:
        async with self.sessions() as session:
            row = await session.get(ApiTokenRow, token_id)
            return _token(row) if row else None

    async def by_hash(self, token_hash: str) -> ApiToken | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(ApiTokenRow).where(ApiTokenRow.token_hash == token_hash)
            )
            return _token(row) if row else None

    async def count_active(self, user_id: UUID, now: datetime) -> int:
        async with self.sessions() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(ApiTokenRow)
                    .where(
                        ApiTokenRow.user_id == user_id,
                        ApiTokenRow.revoked_at.is_(None),
                        ApiTokenRow.expires_at > now,
                    )
                )
                or 0
            )

    async def add(self, token: ApiToken) -> None:
        async with self.sessions.begin() as session:
            session.add(
                ApiTokenRow(
                    id=token.id,
                    user_id=token.user_id,
                    name=token.name,
                    token_prefix=token.token_prefix,
                    token_hash=token.token_hash,
                    scopes=[scope.value for scope in token.scopes],
                    project_ids=list(token.project_ids) if token.project_ids is not None else None,
                    expires_at=token.expires_at,
                    created_at=token.created_at,
                    last_used_at=token.last_used_at,
                    revoked_at=token.revoked_at,
                )
            )

    async def revoke(self, token_id: UUID, at: datetime) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(ApiTokenRow)
                .where(ApiTokenRow.id == token_id, ApiTokenRow.revoked_at.is_(None))
                .values(revoked_at=at)
            )

    async def touch(self, token_id: UUID, at: datetime, *, older_than: datetime) -> None:
        # Условие в самом UPDATE: параллельные запросы одного агента не пишут строку повторно.
        async with self.sessions.begin() as session:
            await session.execute(
                update(ApiTokenRow)
                .where(
                    ApiTokenRow.id == token_id,
                    or_(ApiTokenRow.last_used_at.is_(None), ApiTokenRow.last_used_at < older_than),
                )
                .values(last_used_at=at)
            )
