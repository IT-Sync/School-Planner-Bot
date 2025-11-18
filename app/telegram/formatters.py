from __future__ import annotations

from datetime import time
from typing import Iterable

from app.domain import DayItem, DayItemType, DayView, UsageStats
from app.dto import ExtraInput, LessonInput

DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MARKDOWN_SPECIAL = "_*[]()~`>#+=|{}"


def weekday_label(weekday: int) -> str:
    if 1 <= weekday <= 7:
        return DAY_NAMES[weekday - 1]
    return f"День {weekday}"


def render_day_view(view: DayView) -> str:
    lines = [f"*{escape_markdown(weekday_label(view.weekday))}*"]
    if not view.items:
        lines.append("_записей нет_")
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
    lines = [f"*Предпросмотр уроков ({escape_markdown(weekday_label(weekday))}):*"]
    for entry in entries:
        body = f"{escape_markdown(entry.subject)}"
        lines.append(_format_slot(entry.start_time, entry.end_time, body, entry.location, entry.teacher))
    return "\n".join(lines)


def render_preview_extras(entries: Iterable[ExtraInput], weekday: int) -> str:
    lines = [f"*Предпросмотр внеурочки ({escape_markdown(weekday_label(weekday))}):*"]
    for entry in entries:
        body = f"{escape_markdown(entry.name)}"
        lines.append(_format_slot(entry.start_time, entry.end_time, body, entry.location, entry.notes))
    return "\n".join(lines)


def render_usage_stats(stats: UsageStats) -> str:
    lines = [
        "*Статистика использования*",
        f"- Всего пользователей: *{stats.total_users}*",
        f"- Новых за 24 часа: *{stats.new_users_day}*",
        f"- Новых за 7 дней: *{stats.new_users_week}*",
        f"- Активных пользователей: *{stats.active_users}*",
        f"- Записей уроков: *{stats.lessons_total}*",
        f"- Записей внеурочки: *{stats.extras_total}*",
        f"- Ссылок /share за 7 дней: *{stats.share_links_week}*",
    ]
    return "\n".join(lines)


def _format_day_item(item: DayItem) -> str:
    label_prefix = "*Урок*" if item.type == DayItemType.LESSON else "*Кружок*"
    body = f"{label_prefix}: {escape_markdown(item.label)}"
    return _format_slot(
        item.start_time,
        item.end_time,
        body,
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
    time_span = f"`{start.strftime('%H:%M')}`–`{end.strftime('%H:%M')}`"
    parts = [f"- {time_span} {label.strip()}"]
    if location:
        parts.append(f" ({escape_markdown(location)})")
    if subtitle:
        parts.append(f" — {escape_markdown(subtitle)}")
    return " ".join(parts)


def escape_markdown(value: str) -> str:
    escaped = []
    for char in value:
        if char in MARKDOWN_SPECIAL:
            escaped.append(f"\\{char}")
        else:
            escaped.append(char)
    return "".join(escaped)
