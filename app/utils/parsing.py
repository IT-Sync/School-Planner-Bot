from __future__ import annotations

import re
from datetime import time
from typing import Callable

from app.dto import ExtraInput, LessonInput

LINE_PATTERN = re.compile(r"^\s*(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\s+(.+)$")


def parse_lessons_input(raw: str) -> tuple[list[LessonInput], list[str]]:
    return _parse_lines(raw, _build_lesson, "урока")


def parse_extras_input(raw: str) -> tuple[list[ExtraInput], list[str]]:
    return _parse_lines(raw, _build_extra, "внеурочки")


def _parse_lines(
    raw: str,
    factory: Callable[[str, time, time], object],
    label: str,
) -> tuple[list, list[str]]:
    entries: list = []
    errors: list[str] = []
    lines = [line for line in raw.splitlines() if line.strip()]
    for idx, line in enumerate(lines, start=1):
        match = LINE_PATTERN.match(line)
        if not match:
            errors.append(f"Строка {idx}: неверный формат {label} (ожидаем HH:MM-HH:MM ...)")
            continue

        start_raw, end_raw, body = match.groups()
        try:
            start_time_value = _to_time(start_raw)
            end_time_value = _to_time(end_raw)
        except ValueError as exc:
            errors.append(f"Строка {idx}: {exc}")
            continue

        if end_time_value <= start_time_value:
            errors.append(f"Строка {idx}: конец не может быть раньше или равен началу")
            continue

        try:
            entry = factory(body.strip(), start_time_value, end_time_value)
            entries.append(entry)
        except ValueError as exc:
            errors.append(f"Строка {idx}: {exc}")

    return entries, errors


def _build_lesson(body: str, start: time, end: time) -> LessonInput:
    subject, remainder = _split_optional_fields(body)
    teacher = None
    location = None

    subject, teacher_from_parens = _extract_parenthetical(subject)
    teacher = teacher_from_parens

    extra_teacher = None
    if len(remainder) >= 1:
        location = remainder[0] or None
    if len(remainder) >= 2:
        extra_teacher = remainder[1] or None

    if extra_teacher:
        teacher = extra_teacher

    if location is None:
        subject, location = _extract_location(subject)

    if not subject:
        raise ValueError("не указано название предмета")

    return LessonInput(
        subject=subject,
        start_time=start,
        end_time=end,
        location=location,
        teacher=teacher,
    )


def _build_extra(body: str, start: time, end: time) -> ExtraInput:
    name, remainder = _split_optional_fields(body)
    name, notes_from_parens = _extract_parenthetical(name)
    notes = notes_from_parens
    location = None

    if len(remainder) >= 1:
        location = remainder[0] or None
    if len(remainder) >= 2:
        notes = remainder[1] or notes

    if location is None:
        name, location = _extract_location(name)

    if not name:
        raise ValueError("не указано название активности")

    return ExtraInput(
        name=name,
        start_time=start,
        end_time=end,
        location=location,
        notes=notes,
    )


def _split_optional_fields(body: str) -> tuple[str, list[str]]:
    delimiter = None
    for candidate in ("|", ";"):
        if candidate in body:
            delimiter = candidate
            break
    if delimiter:
        parts = [part.strip() for part in body.split(delimiter)]
        head, tail = parts[0], parts[1:]
        return head, tail
    return body.strip(), []


def _extract_parenthetical(value: str) -> tuple[str, str | None]:
    value = value.strip()
    if value.endswith(")") and "(" in value:
        start_idx = value.rfind("(")
        inside = value[start_idx + 1 : -1].strip()
        base = value[:start_idx].strip()
        return base, inside or None
    return value, None


def _extract_location(value: str) -> tuple[str, str | None]:
    tokens = value.split()
    if len(tokens) <= 1:
        return value.strip(), None

    location_candidate = tokens[-1]
    lowered = location_candidate.lower()
    if any(ch.isdigit() for ch in location_candidate) or lowered.startswith(("к", "cab", "room")):
        subject = " ".join(tokens[:-1]).strip()
        return subject, location_candidate
    return value.strip(), None


def _to_time(value: str) -> time:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("неверный формат времени")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("время выходит за пределы 00:00-23:59")
    return time(hour=hour, minute=minute)
