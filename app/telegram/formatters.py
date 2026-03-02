from __future__ import annotations

from datetime import time
from typing import Iterable

from app.domain import DayItem, DayItemType, DayView, EditableEntry, ShareScope, UsageStats
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
    active_ratio = (stats.active_users / stats.total_users * 100) if stats.total_users else 0.0
    lines = [
        "*Расширенная статистика использования*",
        "",
        "*Пользователи*",
        f"- Всего пользователей: *{stats.total_users}*",
        f"- Новых за 24 часа: *{stats.new_users_day}*",
        f"- Новых за 7 дней: *{stats.new_users_week}*",
        f"- Активных пользователей (всего): *{stats.active_users}* ({active_ratio:.1f}%)",
        f"- Активных за 24 часа: *{stats.active_users_day}*",
        f"- Активных за 7 дней: *{stats.active_users_week}*",
        f"- Пользователей с уроками: *{stats.users_with_lessons}*",
        f"- Пользователей с внеурочкой: *{stats.users_with_extras}*",
        "",
        "*Записи*",
        f"- Записей уроков: *{stats.lessons_total}*",
        f"- Записей внеурочки: *{stats.extras_total}*",
        f"- Среднее уроков на активного пользователя: *{stats.avg_lessons_per_active_user:.2f}*",
        f"- Среднее внеурочки на активного пользователя: *{stats.avg_extras_per_active_user:.2f}*",
        f"- Среднее всех записей на активного пользователя: *{stats.avg_total_entries_per_active_user:.2f}*",
        "",
        "*Share-ссылки*",
        f"- Всего создано: *{stats.share_links_total}*",
        f"- Создано за 24 часа: *{stats.share_links_day}*",
        f"- Ссылок /share за 7 дней: *{stats.share_links_week}*",
        f"- Активных (не истекли): *{stats.active_share_links}*",
    ]
    return "\n".join(lines)


def render_share_preview(scope: ShareScope, week_views: dict[int, DayView]) -> str:
    scope_label = "уроки и внеурочка" if scope == ShareScope.ALL else "только уроки"
    lines = [
        "*Приглашение на импорт расписания*",
        f"Тип данных: *{escape_markdown(scope_label)}*",
        "",
    ]
    content = render_week_view(week_views)
    lines.append(content or "_расписание пусто_")
    return "\n".join(lines)


def render_edit_entries(weekday: int, entries: list[EditableEntry]) -> str:
    lines = [
        f"*{escape_markdown(weekday_label(weekday))}: выберите запись для изменения*",
    ]
    if not entries:
        lines.append("_записей нет_")
        return "\n".join(lines)
    for idx, entry in enumerate(entries, start=1):
        label = "Урок" if entry.type == DayItemType.LESSON else "Кружок"
        span = f"`{entry.start_time.strftime('%H:%M')}`–`{entry.end_time.strftime('%H:%M')}`"
        lines.append(
            f"{idx}. {span} *[{label}]* {escape_markdown(entry.label)}",
        )
    lines.append("\nНажмите на кнопку ниже, чтобы выбрать запись.")
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
