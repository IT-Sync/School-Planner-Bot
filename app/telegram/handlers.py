from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from zoneinfo import ZoneInfo

from app.config import Settings
from app.services import ScheduleService
from app.services.errors import InputValidationError
from app.telegram import formatters, keyboards, states
from app.utils import parsing

router = Router()
_schedule_service: ScheduleService | None = None
_settings: Settings | None = None


def configure_dependencies(service: ScheduleService, settings: Settings) -> None:
    global _schedule_service, _settings
    _schedule_service = service
    _settings = settings


def _get_service(event) -> ScheduleService:
    service = _schedule_service
    if service is None:
        raise RuntimeError("ScheduleService is not configured")
    return service


def _get_settings(event) -> Settings:
    settings = _settings
    if settings is None:
        raise RuntimeError("Settings are not configured")
    return settings


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    service = _get_service(message)
    await service.ensure_user(message.from_user.id)  # type: ignore[arg-type]
    await message.answer(
        "Привет! Я помогу вести расписание уроков и кружков.\n"
        "Команды:\n"
        "/set_lessons — заполнить уроки дня\n"
        "/set_extras — заполнить внеурочку\n"
        "/today — посмотреть расписание на сегодня\n"
        "/week — показать расписание на неделю\n"
        "/help — подсказка по форматам ввода",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Формат строк: HH:MM-HH:MM Название [локация] [комментарий]\n"
        "Примеры:\n"
        "08:30-09:15 Математика 204 (Иванова)\n"
        "16:00-17:00 Робототехника к.12\n"
        "Разделяйте дополнительные поля с помощью символов | или ; если нужно указать локацию/комментарий.",
    )


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    service = _get_service(message)
    settings = _get_settings(message)
    now = datetime.now(tz=ZoneInfo(settings.default_tz))
    view = await service.get_day_view(message.from_user.id, now)  # type: ignore[arg-type]
    await message.answer(formatters.render_day_view(view))


@router.message(Command("week"))
async def cmd_week(message: Message) -> None:
    service = _get_service(message)
    settings = _get_settings(message)
    now = datetime.now(tz=ZoneInfo(settings.default_tz))
    start_of_week = now - timedelta(days=now.weekday())
    views = await service.get_week_view(message.from_user.id, start_of_week.date())  # type: ignore[arg-type]
    await message.answer(formatters.render_week_view(views))


@router.message(Command("set_lessons"))
async def cmd_set_lessons(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(states.LessonsState.choosing_day)
    await message.answer(
        "Выберите день недели для уроков:",
        reply_markup=keyboards.weekday_keyboard("lessons"),
    )


@router.callback_query(
    states.LessonsState.choosing_day,
    F.data.startswith("lessons:day:"),
)
async def lessons_choose_day(callback: CallbackQuery, state: FSMContext) -> None:
    weekday = int(callback.data.split(":")[-1])
    await state.update_data(weekday=weekday)
    await state.set_state(states.LessonsState.waiting_for_text)
    await callback.message.answer(
        f"Отправьте уроки для {formatters.weekday_label(weekday)} (каждый с новой строки).",
    )
    await callback.answer()


@router.callback_query(F.data == "lessons:cancel")
async def lessons_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Действие отменено.")
    await callback.answer()


@router.message(states.LessonsState.waiting_for_text)
async def lessons_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    weekday = data.get("weekday")
    if not weekday:
        await message.answer("Сначала выберите день недели.")
        return

    entries, errors = parsing.parse_lessons_input(message.text or "")
    if errors:
        await message.answer("\n".join(errors))
        return

    await state.update_data(raw_text=message.text)
    await state.set_state(states.LessonsState.confirming)
    preview = formatters.render_preview_lessons(entries, weekday)
    await message.answer(preview, reply_markup=keyboards.confirmation_keyboard("lessons"))


@router.callback_query(states.LessonsState.confirming, F.data == "lessons:save")
async def lessons_save(callback: CallbackQuery, state: FSMContext) -> None:
    service = _get_service(callback)
    data = await state.get_data()
    raw_text = data.get("raw_text")
    weekday = data.get("weekday")
    if not raw_text or not weekday:
        await callback.message.answer("Не найден ввод для сохранения.")
        await callback.answer()
        return

    try:
        view = await service.set_lessons_for_day(callback.from_user.id, int(weekday), raw_text)  # type: ignore[arg-type]
    except InputValidationError as exc:
        await callback.message.answer("\n".join(exc.errors))
        await callback.answer()
        return

    await state.clear()
    await callback.message.answer("Уроки сохранены:\n" + formatters.render_day_view(view))
    await callback.answer("Готово")


@router.callback_query(states.LessonsState.confirming, F.data == "lessons:cancel")
async def lessons_confirm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Изменения уроков отменены.")
    await callback.answer()


@router.message(Command("set_extras"))
async def cmd_set_extras(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(states.ExtrasState.choosing_day)
    await message.answer(
        "Выберите день недели для внеурочки:",
        reply_markup=keyboards.weekday_keyboard("extras"),
    )


@router.callback_query(
    states.ExtrasState.choosing_day,
    F.data.startswith("extras:day:"),
)
async def extras_choose_day(callback: CallbackQuery, state: FSMContext) -> None:
    weekday = int(callback.data.split(":")[-1])
    await state.update_data(weekday=weekday)
    await state.set_state(states.ExtrasState.waiting_for_text)
    await callback.message.answer(
        f"Отправьте внеурочную активность для {formatters.weekday_label(weekday)}.",
    )
    await callback.answer()


@router.callback_query(F.data == "extras:cancel")
async def extras_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Действие отменено.")
    await callback.answer()


@router.message(states.ExtrasState.waiting_for_text)
async def extras_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    weekday = data.get("weekday")
    if not weekday:
        await message.answer("Сначала выберите день недели.")
        return

    entries, errors = parsing.parse_extras_input(message.text or "")
    if errors:
        await message.answer("\n".join(errors))
        return

    await state.update_data(raw_text=message.text)
    await state.set_state(states.ExtrasState.confirming)
    preview = formatters.render_preview_extras(entries, weekday)
    await message.answer(preview, reply_markup=keyboards.confirmation_keyboard("extras"))


@router.callback_query(states.ExtrasState.confirming, F.data == "extras:save")
async def extras_save(callback: CallbackQuery, state: FSMContext) -> None:
    service = _get_service(callback)
    data = await state.get_data()
    raw_text = data.get("raw_text")
    weekday = data.get("weekday")
    if not raw_text or not weekday:
        await callback.message.answer("Не найден ввод для сохранения.")
        await callback.answer()
        return

    try:
        view = await service.set_extras_for_day(callback.from_user.id, int(weekday), raw_text)  # type: ignore[arg-type]
    except InputValidationError as exc:
        await callback.message.answer("\n".join(exc.errors))
        await callback.answer()
        return

    await state.clear()
    await callback.message.answer("Внеурочка сохранена:\n" + formatters.render_day_view(view))
    await callback.answer("Готово")


@router.callback_query(states.ExtrasState.confirming, F.data == "extras:cancel")
async def extras_confirm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Изменения внеурочки отменены.")
    await callback.answer()
