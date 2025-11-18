from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    bot_token: str = Field(alias="BOT_TOKEN")
    database_host: str = Field(alias="DATABASE_HOST", default="db")
    database_port: int = Field(alias="DATABASE_PORT", default=5544)
    database_user: str = Field(alias="DATABASE_USER", default="planner")
    database_password: str = Field(alias="DATABASE_PASSWORD", default="planner")
    database_name: str = Field(alias="DATABASE_NAME", default="planner")

    default_tz: str = Field(alias="DEFAULT_TZ", default="Europe/Amsterdam")
    week_mode_default: Literal["combined", "split"] = Field(
        alias="WEEK_MODE_DEFAULT",
        default="combined",
    )
    max_lessons_per_day: int = Field(alias="MAX_LESSONS_PER_DAY", default=12)
    max_extras_per_day: int = Field(alias="MAX_EXTRAS_PER_DAY", default=6)
    health_port: int = Field(alias="HEALTH_PORT", default=8088)
    admin_ids: tuple[int, ...] = Field(alias="ADMIN_IDS", default=())

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value):
        if value in (None, "", ()):
            return ()
        if isinstance(value, str):
            normalized = value.replace(";", ",")
            parts = [part.strip() for part in normalized.split(",")]
            return tuple(int(part) for part in parts if part)
        if isinstance(value, (list, tuple, set)):
            return tuple(int(item) for item in value)
        raise ValueError("ADMIN_IDS must be a comma-separated list of integers")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return singleton settings instance."""
    return Settings()  # type: ignore[call-arg]
