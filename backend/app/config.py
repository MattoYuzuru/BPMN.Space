"""Единственный источник конфигурации backend. Все значения — из окружения / `.env`."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    app_env: str = "dev"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
