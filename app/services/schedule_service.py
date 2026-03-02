from __future__ import annotations

from datetime import date, datetime, time as time_cls, timedelta
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from app.config import Settings
from app.domain import EditableEntry, DayItem, DayItemType, DayView, Extra, Lesson, ShareImportResult, ShareScope, ShareToken
from app.dto import ExtraInput, LessonInput
from app.repositories import ExtrasRepository, ScheduleRepository, ShareTokenRepository, UserRepository
from app.services.errors import InputValidationError, ShareImportError, ShareLinkNotFoundError
from app.utils import parsing


class ScheduleService:
    def __init__(
        self,
        settings: Settings,
        user_repo: UserRepository,
        schedule_repo: ScheduleRepository,
        extras_repo: ExtrasRepository,
        share_repo: ShareTokenRepository,
    ) -> None:
        self.settings = settings
        self.user_repo = user_repo
        self.schedule_repo = schedule_repo
        self.extras_repo = extras_repo
        self.share_repo = share_repo

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
            lessons=[self._lesson_to_payload(lesson) for lesson in lessons],
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
            extras=[self._extra_to_payload(extra) for extra in extras],
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

    async def create_share_link(self, user_id: int, scope: ShareScope):
        await self.user_repo.get_or_create(user_id)
        return await self.share_repo.create(user_id, scope)

    async def import_shared_schedule(self, target_user_id: int, token: str) -> ShareImportResult:
        share = await self.resolve_share_token(token)
        if share.owner_id == target_user_id:
            raise ShareImportError("Нельзя импортировать своё расписание.")

        await self.user_repo.get_or_create(target_user_id)
        lessons_days = await self._copy_lessons(share.owner_id, target_user_id)

        extras_days = 0
        if share.scope == ShareScope.ALL:
            extras_days = await self._copy_extras(share.owner_id, target_user_id)

        return ShareImportResult(scope=share.scope, lessons_days=lessons_days, extras_days=extras_days)

    async def resolve_share_token(self, token: str) -> ShareToken:
        share = await self.share_repo.get(token)
        if not share:
            raise ShareLinkNotFoundError()
        return share

    async def get_share_week_preview(self, owner_id: int, scope: ShareScope) -> dict[int, DayView]:
        include_extras = scope == ShareScope.ALL
        week: dict[int, DayView] = {}
        for weekday in range(1, 8):
            week[weekday] = await self._build_day_view(
                owner_id,
                weekday,
                include_lessons=True,
                include_extras=include_extras,
            )
        return week

    async def get_editable_entries(self, user_id: int, weekday: int) -> list[EditableEntry]:
        await self.user_repo.get_or_create(user_id)
        self._validate_weekday(weekday)
        lessons = await self.schedule_repo.list_by_user_and_day(user_id, weekday)
        extras = await self.extras_repo.list_by_user_and_day(user_id, weekday)
        entries: list[EditableEntry] = [
            EditableEntry(
                id=lesson.id,
                type=DayItemType.LESSON,
                label=lesson.subject,
                start_time=lesson.start_time,
                end_time=lesson.end_time,
                location=lesson.location,
                subtitle=lesson.teacher,
            )
            for lesson in lessons
        ]
        entries.extend(
            EditableEntry(
                id=extra.id,
                type=DayItemType.EXTRA,
                label=extra.name,
                start_time=extra.start_time,
                end_time=extra.end_time,
                location=extra.location,
                subtitle=extra.notes,
            )
            for extra in extras
        )
        entries.sort(key=lambda entry: entry.start_time)
        return entries

    async def create_entry(
        self,
        user_id: int,
        weekday: int,
        entry_type: DayItemType,
        label: str,
        start_time_value: time_cls,
        end_time_value: time_cls,
        location: str | None,
        subtitle: str | None,
    ) -> EditableEntry:
        await self.user_repo.get_or_create(user_id)
        self._validate_weekday(weekday)
        if not label.strip():
            raise InputValidationError(["Название занятия не может быть пустым."])
        if entry_type == DayItemType.LESSON:
            return await self._create_lesson_entry(
                user_id,
                weekday,
                label,
                start_time_value,
                end_time_value,
                location,
                subtitle,
            )
        return await self._create_extra_entry(
            user_id,
            weekday,
            label,
            start_time_value,
            end_time_value,
            location,
            subtitle,
        )

    async def update_entry(
        self,
        user_id: int,
        entry_type: DayItemType,
        entry_id: int,
        *,
        source_type: DayItemType | None = None,
        label: str,
        start_time_value: time_cls,
        end_time_value: time_cls,
        location: str | None,
        subtitle: str | None,
        weekday: int | None = None,
    ) -> EditableEntry:
        if not label.strip():
            raise InputValidationError(["Название занятия не может быть пустым."])
        current_type = source_type
        current_weekday: int | None = None
        if source_type == DayItemType.LESSON:
            lesson_entry = await self.schedule_repo.get_entry(entry_id, user_id)
            if lesson_entry:
                current_weekday = lesson_entry.weekday
            else:
                current_type = None
        elif source_type == DayItemType.EXTRA:
            extra_entry = await self.extras_repo.get_entry(entry_id, user_id)
            if extra_entry:
                current_weekday = extra_entry.weekday
            else:
                current_type = None
        else:
            lesson_entry = await self.schedule_repo.get_entry(entry_id, user_id)
            extra_entry = await self.extras_repo.get_entry(entry_id, user_id)
            if lesson_entry and extra_entry:
                raise InputValidationError(
                    [
                        "Найдены записи с одинаковым ID. Повторите запрос с указанием исходного типа.",
                    ],
                )
            if lesson_entry:
                current_type = DayItemType.LESSON
                current_weekday = lesson_entry.weekday
            elif extra_entry:
                current_type = DayItemType.EXTRA
                current_weekday = extra_entry.weekday

        if current_type is None:
            raise InputValidationError(["Запись не найдена."])

        if entry_type == current_type:
            if entry_type == DayItemType.LESSON:
                return await self._update_lesson_entry(
                    user_id,
                    entry_id,
                    label,
                    start_time_value,
                    end_time_value,
                    location,
                    subtitle,
                    weekday,
                )
            return await self._update_extra_entry(
                user_id,
                entry_id,
                label,
                start_time_value,
                end_time_value,
                location,
                subtitle,
                weekday,
            )

        target_weekday = weekday or current_weekday
        if target_weekday is None:
            raise InputValidationError(["Не удалось определить день недели записи."])

        if current_type == DayItemType.LESSON:
            deleted = await self.schedule_repo.delete_entry(entry_id, user_id)
        else:
            deleted = await self.extras_repo.delete_entry(entry_id, user_id)
        if not deleted:
            raise InputValidationError(["Не удалось изменить тип записи."])

        return await self.create_entry(
            user_id,
            target_weekday,
            entry_type,
            label,
            start_time_value,
            end_time_value,
            location,
            subtitle,
        )

    async def update_entry_label(
        self,
        user_id: int,
        entry_type: DayItemType,
        entry_id: int,
        new_label: str,
    ) -> bool:
        label = new_label.strip()
        if not label:
            raise InputValidationError(["Название не может быть пустым."])
        if entry_type == DayItemType.LESSON:
            return await self.schedule_repo.update_subject(entry_id, user_id, label)
        return await self.extras_repo.update_name(entry_id, user_id, label)

    async def delete_entry(self, user_id: int, entry_type: DayItemType, entry_id: int) -> bool:
        if entry_type == DayItemType.LESSON:
            return await self.schedule_repo.delete_entry(entry_id, user_id)
        return await self.extras_repo.delete_entry(entry_id, user_id)

    async def _create_lesson_entry(
        self,
        user_id: int,
        weekday: int,
        subject: str,
        start_time_value: time_cls,
        end_time_value: time_cls,
        location: str | None,
        teacher: str | None,
    ) -> EditableEntry:
        lessons = await self.schedule_repo.list_by_user_and_day(user_id, weekday)
        new_entry = LessonInput(
            subject=subject,
            start_time=start_time_value,
            end_time=end_time_value,
            location=location,
            teacher=teacher,
        )
        self._validate_limits(len(lessons) + 1, self.settings.max_lessons_per_day, "уроков")
        self._validate_overlap([self._lesson_to_input(lesson) for lesson in lessons] + [new_entry], "уроков")
        created = await self.schedule_repo.insert_entry(
            user_id=user_id,
            weekday=weekday,
            subject=subject,
            start_time_value=start_time_value,
            end_time_value=end_time_value,
            location=location,
            teacher=teacher,
        )
        return self._lesson_to_editable(created)

    async def _create_extra_entry(
        self,
        user_id: int,
        weekday: int,
        name: str,
        start_time_value: time_cls,
        end_time_value: time_cls,
        location: str | None,
        notes: str | None,
    ) -> EditableEntry:
        extras = await self.extras_repo.list_by_user_and_day(user_id, weekday)
        new_entry = ExtraInput(
            name=name,
            start_time=start_time_value,
            end_time=end_time_value,
            location=location,
            notes=notes,
        )
        self._validate_limits(len(extras) + 1, self.settings.max_extras_per_day, "внеурочки")
        self._validate_overlap([self._extra_to_input(extra) for extra in extras] + [new_entry], "внеурочки")
        created = await self.extras_repo.insert_entry(
            user_id=user_id,
            weekday=weekday,
            name=name,
            start_time_value=start_time_value,
            end_time_value=end_time_value,
            location=location,
            notes=notes,
        )
        return self._extra_to_editable(created)

    async def _update_lesson_entry(
        self,
        user_id: int,
        entry_id: int,
        subject: str,
        start_time_value: time_cls,
        end_time_value: time_cls,
        location: str | None,
        teacher: str | None,
        weekday_override: int | None,
    ) -> EditableEntry:
        current = await self.schedule_repo.get_entry(entry_id, user_id)
        if not current:
            raise InputValidationError(["Урок не найден."])
        target_weekday = weekday_override or current.weekday
        self._validate_weekday(target_weekday)
        lessons = await self.schedule_repo.list_by_user_and_day(user_id, target_weekday)
        remaining = [lesson for lesson in lessons if lesson.id != entry_id]
        updated_input = LessonInput(
            subject=subject,
            start_time=start_time_value,
            end_time=end_time_value,
            location=location,
            teacher=teacher,
        )
        self._validate_limits(len(remaining) + 1, self.settings.max_lessons_per_day, "уроков")
        self._validate_overlap(
            [self._lesson_to_input(lesson) for lesson in remaining] + [updated_input],
            "уроков",
        )
        updated = await self.schedule_repo.update_entry(
            entry_id,
            user_id,
            subject=subject,
            weekday=target_weekday,
            start_time_value=start_time_value,
            end_time_value=end_time_value,
            location=location,
            teacher=teacher,
        )
        if not updated:
            raise InputValidationError(["Не удалось обновить урок."])
        return self._lesson_to_editable(updated)

    async def _update_extra_entry(
        self,
        user_id: int,
        entry_id: int,
        name: str,
        start_time_value: time_cls,
        end_time_value: time_cls,
        location: str | None,
        notes: str | None,
        weekday_override: int | None,
    ) -> EditableEntry:
        current = await self.extras_repo.get_entry(entry_id, user_id)
        if not current:
            raise InputValidationError(["Внеурочная активность не найдена."])
        target_weekday = weekday_override or current.weekday
        self._validate_weekday(target_weekday)
        extras = await self.extras_repo.list_by_user_and_day(user_id, target_weekday)
        remaining = [extra for extra in extras if extra.id != entry_id]
        updated_input = ExtraInput(
            name=name,
            start_time=start_time_value,
            end_time=end_time_value,
            location=location,
            notes=notes,
        )
        self._validate_limits(len(remaining) + 1, self.settings.max_extras_per_day, "внеурочки")
        self._validate_overlap(
            [self._extra_to_input(extra) for extra in remaining] + [updated_input],
            "внеурочки",
        )
        updated = await self.extras_repo.update_entry(
            entry_id,
            user_id,
            name=name,
            weekday=target_weekday,
            start_time_value=start_time_value,
            end_time_value=end_time_value,
            location=location,
            notes=notes,
        )
        if not updated:
            raise InputValidationError(["Не удалось обновить внеурочку."])
        return self._extra_to_editable(updated)

    async def _build_day_view(
        self,
        user_id: int,
        weekday: int,
        *,
        include_lessons: bool = True,
        include_extras: bool = True,
    ) -> DayView:
        lessons: list[Lesson] = []
        extras: list[Extra] = []
        if include_lessons:
            lessons = await self.schedule_repo.list_by_user_and_day(user_id, weekday)
        if include_extras:
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

    @staticmethod
    def _lesson_to_payload(lesson: LessonInput | Lesson) -> dict:
        return {
            "subject": lesson.subject,
            "start_time": lesson.start_time,
            "end_time": lesson.end_time,
            "location": getattr(lesson, "location", None),
            "teacher": getattr(lesson, "teacher", None),
        }

    @staticmethod
    def _extra_to_payload(extra: ExtraInput | Extra) -> dict:
        return {
            "name": extra.name,
            "start_time": extra.start_time,
            "end_time": extra.end_time,
            "location": getattr(extra, "location", None),
            "notes": getattr(extra, "notes", None),
        }

    @staticmethod
    def _lesson_to_input(lesson: Lesson | LessonInput) -> LessonInput:
        if isinstance(lesson, LessonInput):
            return lesson
        return LessonInput(
            subject=lesson.subject,
            start_time=lesson.start_time,
            end_time=lesson.end_time,
            location=lesson.location,
            teacher=lesson.teacher,
        )

    @staticmethod
    def _extra_to_input(extra: Extra | ExtraInput) -> ExtraInput:
        if isinstance(extra, ExtraInput):
            return extra
        return ExtraInput(
            name=extra.name,
            start_time=extra.start_time,
            end_time=extra.end_time,
            location=extra.location,
            notes=extra.notes,
        )

    @staticmethod
    def _lesson_to_editable(lesson: Lesson) -> EditableEntry:
        return EditableEntry(
            id=lesson.id,
            type=DayItemType.LESSON,
            label=lesson.subject,
            start_time=lesson.start_time,
            end_time=lesson.end_time,
            location=lesson.location,
            subtitle=lesson.teacher,
        )

    @staticmethod
    def _extra_to_editable(extra: Extra) -> EditableEntry:
        return EditableEntry(
            id=extra.id,
            type=DayItemType.EXTRA,
            label=extra.name,
            start_time=extra.start_time,
            end_time=extra.end_time,
            location=extra.location,
            subtitle=extra.notes,
        )

    async def _copy_lessons(self, source_user_id: int, target_user_id: int) -> int:
        days_with_data = 0
        for weekday in range(1, 8):
            lessons = await self.schedule_repo.list_by_user_and_day(source_user_id, weekday)
            await self.schedule_repo.replace_day(
                user_id=target_user_id,
                weekday=weekday,
                lessons=[self._lesson_to_payload(lesson) for lesson in lessons],
            )
            if lessons:
                days_with_data += 1
        return days_with_data

    async def _copy_extras(self, source_user_id: int, target_user_id: int) -> int:
        days_with_data = 0
        for weekday in range(1, 8):
            extras = await self.extras_repo.list_by_user_and_day(source_user_id, weekday)
            await self.extras_repo.replace_day(
                user_id=target_user_id,
                weekday=weekday,
                extras=[self._extra_to_payload(extra) for extra in extras],
            )
            if extras:
                days_with_data += 1
        return days_with_data
