"""Ответы с пользовательским XML: только скачивание, никогда не исполняемая страница.

BPMN приходит от пользователей, поэтому в XML могут оказаться теги и скрипты. Браузер не должен
открывать такой ответ как документ: отдаём вложением, запрещаем угадывание типа и любые
ресурсы и скрипты (`sandbox`, `default-src 'none'`).
"""

from urllib.parse import quote

from fastapi import Response

XML_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
}


def bpmn_attachment(xml: str, *, number: int, title: str | None = None) -> Response:
    """`.bpmn` вложением. ASCII-имя — для старых клиентов, `filename*` — человекочитаемое."""
    disposition = f'attachment; filename="diagram-v{number}.bpmn"'
    if title:
        disposition += f"; filename*=UTF-8''{quote(f'{title} v{number}.bpmn')}"
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": disposition, **XML_HEADERS},
    )
