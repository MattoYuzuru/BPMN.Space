"""Единственный источник конфигурации backend. Все значения — из окружения / `.env`."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.concurrency import adaptive_deadline

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
    # Это нижняя граница: к ней прибавляется время на объём источников (см. `run_deadline`).
    run_deadline_sec: float = 600.0
    # Дополнительные секунды срока на каждую 1000 символов источников (длинные документы).
    run_deadline_per_1k_chars_sec: float = Field(default=4.0, ge=0)
    # Жёсткий потолок адаптивного срока (по умолчанию 2 часа); 0 — потолка нет.
    run_deadline_max_sec: float = Field(default=7200.0, ge=0)
    # Анализ: бюджет одного запроса целиком, включая schema; полные источники идут порциями.
    # Построение: бюджет оснований после порционного извлечения; переполнение — явный отказ.
    # Для моделей с большим контекстом увеличьте значение: документ пройдёт без извлечения.
    llm_context_budget_chars: int = 120_000
    # Размер порции текста при извлечении оснований и смысловой сверке (символы).
    llm_chunk_chars: int = Field(default=24_000, ge=1_000)
    # Сколько независимых запросов порций к модели одновременно (анализ, извлечение, сверка).
    llm_parallel_requests: int = Field(default=4, ge=1, le=32)

    # --- Ограничения загрузок ---
    # Документы (.txt .md .csv .docx .xlsx .pptx .pdf).
    max_upload_bytes: int = 50 * _MB
    # Голосовая заметка из микрофона (`POST /transcriptions`, синхронно).
    max_audio_bytes: int = 60 * _MB
    # Файлы аудио и видео, загружаемые как источник (расшифровываются в фоне через ffmpeg).
    max_media_bytes: int = 500 * _MB
    max_diagram_bytes: int = 5 * _MB
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
    # Засевать ли демо-проекты при старте (в тестах можно выключить).
    seed_demo_data: bool = True

    # Внешние провайдеры выключены по умолчанию. Секреты задаются только в корневом .env.
    llm_provider: str = "mock"
    llm_api_key: str | None = None
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
    # Старые имена оставлены для плавного перехода production .env с DeepSeek.
    deepseek_api_key: str | None = None
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
    deepgram_api_key: str | None = None
    deepgram_timeout_sec: float = 120.0

    @field_validator(
        "database_url",
        "bpmn_tools_url",
        "session_cookie_secure",
        "llm_api_key",
        "deepseek_api_key",
        "deepgram_api_key",
        mode="before",
    )
    @classmethod
    def _empty_as_none(cls, value: object) -> object:
        """Пустое значение переменной (`NAME=` в .env или compose) значит «не задано»."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def llm_connection(self) -> tuple[str, str, str]:
        """Эффективные URL, модель и ключ; generic-настройки имеют приоритет над legacy."""
        provider = self.llm_provider.lower()
        api_key = self.llm_api_key or (self.deepseek_api_key if provider == "deepseek" else None)
        base_url = self.llm_base_url or (self.deepseek_base_url if provider == "deepseek" else None)
        model = self.llm_model or (self.deepseek_model if provider == "deepseek" else None)
        if not api_key or not base_url or not model:
            raise ValueError(
                f"LLM_PROVIDER={self.llm_provider} требует LLM_API_KEY, LLM_BASE_URL и LLM_MODEL"
            )
        return api_key, base_url, model

    @property
    def cookie_secure(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.app_env.lower() in {"prod", "production"}

    def context_budget_chars(self, provider_max: int | None = None) -> int:
        """Бюджет контекста: провайдер с большим окном может задать своё значение явно."""
        return provider_max if provider_max is not None else self.llm_context_budget_chars

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
