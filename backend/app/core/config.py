"""Application settings, loaded from environment variables (and an optional .env file).

Nothing secret has a default value. Every setting can be overridden per environment.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "DataBridge"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "text"

    # Database: PostgreSQL in Docker/production, SQLite for zero-setup local development.
    database_url: str = f"sqlite:///{(BACKEND_ROOT / 'data' / 'databridge.db').as_posix()}"
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # Storage
    data_dir: Path = BACKEND_ROOT / "data"
    sample_dir: Path = BACKEND_ROOT.parent / "sample_data"
    frontend_dist: Path | None = None  # optional: serve the built SPA from FastAPI (single-service deploys)
    max_upload_mb: int = Field(default=50, ge=1, le=500)
    max_rows: int = Field(default=1_000_000, ge=1)
    max_columns: int = Field(default=200, ge=1)

    # HTTP
    # Comma-separated. Kept as a string: pydantic-settings would otherwise expect JSON for a list.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # AI provider (optional). The key is never returned by any endpoint.
    ai_provider: Literal["none", "anthropic", "openai"] = "none"
    ai_api_key: str | None = None
    ai_model: str | None = None
    ai_timeout_seconds: float = 45.0

    # Public demo mode (see docs/DEMO_MODE.md). Off by default so local use is unrestricted.
    demo_mode: bool = False
    demo_max_upload_mb: int = Field(default=10, ge=1, le=100)
    demo_max_rows: int = Field(default=50_000, ge=1)
    demo_retention_hours: int = Field(default=24, ge=1, le=24 * 30)
    demo_cleanup_interval_minutes: int = Field(default=60, ge=5)
    demo_max_datasets_per_visitor: int = Field(default=5, ge=1)
    demo_max_pipelines_per_visitor: int = Field(default=10, ge=1)
    rate_limit_enabled: bool | None = None  # defaults to demo_mode
    cookie_secure: bool | None = None  # defaults to True in production

    @model_validator(mode="after")
    def _apply_demo_limits(self) -> "Settings":
        # In demo mode the stricter limits always win, even if larger values were configured.
        if self.demo_mode:
            self.max_upload_mb = min(self.max_upload_mb, self.demo_max_upload_mb)
            self.max_rows = min(self.max_rows, self.demo_max_rows)
        if self.rate_limit_enabled is None:
            self.rate_limit_enabled = self.demo_mode
        if self.cookie_secure is None:
            self.cookie_secure = self.environment == "production"
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def report_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def ai_configured(self) -> bool:
        return self.ai_provider != "none" and bool(self.ai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
