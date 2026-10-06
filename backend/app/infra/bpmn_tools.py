"""Внутренний HTTP-порт layout/bpmnlint; ограниченный mock выбирается только явно локально."""

import asyncio
import json
from contextvars import ContextVar
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app.domain.bpmn.document import BpmnFormatError, parse_bpmn
from app.domain.bpmn.lint import lint_document
from app.domain.models import LintIssue, LintSeverity

HTTP_INPUT_ERROR = 422
MAX_ISSUES = 1000


class BpmnToolsError(ValueError):
    """Сервис недоступен или ответ не прошёл проверку. Не превращается в фальшивый успех."""


class BpmnToolsInputError(BpmnFormatError):
    """Сервис отверг некорректный BPMN XML."""


class BpmnTools(Protocol):
    async def layout(self, xml: str) -> str: ...
    async def lint(self, xml: str) -> list[LintIssue]: ...


class HttpBpmnTools:
    quality = "full"

    def __init__(self, url: str, *, timeout_sec: float = 20, max_bytes: int = 5 * 1024 * 1024):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("BPMN_TOOLS_URL должен быть HTTP(S)-адресом без ключей и параметров")
        self._url = url.rstrip("/")
        self._timeout = timeout_sec
        self._max_bytes = max_bytes
        self._warnings: ContextVar[tuple[str, ...]] = ContextVar("bpmn_tools_warnings", default=())

    def warnings(self) -> list[str]:
        return list(self._warnings.get())

    async def _call(self, operation: str, xml: str) -> dict:
        if len(xml.encode()) > self._max_bytes:
            raise BpmnToolsInputError("Схема превышает лимит внутреннего сервиса")
        # Отмена освобождает await; urllib-поток всё равно имеет конечный socket timeout.
        try:
            async with asyncio.timeout(self._timeout + 1):
                result = await asyncio.to_thread(self._request, operation, xml)
        except TimeoutError:
            raise BpmnToolsError("Сервис проверки схемы не ответил в отведённое время") from None
        if not isinstance(result, dict):
            raise BpmnToolsError("Сервис проверки схемы вернул некорректный ответ")
        return result

    def _request(self, operation: str, xml: str) -> dict:
        request = Request(  # noqa: S310 — URL проверен в __init__, задаётся оператором
            f"{self._url}/{operation}",
            data=json.dumps({"xml": xml}, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:  # noqa: S310 — URL задаёт оператор
                data = response.read(self._max_bytes * 2 + 1)
                if len(data) > self._max_bytes * 2:
                    raise BpmnToolsError("Ответ сервиса проверки слишком большой")
                return json.loads(data)
        except HTTPError as error:
            if error.code == HTTP_INPUT_ERROR:
                raise BpmnToolsInputError(
                    "Сервис проверки отверг BPMN XML: проверьте элементы и ссылки"
                ) from None
            raise BpmnToolsError(f"Сервис проверки схемы недоступен (HTTP {error.code})") from None
        except (URLError, TimeoutError, OSError):
            raise BpmnToolsError("Не удалось связаться с сервисом проверки схемы") from None
        except (ValueError, UnicodeError):
            raise BpmnToolsError("Сервис проверки схемы вернул некорректный JSON") from None

    async def layout(self, xml: str) -> str:
        result = await self._call("layout", xml)
        value = result.get("xml")
        if not isinstance(value, str) or len(value.encode()) > self._max_bytes:
            raise BpmnToolsError("Сервис раскладки не вернул допустимый BPMN XML")
        if not parse_bpmn(value).has_layout:
            raise BpmnToolsError("После раскладки в схеме отсутствуют координаты")
        warnings = result.get("warnings", [])
        if not isinstance(warnings, list) or any(not isinstance(w, str) for w in warnings):
            raise BpmnToolsError("Некорректные предупреждения сервиса раскладки")
        self._warnings.set(tuple(w[:400] for w in warnings[:30]))
        return value

    async def lint(self, xml: str) -> list[LintIssue]:
        result = await self._call("lint", xml)
        issues = result.get("issues")
        if not isinstance(issues, list) or len(issues) > MAX_ISSUES:
            raise BpmnToolsError("Сервис проверки не вернул список правил")
        try:
            return [
                LintIssue(
                    rule=str(item["rule"])[:200],
                    message=str(item["message"])[:500],
                    element_id=item["element_id"],
                    severity=LintSeverity(item["severity"]),
                )
                for item in issues
            ]
        except (KeyError, ValueError, TypeError):
            raise BpmnToolsError("Результат линтинга имеет неизвестный формат") from None


class MockBpmnTools:
    quality = "limited"

    async def layout(self, xml: str) -> str:
        if not parse_bpmn(xml).has_layout:
            raise BpmnToolsError(
                "Для схемы без координат (DI) нужен runtime bpmn-tools: укажите BPMN_TOOLS_URL"
            )
        return xml

    async def lint(self, xml: str) -> list[LintIssue]:
        return lint_document(parse_bpmn(xml))
