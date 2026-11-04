"""SQL-реализация ключей моделей пользователей."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update

from app.domain.credentials import LlmCredential
from app.infra.db_models import UserLlmCredentialRow
from app.infra.repositories.session import SessionFactory


def _credential(row: UserLlmCredentialRow) -> LlmCredential:
    return LlmCredential(
        id=row.id,
        user_id=row.user_id,
        provider=row.provider,
        label=row.label,
        base_url=row.base_url,
        encrypted_key=bytes(row.encrypted_key),
        key_hint=row.key_hint,
        default_model=row.default_model,
        is_default=row.is_default,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        last_error=row.last_error,
    )


class SqlLlmCredentialRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    async def list_by_user(self, user_id: UUID) -> list[LlmCredential]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(UserLlmCredentialRow)
                .where(UserLlmCredentialRow.user_id == user_id)
                .order_by(
                    UserLlmCredentialRow.is_default.desc(),
                    UserLlmCredentialRow.created_at,
                    UserLlmCredentialRow.id,
                )
            )
            return [_credential(row) for row in rows]

    async def get(self, credential_id: UUID) -> LlmCredential | None:
        async with self.sessions() as session:
            row = await session.get(UserLlmCredentialRow, credential_id)
            return _credential(row) if row else None

    async def count(self, user_id: UUID) -> int:
        async with self.sessions() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(UserLlmCredentialRow)
                    .where(UserLlmCredentialRow.user_id == user_id)
                )
                or 0
            )

    async def save(self, credential: LlmCredential) -> None:
        values = {
            "user_id": credential.user_id,
            "provider": credential.provider,
            "label": credential.label,
            "base_url": credential.base_url,
            "encrypted_key": credential.encrypted_key,
            "key_hint": credential.key_hint,
            "default_model": credential.default_model,
            "is_default": credential.is_default,
            "created_at": credential.created_at,
            "last_used_at": credential.last_used_at,
            "last_error": credential.last_error,
        }
        async with self.sessions.begin() as session:
            if credential.is_default:
                await session.execute(
                    update(UserLlmCredentialRow)
                    .where(
                        UserLlmCredentialRow.user_id == credential.user_id,
                        UserLlmCredentialRow.id != credential.id,
                    )
                    .values(is_default=False)
                )
            row = await session.get(UserLlmCredentialRow, credential.id)
            if row is None:
                session.add(UserLlmCredentialRow(id=credential.id, **values))
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
    ) -> LlmCredential | None:
        values: dict[str, object] = {}
        if label is not None:
            values["label"] = label
        if default_model is not None:
            values["default_model"] = default_model
        elif clear_default_model:
            values["default_model"] = None
        if is_default is not None:
            values["is_default"] = is_default
        async with self.sessions.begin() as session:
            row = await session.get(UserLlmCredentialRow, credential_id)
            if row is None:
                return None
            if is_default:
                await session.execute(
                    update(UserLlmCredentialRow)
                    .where(
                        UserLlmCredentialRow.user_id == row.user_id,
                        UserLlmCredentialRow.id != credential_id,
                    )
                    .values(is_default=False)
                )
            if values:
                # UPDATE только изменённых колонок: `last_used_at`/`last_error` не трогаем.
                await session.execute(
                    update(UserLlmCredentialRow)
                    .where(UserLlmCredentialRow.id == credential_id)
                    .values(**values)
                )
                await session.refresh(row)
            return _credential(row)

    async def delete(self, credential_id: UUID) -> bool:
        async with self.sessions.begin() as session:
            result = await session.execute(
                delete(UserLlmCredentialRow).where(UserLlmCredentialRow.id == credential_id)
            )
            return bool(getattr(result, "rowcount", 0))

    async def mark_used(self, credential_id: UUID, at: datetime, error: str | None) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(UserLlmCredentialRow)
                .where(UserLlmCredentialRow.id == credential_id)
                .values(last_used_at=at, last_error=error[:500] if error else None)
            )
