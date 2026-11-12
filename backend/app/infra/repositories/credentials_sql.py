"""SQL-реализация ключей пользователя по типам задач (RFC-0006)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update

from app.domain.capabilities import CredentialKind
from app.domain.credentials import MAX_ERROR_CHARS, Credential
from app.infra.db_models import UserCredentialRow
from app.infra.repositories.session import SessionFactory


def _credential(row: UserCredentialRow) -> Credential:
    return Credential(
        id=row.id,
        user_id=row.user_id,
        provider=row.provider,
        label=row.label,
        kinds=tuple(CredentialKind(kind) for kind in row.kinds),
        base_url=row.base_url,
        wire_api=row.wire_api,
        encrypted_key=bytes(row.encrypted_key),
        key_hint=row.key_hint,
        default_model=row.default_model,
        is_default=row.is_default,
        priority=row.priority,
        enabled=row.enabled,
        monthly_limit=dict(row.monthly_limit) if row.monthly_limit else None,
        exhausted_until=row.exhausted_until,
        last_error_code=row.last_error_code,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        last_error=row.last_error,
    )


class SqlCredentialRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    async def list_by_user(self, user_id: UUID) -> list[Credential]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(UserCredentialRow)
                .where(UserCredentialRow.user_id == user_id)
                .order_by(
                    UserCredentialRow.is_default.desc(),
                    UserCredentialRow.priority,
                    UserCredentialRow.created_at,
                    UserCredentialRow.id,
                )
            )
            return [_credential(row) for row in rows]

    async def get(self, credential_id: UUID) -> Credential | None:
        async with self.sessions() as session:
            row = await session.get(UserCredentialRow, credential_id)
            return _credential(row) if row else None

    async def count(self, user_id: UUID) -> int:
        async with self.sessions() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(UserCredentialRow)
                    .where(UserCredentialRow.user_id == user_id)
                )
                or 0
            )

    async def save(self, credential: Credential) -> None:
        values = {
            "user_id": credential.user_id,
            "kinds": [kind.value for kind in credential.kinds],
            "provider": credential.provider,
            "label": credential.label,
            "base_url": credential.base_url,
            "wire_api": credential.wire_api,
            "encrypted_key": credential.encrypted_key,
            "key_hint": credential.key_hint,
            "default_model": credential.default_model,
            "is_default": credential.is_default,
            "priority": credential.priority,
            "enabled": credential.enabled,
            "monthly_limit": credential.monthly_limit,
            "exhausted_until": credential.exhausted_until,
            "last_error_code": credential.last_error_code,
            "created_at": credential.created_at,
            "last_used_at": credential.last_used_at,
            "last_error": credential.last_error,
        }
        async with self.sessions.begin() as session:
            if credential.is_default:
                await session.execute(
                    update(UserCredentialRow)
                    .where(
                        UserCredentialRow.user_id == credential.user_id,
                        UserCredentialRow.id != credential.id,
                    )
                    .values(is_default=False)
                )
            row = await session.get(UserCredentialRow, credential.id)
            if row is None:
                session.add(UserCredentialRow(id=credential.id, **values))
            else:
                for name, value in values.items():
                    setattr(row, name, value)

    async def update_fields(
        self,
        credential_id: UUID,
        *,
        label: str | None = None,
        default_model: str | None = None,
        is_default: bool | None = None,
        clear_default_model: bool = False,
        priority: int | None = None,
        enabled: bool | None = None,
        monthly_limit: dict[str, float] | None = None,
        clear_monthly_limit: bool = False,
    ) -> Credential | None:
        values: dict[str, object] = {}
        if label is not None:
            values["label"] = label
        if default_model is not None:
            values["default_model"] = default_model
        elif clear_default_model:
            values["default_model"] = None
        if is_default is not None:
            values["is_default"] = is_default
        if priority is not None:
            values["priority"] = priority
        if enabled is not None:
            values["enabled"] = enabled
        if monthly_limit is not None:
            values["monthly_limit"] = monthly_limit
        elif clear_monthly_limit:
            values["monthly_limit"] = None
        async with self.sessions.begin() as session:
            row = await session.get(UserCredentialRow, credential_id)
            if row is None:
                return None
            if is_default:
                await session.execute(
                    update(UserCredentialRow)
                    .where(
                        UserCredentialRow.user_id == row.user_id,
                        UserCredentialRow.id != credential_id,
                    )
                    .values(is_default=False)
                )
            if values:
                # UPDATE только изменённых колонок: `last_used_at`/`last_error` не трогаем.
                await session.execute(
                    update(UserCredentialRow)
                    .where(UserCredentialRow.id == credential_id)
                    .values(**values)
                )
                await session.refresh(row)
            return _credential(row)

    async def delete(self, credential_id: UUID) -> bool:
        async with self.sessions.begin() as session:
            result = await session.execute(
                delete(UserCredentialRow).where(UserCredentialRow.id == credential_id)
            )
            return bool(getattr(result, "rowcount", 0))

    async def mark_used(
        self,
        credential_id: UUID,
        at: datetime,
        error: str | None,
        *,
        error_code: str | None = None,
    ) -> None:
        values: dict[str, object] = {
            "last_used_at": at,
            "last_error": error[:MAX_ERROR_CHARS] if error else None,
            "last_error_code": error_code,
        }
        if error is None:
            # Успешный вызов доказывает, что квота снова работает.
            values["exhausted_until"] = None
        async with self.sessions.begin() as session:
            await session.execute(
                update(UserCredentialRow)
                .where(UserCredentialRow.id == credential_id)
                .values(**values)
            )

    async def mark_failure(
        self,
        credential_id: UUID,
        at: datetime,
        *,
        error: str,
        error_code: str,
        exhausted_until: datetime | None = None,
        disable: bool = False,
    ) -> None:
        values: dict[str, object] = {
            "last_used_at": at,
            "last_error": error[:MAX_ERROR_CHARS],
            "last_error_code": error_code,
            "exhausted_until": exhausted_until,
        }
        if disable:
            values["enabled"] = False
        async with self.sessions.begin() as session:
            await session.execute(
                update(UserCredentialRow)
                .where(UserCredentialRow.id == credential_id)
                .values(**values)
            )
