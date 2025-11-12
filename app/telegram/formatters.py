from __future__ import annotations

from datetime import time
from typing import Iterable

from app.domain import DayItem, DayItemType, DayView
from app.dto import ExtraInput, LessonInput

DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def weekday_label(weekday: int) -> str:
    if 1 <= weekday <= 7:
        return DAY_NAMES[weekday - 1]
    return f"День {weekday}"


def render_day_view(view: DayView) -> str:
    lines = [f"{weekday_label(view.weekday)}"]
    if not view.items:
        lines.append("— записей нет")
        return "\n".join(lines)

    for item in view.items:
        lines.append(_format_day_item(item))
    return "\n".join(lines)


def render_week_view(views: dict[int, DayView]) -> str:
    parts: list[str] = []
    for weekday in range(1, 8):
        day_view = views.get(weekday)
        if not day_view:
            continue
        parts.append(render_day_view(day_view))
    return "\n\n".join(parts)


def render_preview_lessons(entries: Iterable[LessonInput], weekday: int) -> str:
    lines = [f"Предпросмотр уроков ({weekday_label(weekday)}):"]
    for entry in entries:
        lines.append(_format_slot(entry.start_time, entry.end_time, entry.subject, entry.location, entry.teacher))
    return "\n".join(lines)


def render_preview_extras(entries: Iterable[ExtraInput], weekday: int) -> str:
    lines = [f"Предпросмотр внеурочки ({weekday_label(weekday)}):"]
    for entry in entries:
        lines.append(_format_slot(entry.start_time, entry.end_time, entry.name, entry.location, entry.notes))
    return "\n".join(lines)


def _format_day_item(item: DayItem) -> str:
    label_prefix = "[Урок]" if item.type == DayItemType.LESSON else "[Кружок]"
    return _format_slot(
        item.start_time,
        item.end_time,
        f"{label_prefix} {item.label}",
        item.location,
        item.subtitle,
    )


def _format_slot(
    start: time,
    end: time,
    label: str,
    location: str | None,
    subtitle: str | None,
) -> str:
    parts = [f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')} {label.strip()}"]
    if location:
        parts.append(f"({location})")
    if subtitle:
        parts.append(f"— {subtitle}")
    return " ".join(parts)
