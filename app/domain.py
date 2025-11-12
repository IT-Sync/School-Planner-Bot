from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from typing import Optional


class DayItemType(str, Enum):
    LESSON = "lesson"
    EXTRA = "extra"


@dataclass(slots=True)
class User:
    id: int
    timezone: str
    lang: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class Lesson:
    id: int
    user_id: int
    weekday: int
    subject: str
    start_time: time
    end_time: time
    location: Optional[str]
    teacher: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class Extra:
    id: int
    user_id: int
    weekday: int
    name: str
    start_time: time
    end_time: time
    location: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class DayItem:
    type: DayItemType
    label: str
    start_time: time
    end_time: time
    location: Optional[str]
    subtitle: Optional[str]


@dataclass(slots=True)
class DayView:
    weekday: int
    items: list[DayItem]


WeekView = dict[int, DayView]
