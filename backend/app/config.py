"""Единственный источник конфигурации backend. Все значения — из окружения / `.env`."""

import logging
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)
_MB = 1024 * 1024
# Квитанции удаления доступны 30 дней; содержимое проектов удаляется сразу.
DELETED_PROJECT_NOTICE_DAYS = 30


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    app_env: str = "dev"
    database_url: str | None = None
    # One API worker: bounded pool sized for ordinary request bursts, with a short wait so
    # exhausted capacity fails visibly instead of making the UI appear frozen for 30 seconds.
    database_pool_size: int = 10
    database_max_overflow: int = 10
    database_pool_timeout_sec: float = 5.0
    upload_dir: str = "/data/uploads"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]
    auth_enabled: bool = True
    # Обучение и чек-лист «Начало работы»: работают только вместе с аккаунтами (`auth_enabled`).
    onboarding_enabled: bool = True
    # Secure у session- и CSRF-cookie: None — включить в production (`APP_ENV=prod|production`).
    # Явное true/false нужно, когда HTTPS ещё нет (false) или TLS завершается снаружи (true).
    session_cookie_secure: bool | None = None

    # --- Анти-спам лимиты (скользящее окно в памяти процесса, запросов в минуту) ---
    # Намеренно щедрые: защита от скриптов и подбора пароля, а не ограничение продукта.
    rate_limit_enabled: bool = True
    rate_limit_api_per_min: int = 600  # весь API, на IP
    rate_limit_auth_per_min: int = 20  # вход и регистрация, на IP
    rate_limit_expensive_per_min: int = 60  # прогоны, помощник, расшифровка, загрузка, на аккаунт
    rate_limit_expensive_ip_per_min: int = 120  # те же вызовы суммарно с одного IP (все аккаунты)

    # В Compose всегда настоящий внутренний Node-сервис. None — ограниченный локальный mock.
    bpmn_tools_url: str | None = None
    bpmn_tools_timeout_sec: float = Field(default=20.0, gt=0, le=120)

    # --- Прогоны (RFC §5.1) ---
    max_concurrent_runs: int = 2
    # Общий срок одного прогона (секунды, 0 — без срока): новые запросы к модели после него
    # не начинаются, прогон завершается ошибкой, а не висит.
    run_deadline_sec: float = 600.0
    # Анализ: бюджет одного запроса целиком, включая schema; полные источники идут порциями.
    # Построение: бюджет оснований после порционного извлечения; переполнение — явный отказ.
    llm_context_budget_chars: int = 120_000

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
    # Засевать ли демо-проекты при старте. None — по окружению: в production выключено,
    # иначе включено (в тестах можно выключить явно).
    seed_demo_data: bool | None = None

    # Внешние провайдеры выключены по умолчанию. Секреты задаются только в корневом .env.
    llm_provider: str = "mock"
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout_sec: float = 120.0
    llm_json_mode: bool = True
    llm_semantic_review: bool = True
    # Настраивается под ограничения провайдера; незавершённый length-ответ не применяется.
    llm_json_max_tokens: int = Field(default=16384, ge=256, le=131_072)
    # Температура для JSON-ответов (анализ, сборка). Дефолт провайдера (DeepSeek — 1.0)
    # даёт редкие ответы не по схеме; 0.0 — рекомендация DeepSeek для структурированного вывода.
    llm_json_temperature: float | None = 0.0
    llm_max_retries: int = 3
    llm_retry_base_sec: float = 1.0
    llm_retry_max_sec: float = 30.0
    # Глубина рассуждения Anthropic (`output_config.effort`): low | medium | high.
    llm_anthropic_effort: str = "medium"
    # Ключи моделей пользователей (ADR-0011): Fernet-ключи через запятую; первый шифрует,
    # все расшифровывают (ротация). Сгенерировать: `make credentials-key`. В production без
    # него пользовательские ключи не принимаются; в dev берётся временный ключ процесса.
    credentials_encryption_key: SecretStr | None = None
    # Хосты закрытых сетей, к которым разрешено ходить совместимым провайдерам пользователей
    # (локальный vLLM/Ollama в dev). Пусто — только публичные адреса по HTTPS.
    llm_allowed_private_hosts: Annotated[list[str], NoDecode] = []
    # Сколько секунд хранить список моделей аккаунта пользователя.
    llm_models_cache_sec: float = 300.0
    # Старые имена оставлены для плавного перехода production .env с DeepSeek.
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_timeout_sec: float = 120.0
    # Рассуждение DeepSeek съедает лимит ответа и обрезает JSON, поэтому по умолчанию выключено.
    deepseek_thinking_enabled: bool = False
    # Повторы временных сбоев (HTTP 408/429/5xx, таймаут, обрыв сети): экспоненциальная пауза
    # с джиттером от `base` до `max` секунд, `Retry-After` провайдера учитывается.
    deepseek_max_retries: int = 3
    deepseek_retry_base_sec: float = 1.0
    deepseek_retry_max_sec: float = 30.0
    stt_provider: str = "mock"
    deepgram_api_key: SecretStr | None = None

    @field_validator(
        "database_url",
        "bpmn_tools_url",
        "session_cookie_secure",
        "llm_api_key",
        "deepseek_api_key",
        "deepgram_api_key",
        "credentials_encryption_key",
        "seed_demo_data",
        mode="before",
    )
    @classmethod
    def _empty_as_none(cls, value: object) -> object:
        """Пустое значение переменной (`NAME=` в .env или compose) значит «не задано»."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("llm_allowed_private_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip().lower() for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def _resolve_defaults(self) -> "Settings":
        if self.seed_demo_data is None:
            self.seed_demo_data = not self.is_production
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}

    def llm_connection(self) -> tuple[SecretStr, str, str]:
        """Эффективные ключ, URL и модель; generic-настройки имеют приоритет над legacy."""
        provider = self.llm_provider.lower()
        legacy = provider == "deepseek"
        api_key = self.llm_api_key or (self.deepseek_api_key if legacy else None)
        base_url = self.llm_base_url or (self.deepseek_base_url if legacy else None)
        model = self.llm_model or (self.deepseek_model if legacy else None)
        if provider == "anthropic":
            base_url = base_url or "https://api.anthropic.com"
        if provider == "openai":
            base_url = base_url or "https://api.openai.com/v1"
        if not api_key or not base_url or not model:
            raise ValueError(
                f"LLM_PROVIDER={self.llm_provider} требует LLM_API_KEY, LLM_BASE_URL и LLM_MODEL"
            )
        return api_key, base_url, model

    def llm_runtime(self, *, warn: bool = False) -> dict[str, float | int | bool | None]:
        """Таймаут, повторы и thinking: generic `LLM_*` главнее legacy `DEEPSEEK_*`.

        Legacy-имена действуют только для `LLM_PROVIDER=deepseek` и только если соответствующее
        generic-имя не задано; об их использовании пишется предупреждение.
        """
        legacy = self.llm_provider.lower() == "deepseek"
        explicit = self.model_fields_set
        pairs = {
            "timeout_sec": ("llm_timeout_sec", "deepseek_timeout_sec"),
            "max_retries": ("llm_max_retries", "deepseek_max_retries"),
            "retry_base_sec": ("llm_retry_base_sec", "deepseek_retry_base_sec"),
            "retry_max_sec": ("llm_retry_max_sec", "deepseek_retry_max_sec"),
        }
        values: dict[str, float | int | bool | None] = {}
        for key, (generic, old) in pairs.items():
            if generic not in explicit and legacy and old in explicit:
                if warn:
                    logger.warning(
                        "Переменная %s устарела: задайте %s", old.upper(), generic.upper()
                    )
                values[key] = getattr(self, old)
            else:
                values[key] = getattr(self, generic)
        values["thinking"] = self.deepseek_thinking_enabled if legacy else None
        return values

    def validate_for_runtime(self) -> None:
        """Отказ при старте, если production молча работал бы на заглушках."""
        if not self.is_production:
            return
        if self.stt_provider.lower() == "mock":
            raise ValueError(
                "Production не принимает STT_PROVIDER=mock: задайте STT_PROVIDER=deepgram "
                "и DEEPGRAM_API_KEY, иначе записи превратились бы в заготовленный текст"
            )
        if self.llm_provider.lower() == "mock" and not self.credentials_encryption_key:
            raise ValueError(
                "Production не принимает LLM_PROVIDER=mock без CREDENTIALS_ENCRYPTION_KEY: "
                "задайте провайдера сервера или включите ключи пользователей"
            )

    @property
    def cookie_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.is_production

    def mock_delay(self, seconds: float) -> float:
        return max(seconds, 0.0) * max(self.mock_delay_scale, 0.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
