"""Шифрование ключей моделей пользователей (ADR-0011): Fernet (AES-128-CBC + HMAC-SHA256).

Ключи сервера задаются `CREDENTIALS_ENCRYPTION_KEY` списком через запятую: первый шифрует,
все расшифровывают — так ключ ротируется без потери данных. В шифртекст зашит `user_id`,
поэтому строку нельзя перенести к другому пользователю. Открытое значение и ключи шифрования
не попадают в журналы и тексты ошибок.
"""

import logging
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from pydantic import SecretStr

logger = logging.getLogger(__name__)


class CredentialCipherError(RuntimeError):
    """Ключ нельзя расшифровать (сменился ключ сервера); сообщение безопасно для пользователя."""


class CredentialCipher:
    def __init__(self, keys: SecretStr | None, *, allow_ephemeral: bool) -> None:
        raw = [part.strip() for part in (keys.get_secret_value() if keys else "").split(",")]
        raw = [part for part in raw if part]
        self.ephemeral = False
        if not raw:
            if not allow_ephemeral:
                self._fernet: MultiFernet | None = None
                return
            logger.warning(
                "CREDENTIALS_ENCRYPTION_KEY не задан: ключи моделей шифруются временным ключом "
                "процесса и пропадут после перезапуска. В production это запрещено"
            )
            raw = [Fernet.generate_key().decode()]
            self.ephemeral = True
        try:
            self._fernet = MultiFernet([Fernet(part.encode()) for part in raw])
        except (ValueError, TypeError):
            raise ValueError(
                "CREDENTIALS_ENCRYPTION_KEY должен состоять из ключей Fernet (base64, 32 байта)"
            ) from None

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, user_id: UUID, api_key: str) -> bytes:
        if self._fernet is None:
            raise CredentialCipherError("Хранение ключей не настроено на сервере")
        return self._fernet.encrypt(f"{user_id}:{api_key}".encode())

    def decrypt(self, user_id: UUID, token: bytes) -> SecretStr:
        if self._fernet is None:
            raise CredentialCipherError("Хранение ключей не настроено на сервере")
        try:
            plain = self._fernet.decrypt(token).decode()
        except (InvalidToken, UnicodeDecodeError):
            raise CredentialCipherError(
                "Ключ нельзя расшифровать: ключ шифрования сервера изменился. Добавьте ключ заново"
            ) from None
        prefix = f"{user_id}:"
        if not plain.startswith(prefix):
            raise CredentialCipherError("Ключ принадлежит другому аккаунту")
        return SecretStr(plain.removeprefix(prefix))
