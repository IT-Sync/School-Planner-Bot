from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return singleton settings instance."""
    return Settings()  # type: ignore[call-arg]
