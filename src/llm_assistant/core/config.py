"""Settings for LLM Assistant.

The app is local-first: a SQLite file is the source of truth for
experiments and results, secrets are kept in env, and the model
catalog is configurable. The demo defaults assume an OpenAI key but
the services layer can route to any provider.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Persistence
    database_url: str = "llm_assistant.db"

    # HTTP
    cors_origins: str = "*"
    log_level: str = "INFO"

    # Provider keys
    openai_api_key: str = "sk-demo"
    anthropic_api_key: str = "sk-ant-demo"
    ollama_base_url: str = "http://localhost:11434"

    # Defaults applied when a request doesn't specify a model
    default_provider: str = "openai"
    default_model: str = "gpt-4o-mini"
    default_temperature: float = 0.2
    default_max_tokens: int = 1024

    # Safety
    max_prompt_chars: int = 32000
    request_timeout_seconds: int = 120


@lru_cache
def settings() -> Settings:
    return Settings()
