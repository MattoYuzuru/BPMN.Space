"""Единственный источник конфигурации backend. Все значения — из окружения / `.env`."""

import logging
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.domain.concurrency import adaptive_deadline

logger = logging.getLogger(__name__)
_MB = 1024 * 1024
# Переменные, у которых «задано явно» меняет поведение (RFC-0005): пустое значение — не задано.
_UNSET_WHEN_EMPTY = frozenset(
    {"llm_json_max_tokens", "llm_anthropic_effort", "llm_server_max_effort"}
)
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

    # --- MCP-сервер внешних агентов (RFC-0007, шаг 2) ---
    # Секрет HMAC-подписи `estimate_token` (допуск на запуск после оценки). Пусто — случайный
    # на процесс: после перезапуска старые оценки потребуют повторного `estimate_run`.
    mcp_estimate_secret: str | None = None
    # Срок жизни оценки прогона (секунды): `start_run` без свежей оценки отклоняется.
    mcp_estimate_ttl_sec: float = Field(default=900.0, gt=0, le=86_400)
    # Дорогие вызовы MCP (`start_run`) на токен в минуту: отдельная таблица, потому что
    # IP-лимиты `/api/v1` путь `/mcp` не покрывают.
    mcp_expensive_per_min: int = 30

    # В Compose всегда настоящий внутренний Node-сервис. None — ограниченный локальный mock.
    bpmn_tools_url: str | None = None
    bpmn_tools_timeout_sec: float = Field(default=20.0, gt=0, le=120)

    # --- Прогоны (RFC §5.1) ---
    max_concurrent_runs: int = 2
    # Общий срок одного прогона (секунды, 0 — без срока): новые запросы к модели после него
    # не начинаются, прогон завершается ошибкой, а не висит.
    # Это нижняя граница: к ней прибавляется время на объём источников (см. `run_deadline`).
    run_deadline_sec: float = 600.0
    # Дополнительные секунды срока на каждую 1000 символов источников (длинные документы).
    run_deadline_per_1k_chars_sec: float = Field(default=4.0, ge=0)
    # Жёсткий потолок адаптивного срока (по умолчанию 2 часа); 0 — потолка нет.
    run_deadline_max_sec: float = Field(default=7200.0, ge=0)
    # Бюджет источников прогона (RFC-0005) считается из окна выбранной модели:
    # (окно − ответ − накладные) × знаков на токен × запас. Эта переменная — нижняя граница и
    # бюджет моделей с неизвестным окном (совместимые провайдеры, mock). Что не помещается в
    # бюджет, идёт порциями; поместившийся проект — без порционного извлечения.
    llm_context_budget_chars: int = 120_000
    # Потолок бюджета, рассчитанного из окна (знаки; 0 — без потолка). Нужен, если лимиты
    # аккаунта провайдера (входные токены в минуту) не пропускают запрос на всё окно.
    llm_context_budget_max_chars: int = Field(default=0, ge=0)
    # Размер порции текста при извлечении оснований и смысловой сверке (символы).
    llm_chunk_chars: int = Field(default=24_000, ge=1_000)
    # Сколько независимых запросов порций к модели одновременно (анализ, извлечение, сверка).
    llm_parallel_requests: int = Field(default=4, ge=1, le=32)

    # --- Агентный режим (RFC-0004): модель сама читает источники инструментами ---
    # Выключен по умолчанию: режим включает оператор. Агент доступен только моделям с
    # инструментами; профиль прогона с mode=agent иначе получает 422.
    llm_agent_mode: bool = False
    # Потолок ходов агента на прогон: профиль может попросить меньше, но не больше.
    llm_agent_max_steps: int = Field(default=24, ge=1, le=200)
    # Сколько символов источника агент читает за один вызов read_source.
    llm_agent_read_max_chars: int = Field(default=12_000, ge=1_000, le=40_000)
    # Сколько совпадений и какой длины фрагменты отдаёт search_sources.
    llm_agent_search_limit: int = Field(default=5, ge=1, le=20)
    llm_agent_search_snippet_chars: int = Field(default=400, ge=100, le=1_200)

    # --- Ограничения загрузок ---
    # Документы (.txt .md .csv .docx .xlsx .pptx .pdf).
    max_upload_bytes: int = 50 * _MB
    # Голосовая заметка из микрофона (`POST /transcriptions`, синхронно).
    max_audio_bytes: int = 60 * _MB
    # Файлы аудио и видео, загружаемые как источник (расшифровываются в фоне через ffmpeg).
    max_media_bytes: int = 500 * _MB
    max_diagram_bytes: int = 5 * _MB

    # --- Сессии правок (ADR-0010): автосохранения одного автора сливаются в одну версию ---
    # Пауза между сохранениями, после которой правка начинает новую версию (0 — не сливать).
    version_session_idle_sec: float = Field(default=600.0, ge=0)
    # Предельная длительность одной сессии правок, даже если автор не останавливался.
    version_session_max_sec: float = Field(default=3600.0, ge=0)
    # Текст одного источника после разбора (≈ 500 страниц).
    max_text_chars: int = 1_500_000
    # Разбор документов: у PDF ограничены число страниц и время (в отдельном потоке).
    max_pdf_pages: int = 1000
    # Таблицы Excel: строк с данными на лист; остаток не молчаливо пропускается, а даёт warning.
    max_sheet_rows: int = 20_000
    parse_timeout_sec: float = 180.0

    # --- Аудио и видео (ingest/media.py): ffmpeg режет звук, STT читает сегменты параллельно ---
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    media_segment_sec: int = Field(default=600, ge=30, le=1800)
    media_ffmpeg_timeout_sec: float = Field(default=3600.0, gt=0)
    media_max_duration_sec: float = Field(default=4 * 3600.0, gt=0)
    # Одновременно расшифровываемых сегментов и одновременных медиазаданий.
    stt_parallel_segments: int = Field(default=3, ge=1, le=16)
    media_max_concurrent_jobs: int = Field(default=1, ge=1, le=8)
    # Срок запроса сегмента: база + доля длительности сегмента.
    stt_segment_timeout_base_sec: float = Field(default=60.0, gt=0)
    stt_segment_timeout_per_audio_sec: float = Field(default=0.3, ge=0)

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
    # Лимит JSON-ответа. У модели из справочника по умолчанию берётся её максимум (у Claude
    # 5.5 — 128 тыс., потоком); явно заданная переменная становится потолком. У модели с
    # неизвестным максимумом — само значение. Незавершённый length-ответ не применяется.
    llm_json_max_tokens: int = Field(default=16384, ge=256, le=131_072)
    # Лимит ответа порций: извлечение оснований, смысловая сверка, проверка вопросов пакетами.
    # Провайдер резервирует лимит выходных токенов в минуту по `max_tokens`, поэтому параллельные
    # порции не получают полный максимум модели. Обрезанная порция делится, а не теряется.
    llm_chunk_max_tokens: int = Field(default=16384, ge=256, le=131_072)
    # Температура для JSON-ответов (анализ, сборка). Дефолт провайдера (DeepSeek — 1.0)
    # даёт редкие ответы не по схеме; 0.0 — рекомендация DeepSeek для структурированного вывода.
    llm_json_temperature: float | None = 0.0
    llm_max_retries: int = 3
    llm_retry_base_sec: float = 1.0
    llm_retry_max_sec: float = 30.0
    # Глубина рассуждения Anthropic (`output_config.effort`) по умолчанию для всех моделей:
    # low | medium | high | xhigh | max. Не задана — умолчание модели из справочника (Opus 5.5 —
    # medium, Sonnet 5.5 — high). Уровень из профиля прогона главнее.
    llm_anthropic_effort: str = "medium"
    # Предельный уровень effort для модели сервера (ключ оператора), который может попросить
    # любой пользователь: low | medium | high | xhigh | max. Не задан — уровень сервера по
    # умолчанию (`LLM_ANTHROPIC_EFFORT`, иначе умолчание модели). Свой ключ не ограничивается.
    llm_server_max_effort: str | None = None
    # Ключи моделей пользователей (ADR-0011): Fernet-ключи через запятую; первый шифрует,
    # все расшифровывают (ротация). Сгенерировать: `make credentials-key`. В production без
    # него пользовательские ключи не принимаются; в dev берётся временный ключ процесса.
    credentials_encryption_key: SecretStr | None = None
    # Хосты закрытых сетей, к которым разрешено ходить совместимым провайдерам пользователей
    # (локальный vLLM/Ollama в dev). Пусто — только публичные адреса по HTTPS.
    llm_allowed_private_hosts: Annotated[list[str], NoDecode] = []
    # Потолок тела ответа сервера модели (чат и /models): защита памяти от чужого сервера.
    llm_max_response_bytes: int = Field(default=8 * _MB, ge=1024)
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
    deepgram_timeout_sec: float = 120.0

    # --- Маршрутизация инструментов по ключам пользователя (RFC-0006) ---
    # Повторы временных сбоев одного ключа: число попыток и паузы (как у LLM, с джиттером).
    capability_max_attempts: int = Field(default=2, ge=1, le=5)
    capability_retry_base_sec: float = Field(default=1.0, ge=0)
    capability_retry_max_sec: float = Field(default=30.0, ge=0)
    # Предохранитель ключа: после стольких подряд отказов ключ отдыхает это число секунд.
    capability_breaker_threshold: int = Field(default=3, ge=1, le=100)
    capability_breaker_cooldown_sec: float = Field(default=60.0, ge=0)
    # Пауза ключа при исчерпанной квоте, если провайдер не прислал `Retry-After`.
    capability_quota_cooldown_sec: float = Field(default=3600.0, ge=0)

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

    @field_validator("llm_anthropic_effort", "llm_server_max_effort")
    @classmethod
    def _effort_level(cls, value: str | None) -> str | None:
        if value is None:
            return None
        level = value.strip().lower()
        if level not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Уровень effort: low | medium | high | xhigh | max")
        return level

    @field_validator("llm_allowed_private_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip().lower() for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="before")
    @classmethod
    def _unset_when_empty(cls, data: object) -> object:
        """Пустые `LLM_JSON_MAX_TOKENS=` и `LLM_ANTHROPIC_EFFORT=` (так их передаёт compose) —
        «не задано»: тогда действуют пределы и умолчания модели, а не потолок оператора."""
        if isinstance(data, dict):
            for key in list(data):
                if (
                    str(key).lower() in _UNSET_WHEN_EMPTY
                    and isinstance(data[key], str)
                    and not data[key].strip()
                ):
                    data.pop(key)
        return data

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

    def context_budget_chars(self) -> int:
        """Нижняя граница бюджета и бюджет моделей с неизвестным окном (см. `llm/factory.py`)."""
        return self.llm_context_budget_chars

    @property
    def json_max_tokens_explicit(self) -> bool:
        """`LLM_JSON_MAX_TOKENS` задан явно: тогда он потолок и для моделей из справочника."""
        return "llm_json_max_tokens" in self.model_fields_set

    def anthropic_effort_default(self) -> str | None:
        """`LLM_ANTHROPIC_EFFORT`, только если задан явно; иначе — умолчание модели."""
        if "llm_anthropic_effort" not in self.model_fields_set:
            return None
        return self.llm_anthropic_effort

    def run_deadline(self, total_chars: int = 0) -> float | None:
        """Срок прогона: `run_deadline_sec` — нижняя граница, плюс время на объём источников.

        `None` — срока нет (`RUN_DEADLINE_SEC=0`). Потолок `run_deadline_max_sec` не ниже базы.
        """
        return adaptive_deadline(
            self.run_deadline_sec,
            total_chars=total_chars,
            per_1k_chars_sec=self.run_deadline_per_1k_chars_sec,
            max_sec=self.run_deadline_max_sec,
        )

    def mock_delay(self, seconds: float) -> float:
        return max(seconds, 0.0) * max(self.mock_delay_scale, 0.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
