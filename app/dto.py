from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Optional


@dataclass(slots=True)
class LessonInput:
    subject: str
    start_time: time
    end_time: time
    location: Optional[str] = None
    teacher: Optional[str] = None


@dataclass(slots=True)
class ExtraInput:
    name: str
    start_time: time
    end_time: time
    location: Optional[str] = None
    notes: Optional[str] = None
