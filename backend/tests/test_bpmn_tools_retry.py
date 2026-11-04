"""HttpBpmnTools повторяет 503 и обрыв соединения, но не скрывает постоянные ошибки."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.fixtures import read_bpmn
from app.infra.bpmn_tools import BpmnToolsError, BpmnToolsInputError, HttpBpmnTools

XML = read_bpmn("logistics_order")


@pytest.fixture
def flaky():
    """Сервер, отвечающий заданной последовательностью статусов; счётчик запросов."""
    state = {"script": [], "calls": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", 0)))
            state["calls"] += 1
            step = state["script"].pop(0) if state["script"] else 200
            status, extra = step if isinstance(step, tuple) else (step, {})
            payload = {"xml": XML} if status == 200 else {"detail": "x", **extra}
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_busy_503_is_retried_until_success(flaky):
    state, url = flaky
    state["script"] = [503, 503]
    tools = HttpBpmnTools(url, backoff_sec=0.01)
    assert "BPMNPlane" in await tools.layout(XML)
    assert state["calls"] == 3


@pytest.mark.asyncio
async def test_persistent_503_fails_after_bounded_retries(flaky):
    state, url = flaky
    state["script"] = [503] * 10
    with pytest.raises(BpmnToolsError, match="503"):
        await HttpBpmnTools(url, backoff_sec=0.01, retries=2).layout(XML)
    assert state["calls"] == 3


@pytest.mark.asyncio
async def test_input_error_and_gateway_timeout_are_not_retried(flaky):
    state, url = flaky
    state["script"] = [422]
    with pytest.raises(BpmnToolsInputError):
        await HttpBpmnTools(url, backoff_sec=0.01).layout(XML)
    assert state["calls"] == 1
    state["script"] = [504]
    with pytest.raises(BpmnToolsError, match="504"):
        await HttpBpmnTools(url, backoff_sec=0.01).layout(XML)
    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_connection_refused_is_retried_then_explicit_failure():
    tools = HttpBpmnTools("http://127.0.0.1:1", timeout_sec=0.2, retries=1, backoff_sec=0.01)
    with pytest.raises(BpmnToolsError, match="связаться"):
        await tools.layout(XML)


@pytest.mark.asyncio
async def test_worker_crash_503_is_not_retried(flaky):
    state, url = flaky
    state["script"] = [(503, {"code": "crash"})]
    with pytest.raises(BpmnToolsError, match="503"):
        await HttpBpmnTools(url, backoff_sec=0.01, retries=2).layout(XML)
    assert state["calls"] == 1


@pytest.mark.asyncio
async def test_busy_code_503_is_still_retried(flaky):
    state, url = flaky
    state["script"] = [(503, {"code": "busy"})]
    assert "BPMNPlane" in await HttpBpmnTools(url, backoff_sec=0.01).layout(XML)
    assert state["calls"] == 2
