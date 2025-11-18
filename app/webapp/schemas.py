from __future__ import annotations

from datetime import time
from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field


class EntryType(str, Enum):
    LESSON = "lesson"
    EXTRA = "extra"


class ScheduleEntry(BaseModel):
    id: int
    type: EntryType
    label: str
    start_time: time
    end_time: time
    location: str | None = None
    subtitle: str | None = None


class DayScheduleResponse(BaseModel):
    weekday: int
    entries: List[ScheduleEntry]


class WeekScheduleResponse(BaseModel):
    week: Dict[int, List[ScheduleEntry]]


class CreateEntryRequest(BaseModel):
    weekday: int = Field(ge=1, le=7)
    type: EntryType
    label: str
    start_time: time
    end_time: time
    location: str | None = None
    subtitle: str | None = None


class UpdateEntryRequest(BaseModel):
    type: EntryType
    label: str
    start_time: time
    end_time: time
    location: str | None = None
    subtitle: str | None = None
    weekday: int | None = Field(default=None, ge=1, le=7)
