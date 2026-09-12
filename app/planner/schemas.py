from __future__ import annotations

from datetime import date, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Kind = Literal["lesson", "extra"]


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProfilePayload(Payload):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(default="#5b68df", pattern=r"^#[0-9a-fA-F]{6}$")


class ProfilePatch(Payload):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class UserPatch(Payload):
    timezone: str | None = None
    reminder_minutes: int | None = Field(default=None, ge=0, le=120)
    evening_time: time | None = None
    reminders_enabled: bool | None = None
    default_profile_id: int | None = Field(default=None, gt=0)

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, value):
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError("Неизвестный часовой пояс") from exc
        return value

    @field_validator("evening_time")
    @classmethod
    def local_time(cls, value):
        if value is not None and value.tzinfo is not None:
            raise ValueError("Укажите местное время без смещения часового пояса")
        return value


class EventPayload(Payload):
    weekday: int = Field(ge=1, le=7)
    type: Kind
    label: str = Field(min_length=1, max_length=200)
    start_time: time
    end_time: time
    location: str | None = Field(default=None, max_length=200)
    subtitle: str | None = Field(default=None, max_length=1000)
    event_date: date | None = None

    @model_validator(mode="after")
    def validate_times(self):
        if self.start_time.tzinfo or self.end_time.tzinfo:
            raise ValueError("Укажите местное время без смещения часового пояса")
        if self.end_time <= self.start_time:
            raise ValueError("Окончание должно быть позже начала")
        if self.event_date and self.event_date.isoweekday() != self.weekday:
            raise ValueError("День недели не совпадает с датой занятия")
        return self


class ExceptionPayload(Payload):
    date: date
    cancelled: bool = False
    label: str | None = Field(default=None, min_length=1, max_length=200)
    type: Kind | None = None
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = Field(default=None, max_length=200)
    subtitle: str | None = Field(default=None, max_length=1000)


class CopyDayPayload(Payload):
    source_weekday: int = Field(ge=1, le=7)
    target_weekdays: list[int] = Field(min_length=1, max_length=7)
    mode: Literal["merge", "replace"] = "merge"
    types: list[Kind] = Field(
        default_factory=lambda: ["lesson", "extra"], min_length=1, max_length=2
    )
    preview: bool = False

    @field_validator("target_weekdays")
    @classmethod
    def valid_days(cls, value):
        if any(day < 1 or day > 7 for day in value):
            raise ValueError("Дни недели должны быть от 1 до 7")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def distinct_days(self):
        if self.source_weekday in self.target_weekdays:
            raise ValueError("Исходный день нельзя выбрать в качестве назначения")
        return self


class HolidayPayload(Payload):
    name: str = Field(min_length=1, max_length=120)
    start_date: date
    end_date: date
    types: list[Kind] = Field(default_factory=lambda: ["lesson"], min_length=1, max_length=2)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("Конец каникул должен быть не раньше начала")
        return self


class TaskPayload(Payload):
    title: str = Field(min_length=1, max_length=200)
    subject: str | None = Field(default=None, max_length=200)
    description: str = Field(default="", max_length=10000)
    due_date: date
    completed: bool = False


class TaskPatch(Payload):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    subject: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    due_date: date | None = None
    completed: bool | None = None


class InvitePayload(Payload):
    role: Literal["editor", "viewer"] = "editor"


class SharePayload(Payload):
    types: list[Kind] = Field(
        default_factory=lambda: ["lesson", "extra"], min_length=1, max_length=2
    )
    weekdays: list[int] = Field(
        default_factory=lambda: list(range(1, 8)), min_length=1, max_length=7
    )

    @field_validator("weekdays")
    @classmethod
    def days_valid(cls, value):
        if any(day < 1 or day > 7 for day in value):
            raise ValueError("Дни недели должны быть от 1 до 7")
        return sorted(set(value))


class ShareImportPayload(Payload):
    profile_id: int = Field(gt=0)
    mode: Literal["merge", "replace"] = "merge"
    preview: bool = False


class BellSlot(Payload):
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def times_valid(self):
        if self.start_time.tzinfo or self.end_time.tzinfo or self.end_time <= self.start_time:
            raise ValueError("Укажите корректное время начала и окончания")
        return self


class BellsPayload(Payload):
    slots: list[BellSlot] = Field(max_length=20)

    @model_validator(mode="after")
    def no_overlaps(self):
        ordered = sorted(self.slots, key=lambda item: item.start_time)
        if any(a.end_time > b.start_time for a, b in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("Время звонков не должно пересекаться")
        self.slots = ordered
        return self
