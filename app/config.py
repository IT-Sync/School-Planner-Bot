from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    app_env: Literal["production", "development", "test"] = Field(
        alias="APP_ENV", default="production"
    )
    bot_token: str = Field(alias="BOT_TOKEN", default="")
    bot_username: str = Field(alias="BOT_USERNAME", default="")
    database_host: str = Field(alias="DATABASE_HOST", default="db")
    database_port: int = Field(alias="DATABASE_PORT", default=5432, ge=1, le=65535)
    database_user: str = Field(alias="DATABASE_USER", default="planner")
    database_password: str = Field(alias="DATABASE_PASSWORD", default="planner")
    database_name: str = Field(alias="DATABASE_NAME", default="planner")
    auto_migrate: bool = Field(alias="AUTO_MIGRATE", default=False)
    default_tz: str = Field(alias="DEFAULT_TZ", default="Europe/Moscow")
    week_mode_default: Literal["combined", "split"] = Field(
        alias="WEEK_MODE_DEFAULT", default="combined"
    )
    max_lessons_per_day: int = Field(alias="MAX_LESSONS_PER_DAY", default=12, ge=1, le=50)
    max_extras_per_day: int = Field(alias="MAX_EXTRAS_PER_DAY", default=6, ge=1, le=50)
    health_port: int = Field(alias="HEALTH_PORT", default=8088)
    admin_ids: Annotated[tuple[int, ...], NoDecode] = Field(alias="ADMIN_IDS", default=())
    webapp_url: str = Field(alias="WEBAPP_URL", default="")
    webapp_dev_user_id: int | None = Field(alias="WEBAPP_DEV_USER_ID", default=None, gt=0)
    webapp_auth_max_age: int = Field(alias="WEBAPP_AUTH_MAX_AGE", default=3600, ge=60, le=86400)
    reminder_poll_seconds: int = Field(alias="REMINDER_POLL_SECONDS", default=30, ge=10, le=60)
    fsm_ttl_seconds: int = Field(
        alias="FSM_TTL_SECONDS", default=7 * 24 * 60 * 60, ge=300, le=30 * 24 * 60 * 60
    )
    max_attachment_bytes: int = Field(
        alias="MAX_ATTACHMENT_BYTES", default=5 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024
    )

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value):
        if value in (None, "", ()):
            return ()
        if isinstance(value, str):
            import json

            value = (
                json.loads(value)
                if value.strip().startswith("[")
                else [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]
            )
        if isinstance(value, int):
            value = [value]
        return tuple(int(item) for item in value)

    @field_validator("webapp_dev_user_id", mode="before")
    @classmethod
    def empty_dev_id(cls, value):
        return None if value == "" else value

    @field_validator("default_tz")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("DEFAULT_TZ must be an IANA timezone") from exc
        return value

    @field_validator("webapp_url")
    @classmethod
    def valid_web_url(cls, value):
        if value:
            url = urlsplit(value)
            if url.scheme != "https" or not url.netloc or url.username or url.fragment:
                raise ValueError("WEBAPP_URL must be a public HTTPS URL")
        return value.rstrip("/")

    @model_validator(mode="after")
    def production_auth(self):
        if self.app_env == "production":
            if self.webapp_dev_user_id:
                raise ValueError("WEBAPP_DEV_USER_ID is forbidden in production")
            if not self.bot_token:
                raise ValueError("BOT_TOKEN is required in production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
