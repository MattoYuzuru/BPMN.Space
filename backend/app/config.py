"""Единственный источник конфигурации backend. Все значения — из окружения / `.env`."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_MB = 1024 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    app_env: str = "dev"
    database_url: str | None = None
    upload_dir: str = "/data/uploads"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]
    auth_enabled: bool = True
    # Secure у session- и CSRF-cookie: None — включить в production (`APP_ENV=prod|production`).
    # Явное true/false нужно, когда HTTPS ещё нет (false) или TLS завершается снаружи (true).
    session_cookie_secure: bool | None = None

    # --- Анти-спам лимиты (скользящее окно в памяти процесса, запросов в минуту) ---
    # Намеренно щедрые: защита от скриптов и подбора пароля, а не ограничение продукта.
    rate_limit_enabled: bool = True
    rate_limit_api_per_min: int = 600  # весь API, на IP
    rate_limit_auth_per_min: int = 20  # вход и регистрация, на IP
    rate_limit_expensive_per_min: int = 60  # прогоны, помощник, расшифровка, загрузка, на аккаунт

    # --- Прогоны (RFC §5.1) ---
    max_concurrent_runs: int = 2

    # --- Ограничения загрузок ---
    max_upload_bytes: int = 20 * _MB
    max_audio_bytes: int = 60 * _MB
    max_diagram_bytes: int = 5 * _MB
    max_text_chars: int = 200_000
    # Разбор документов: у PDF ограничены число страниц и время (в отдельном потоке).
    max_pdf_pages: int = 300
    parse_timeout_sec: float = 60.0

    # --- Mock-реализация (#2): задержки имитируют работу модели и STT ---
    # Множитель всех задержек: 0 — мгновенно (тесты), 1 — как в демо.
    mock_delay_scale: float = 1.0
    # Секунды на этап прогона; анализ ≈ 5 с, сборка ≈ 7,5 с.
    mock_stage_delays: dict[str, float] = {
        "reading_sources": 1.0,
        "extracting": 2.4,
        "reconciling": 1.6,
        "structuring": 1.2,
        "validating": 0.6,
        "layout": 0.7,
    }
    mock_transcription_delay_sec: float = 1.0
    mock_parse_delay_sec: float = 1.5
    # Засевать ли демо-проекты при старте (в тестах можно выключить).
    seed_demo_data: bool = True

    # Внешние провайдеры выключены по умолчанию. Секреты задаются только в корневом .env.
    llm_provider: str = "mock"
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_timeout_sec: float = 120.0
    deepseek_thinking_enabled: bool = False
    stt_provider: str = "mock"
    deepgram_api_key: str | None = None

    @property
    def cookie_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.app_env.lower() in {"prod", "production"}

    def mock_delay(self, seconds: float) -> float:
        return max(seconds, 0.0) * max(self.mock_delay_scale, 0.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
