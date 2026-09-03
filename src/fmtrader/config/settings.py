"""Typed application settings loaded from environment / ``.env``."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from fmtrader.core.errors import SettingsError

_MISSING = "is not set. Copy .env.example to .env and set real credentials before running make up."


class Settings(BaseSettings):
    """Infrastructure and runtime settings.

    Required QuestDB / Postgres credentials fail fast with a named error — there is no
    weak-default fallback (matches docker-compose ``${VAR:?error}`` behaviour).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    questdb_user: str = Field(default="", description="QuestDB PG user")
    questdb_password: str = Field(default="", description="QuestDB PG password")
    postgres_user: str = Field(default="", description="Postgres user")
    postgres_password: str = Field(default="", description="Postgres password")

    questdb_http_url: str = Field(default="http://localhost:9000")
    questdb_pg_host: str = Field(default="localhost")
    questdb_pg_port: int = Field(default=8812)
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="fmtrader")
    temporal_host: str = Field(default="localhost")
    temporal_port: int = Field(default=7233)
    temporal_ui_url: str = Field(default="http://localhost:8233")
    redis_url: str = Field(default="redis://localhost:6379/0")
    mlflow_url: str = Field(default="http://localhost:5001")
    ollama_url: str = Field(default="http://localhost:11434")
    ollama_cloud_url: str = Field(
        default="http://localhost:11434",
        description="Ollama Cloud HTTP base (same host once signed in; models by name)",
    )
    ollama_api_key: str = Field(
        default="",
        description="Optional Ollama Cloud API key (OLLAMA_API_KEY)",
    )

    # LLM budget caps (USD) — Phase 7 governor; empty env → 0 (local-only)
    llm_budget_per_campaign_usd: float = Field(default=0.0)
    llm_budget_per_day_usd: float = Field(default=0.0)
    llm_budget_per_generation_usd: float = Field(default=0.0)
    anthropic_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    gemini_api_key: str = Field(default="")

    # LangSmith — optional LLM/agent tracing (never commit real keys)
    langsmith_api_key: str = Field(default="")
    langchain_api_key: str = Field(default="")
    langsmith_project: str = Field(default="FMEngine")
    langsmith_tracing: bool = Field(default=False)

    # News — env key preferred; free RSS fallback when blank
    news_api_key: str = Field(default="")

    # Memory budget (GB) — see ADR 0001
    memory_budget_total_gb: float = Field(default=24.0)
    memory_budget_docker_gb: float = Field(default=6.0)
    memory_budget_ollama_gb: float = Field(default=8.0)
    memory_budget_workers_gb: float = Field(default=6.0)
    memory_budget_headroom_gb: float = Field(default=4.0)

    @field_validator(
        "questdb_user",
        "questdb_password",
        "postgres_user",
        "postgres_password",
        mode="before",
    )
    @classmethod
    def _strip_str(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator(
        "llm_budget_per_campaign_usd",
        "llm_budget_per_day_usd",
        "llm_budget_per_generation_usd",
        mode="before",
    )
    @classmethod
    def _empty_budget_to_zero(cls, value: object) -> object:
        if value is None or value == "":
            return 0.0
        return value

    @field_validator("langsmith_tracing", mode="before")
    @classmethod
    def _boolish(cls, value: object) -> object:
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"", "0", "false", "no", "off"}:
                return False
            if v in {"1", "true", "yes", "on"}:
                return True
        return value

    def require_infra_credentials(self) -> None:
        """Raise ``SettingsError`` naming each missing required credential."""
        missing: list[str] = []
        for name, value in (
            ("QUESTDB_USER", self.questdb_user),
            ("QUESTDB_PASSWORD", self.questdb_password),
            ("POSTGRES_USER", self.postgres_user),
            ("POSTGRES_PASSWORD", self.postgres_password),
        ):
            if not value:
                missing.append(f"{name} {_MISSING}")
        if missing:
            raise SettingsError("; ".join(missing))

    @property
    def postgres_dsn(self) -> str:
        self.require_infra_credentials()
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def questdb_pg_dsn(self) -> str:
        self.require_infra_credentials()
        return (
            f"postgresql://{self.questdb_user}:{self.questdb_password}"
            f"@{self.questdb_pg_host}:{self.questdb_pg_port}/qdb"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear the settings cache (tests only)."""
    get_settings.cache_clear()
