"""Фильтры журнала: секреты не должны попадать в логи.

Токен ссылки «поделиться» стоит в пути (`/api/v1/shares/<токен>/…`), а access-лог uvicorn
пишет путь целиком. Токен — это доступ к проекту, поэтому в журнале он заменяется на `***`.
"""

import logging
import re

_SHARE_TOKEN = re.compile(r"(/shares/)[^/?#\s\"']+")
MASK = r"\1***"


def mask_share_token(text: str) -> str:
    """`/api/v1/shares/abc/versions/1/xml` → `/api/v1/shares/***/versions/1/xml`."""
    return _SHARE_TOKEN.sub(MASK, text)


class ShareTokenFilter(logging.Filter):
    """Маскирует токен ссылки в записях `uvicorn.access` (путь — третий аргумент записи)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                mask_share_token(arg) if isinstance(arg, str) else arg for arg in record.args
            )
        if isinstance(record.msg, str):
            record.msg = mask_share_token(record.msg)
        return True


def install_log_filters() -> None:
    """Повесить фильтры на логгеры; повторный вызов ничего не дублирует."""
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, ShareTokenFilter) for item in logger.filters):
        logger.addFilter(ShareTokenFilter())
