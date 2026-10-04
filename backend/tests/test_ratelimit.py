"""Анти-спам лимиты: скользящее окно, IP-лимиты middleware и лимит дорогих вызовов."""

from fastapi.testclient import TestClient

from app.api.ratelimit import SlidingWindowLimiter
from app.config import Settings
from app.container import build_container
from app.main import create_app

API = "/api/v1"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _client(**overrides: object) -> TestClient:
    settings = Settings(
        mock_delay_scale=0,
        database_url=None,
        app_env="test",
        auth_enabled=False,
        rate_limit_enabled=True,
        **overrides,  # type: ignore[arg-type]
    )
    return TestClient(create_app(settings, container=build_container(settings)))


def test_sliding_window_blocks_then_releases() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(2, window=60, clock=clock)

    assert limiter.check("a") is None
    clock.now += 10
    assert limiter.check("a") is None
    assert limiter.check("b") is None  # ключи независимы
    wait = limiter.check("a")
    assert wait == 50  # слот первого запроса освободится через 50 с
    clock.now += 50.1
    assert limiter.check("a") is None


def test_limiter_evicts_idle_keys_when_full(monkeypatch) -> None:
    monkeypatch.setattr("app.api.ratelimit._MAX_KEYS", 3)
    clock = FakeClock()
    limiter = SlidingWindowLimiter(1, window=60, clock=clock)
    for key in "abc":
        assert limiter.check(key) is None
    clock.now += 61
    assert limiter.check("d") is None
    assert set(limiter._hits) == {"d"}


def test_limiter_evicts_oldest_active_key_when_all_are_busy(monkeypatch) -> None:
    monkeypatch.setattr("app.api.ratelimit._MAX_KEYS", 3)
    clock = FakeClock()
    limiter = SlidingWindowLimiter(1, window=60, clock=clock)
    for key in "abc":
        assert limiter.check(key) is None
        clock.now += 1
    assert limiter.check("d") is None  # все активны: вытеснен самый давний, размер ограничен
    assert list(limiter._hits) == ["b", "c", "d"]


def test_limiter_eviction_does_not_scan_all_keys(monkeypatch) -> None:
    monkeypatch.setattr("app.api.ratelimit._MAX_KEYS", 1000)
    clock = FakeClock()
    limiter = SlidingWindowLimiter(1, window=60, clock=clock)
    for index in range(5000):
        limiter.check(f"k{index}")
        clock.now += 0.001
    assert len(limiter._hits) <= 1000
    assert "k4999" in limiter._hits
    assert "k0" not in limiter._hits


def test_api_limit_per_ip_returns_429_with_retry_after() -> None:
    with _client(rate_limit_api_per_min=3) as client:
        statuses = [client.get(f"{API}/examples").status_code for _ in range(4)]
        assert statuses == [200, 200, 200, 429]
        limited = client.get(f"{API}/examples")
        assert limited.status_code == 429
        assert 1 <= int(limited.headers["retry-after"]) <= 60
        assert limited.json()["detail"].startswith("Слишком много запросов")
        # Не API (health) лимитом не затрагивается.
        assert client.get("/health").status_code == 200


def test_ip_comes_from_the_proxy_appended_forwarded_header() -> None:
    with _client(rate_limit_api_per_min=1) as client:
        first = client.get(f"{API}/examples", headers={"x-forwarded-for": "9.9.9.9, 10.0.0.1"})
        spoofed = client.get(f"{API}/examples", headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1"})
        again = client.get(f"{API}/examples", headers={"x-forwarded-for": "5.5.5.5, 10.0.0.1"})
        assert (first.status_code, spoofed.status_code, again.status_code) == (200, 429, 429)
        other = client.get(f"{API}/examples", headers={"x-forwarded-for": "5.5.5.5, 10.0.0.2"})
        assert other.status_code == 200


def test_login_and_register_have_a_stricter_limit() -> None:
    with _client(rate_limit_auth_per_min=2) as client:
        login = {"username": "a@example.com", "password": "x"}
        codes = [client.post(f"{API}/auth/session/login", data=login).status_code for _ in range(3)]
        assert codes[:2] == [503, 503]  # без PostgreSQL вход недоступен, но лимит уже считается
        assert codes[2] == 429
        register = client.post(f"{API}/auth/register", json={"email": "a@b.co", "password": "x"})
        assert register.status_code == 429  # общая корзина входа и регистрации
        assert client.get(f"{API}/examples").status_code == 200


def test_expensive_calls_are_limited_per_user() -> None:
    with _client(rate_limit_expensive_per_min=2) as client:
        audio = {"file": ("a.webm", b"1234", "audio/webm")}
        codes = [client.post(f"{API}/transcriptions", files=audio).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        response = client.post(f"{API}/transcriptions", files=audio)
        assert response.status_code == 429
        assert "retry-after" in response.headers


def test_expensive_calls_are_limited_per_ip_across_accounts() -> None:
    # Лимит на аккаунт щедрый, на IP — тугой: новые аккаунты с того же адреса его не обходят.
    with _client(rate_limit_expensive_per_min=100, rate_limit_expensive_ip_per_min=2) as client:
        audio = {"file": ("a.webm", b"1234", "audio/webm")}
        codes = [client.post(f"{API}/transcriptions", files=audio).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        other_ip = client.post(
            f"{API}/transcriptions", files=audio, headers={"x-forwarded-for": "7.7.7.7"}
        )
        assert other_ip.status_code == 200


def test_limits_can_be_disabled() -> None:
    settings = Settings(
        mock_delay_scale=0,
        database_url=None,
        auth_enabled=False,
        rate_limit_enabled=False,
        rate_limit_api_per_min=1,
    )
    with TestClient(create_app(settings, container=build_container(settings))) as client:
        assert {client.get(f"{API}/examples").status_code for _ in range(5)} == {200}
