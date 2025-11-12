from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, time as time_cls, timedelta
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from app.config import Settings
from app.domain import DayItem, DayItemType, DayView, Extra, Lesson
from app.dto import ExtraInput, LessonInput
from app.repositories import ExtrasRepository, ScheduleRepository, UserRepository
from app.services.errors import InputValidationError
from app.utils import parsing


class ScheduleService:
    def __init__(
        self,
        settings: Settings,
        user_repo: UserRepository,
        schedule_repo: ScheduleRepository,
        extras_repo: ExtrasRepository,
    ) -> None:
        self.settings = settings
        self.user_repo = user_repo
        self.schedule_repo = schedule_repo
        self.extras_repo = extras_repo

    async def ensure_user(self, user_id: int) -> None:
        await self.user_repo.get_or_create(user_id)

    async def set_lessons_for_day(self, user_id: int, weekday: int, raw: str) -> DayView:
        await self.user_repo.get_or_create(user_id)
        self._validate_weekday(weekday)
        lessons, errors = parsing.parse_lessons_input(raw)
        if errors:
            raise InputValidationError(errors)
        self._validate_limits(len(lessons), self.settings.max_lessons_per_day, "уроков")
        self._validate_overlap(lessons, "уроков")

        await self.schedule_repo.replace_day(
            user_id=user_id,
            weekday=weekday,
            lessons=[asdict(lesson) for lesson in lessons],
        )
        return await self._build_day_view(user_id, weekday)

    async def set_extras_for_day(self, user_id: int, weekday: int, raw: str) -> DayView:
        await self.user_repo.get_or_create(user_id)
        self._validate_weekday(weekday)
        extras, errors = parsing.parse_extras_input(raw)
        if errors:
            raise InputValidationError(errors)
        self._validate_limits(len(extras), self.settings.max_extras_per_day, "внеурочки")
        self._validate_overlap(extras, "внеурочки")

        await self.extras_repo.replace_day(
            user_id=user_id,
            weekday=weekday,
            extras=[asdict(extra) for extra in extras],
        )
        return await self._build_day_view(user_id, weekday)

    async def get_day_view(
        self,
        user_id: int,
        target_date: date | datetime,
    ) -> DayView:
        user = await self.user_repo.get_or_create(user_id)
        timezone = ZoneInfo(user.timezone or self.settings.default_tz)
        if isinstance(target_date, datetime):
            localized = target_date.astimezone(timezone)
        else:
            localized = datetime.combine(target_date, time_cls.min, tzinfo=timezone)
        weekday = localized.isoweekday()
        return await self._build_day_view(user_id, weekday)

    async def get_week_view(self, user_id: int, week_start: date | datetime) -> dict[int, DayView]:
        await self.user_repo.get_or_create(user_id)
        if isinstance(week_start, datetime):
            start_date = week_start.date()
        else:
            start_date = week_start

        week: dict[int, DayView] = {}
        for offset in range(7):
            day = start_date + timedelta(days=offset)
            weekday = day.isoweekday()
            week[weekday] = await self._build_day_view(user_id, weekday)
        return week

    async def _build_day_view(self, user_id: int, weekday: int) -> DayView:
        lessons = await self.schedule_repo.list_by_user_and_day(user_id, weekday)
        extras = await self.extras_repo.list_by_user_and_day(user_id, weekday)
        items = self._merge_items(lessons, extras)
        return DayView(weekday=weekday, items=items)

    @staticmethod
    def _merge_items(lessons: Sequence[Lesson], extras: Sequence[Extra]) -> list[DayItem]:
        lesson_items = [
            DayItem(
                type=DayItemType.LESSON,
                label=lesson.subject,
                start_time=lesson.start_time,
                end_time=lesson.end_time,
                location=lesson.location,
                subtitle=lesson.teacher,
            )
            for lesson in lessons
        ]
        extra_items = [
            DayItem(
                type=DayItemType.EXTRA,
                label=extra.name,
                start_time=extra.start_time,
                end_time=extra.end_time,
                location=extra.location,
                subtitle=extra.notes,
            )
            for extra in extras
        ]

        combined = lesson_items + extra_items
        combined.sort(key=lambda item: item.start_time)
        return combined

    @staticmethod
    def _validate_weekday(weekday: int) -> None:
        if weekday < 1 or weekday > 7:
            raise InputValidationError(["weekday должен быть в диапазоне 1-7"])

    @staticmethod
    def _validate_limits(count: int, limit: int, label: str) -> None:
        if count > limit:
            raise InputValidationError([f"Не более {limit} {label} в день"])

    @staticmethod
    def _validate_overlap(entries: Iterable[LessonInput | ExtraInput], label: str) -> None:
        sorted_entries = sorted(entries, key=lambda item: item.start_time)  # type: ignore[arg-type]
        for prev, current in zip(sorted_entries, sorted_entries[1:]):
            if current.start_time < prev.end_time:
                raise InputValidationError(
                    [
                        f"Пересечение {label}: {prev.start_time.strftime('%H:%M')}–"
                        f"{prev.end_time.strftime('%H:%M')} и "
                        f"{current.start_time.strftime('%H:%M')}–"
                        f"{current.end_time.strftime('%H:%M')}",
                    ],
                )
