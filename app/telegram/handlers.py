from __future__ import annotations

from datetime import datetime, timedelta

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from zoneinfo import ZoneInfo

from app.config import Settings
from app.domain import ShareScope
from app.services import AdminService, ScheduleService
from app.services.errors import InputValidationError, ShareImportError, ShareLinkNotFoundError
from app.telegram import formatters, keyboards, states
from app.utils import parsing

router = Router()


def _menu_buttons_text() -> str:
    labels = [
        keyboards.MENU_TODAY_LABEL,
        keyboards.MENU_TOMORROW_LABEL,
        keyboards.MENU_WEEK_LABEL,
    ]
    return "Список кнопок меню:\n" + "\n".join(f"- {label}" for label in labels)


class CommandMenuReminderMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            text = (event.text or "").strip()
            if text.startswith("/") and event.chat.type == "private":
                await event.answer(
                    _menu_buttons_text(),
                    reply_markup=keyboards.main_menu_keyboard(),
                )
        return await handler(event, data)


router.message.middleware(CommandMenuReminderMiddleware())
_schedule_service: ScheduleService | None = None
_admin_service: AdminService | None = None
_settings: Settings | None = None


def configure_dependencies(service: ScheduleService, settings: Settings, admin_service: AdminService) -> None:
    global _schedule_service, _settings, _admin_service
    _schedule_service = service
    _settings = settings
    _admin_service = admin_service


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


def _get_admin_service(event) -> AdminService:
    service = _admin_service
    if service is None:
        raise RuntimeError("AdminService is not configured")
    return service


def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    settings = _settings
    if not settings:
        return False
    return user_id in settings.admin_ids


def _parse_share_scope(value: str) -> ShareScope:
    return ShareScope.ALL if value == "all" else ShareScope.LESSONS


def _format_days_stat(label: str, days: int) -> str:
    return f"- {formatters.escape_markdown(label)}: *{days}* дн."


async def _handle_share_deep_link(message: Message, args: str) -> None:
    if not args.startswith("share_"):
        return
    token = args.split("share_", 1)[1]
    if not token:
        await message.answer("Не удалось распознать приглашение.")
        return

    service = _get_service(message)
    try:
        result = await service.import_shared_schedule(message.from_user.id, token)  # type: ignore[arg-type]
    except ShareLinkNotFoundError:
        await message.answer("Приглашение недействительно или устарело.")
        return
    except ShareImportError as exc:
        await message.answer(str(exc))
        return

    scope_label = "уроки и внеурочка" if result.scope == ShareScope.ALL else "только уроки"
    safe_scope = formatters.escape_markdown(scope_label)
    lines = [
        f"*Импортировано расписание* ({safe_scope}).",
        _format_days_stat("Уроки", result.lessons_days),
    ]
    if result.scope == ShareScope.ALL:
        lines.append(_format_days_stat("Внеурочка", result.extras_days))
    await message.answer("\n".join(lines))


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject | None = None) -> None:
    service = _get_service(message)
    await service.ensure_user(message.from_user.id)  # type: ignore[arg-type]
    if command and command.args:
        await _handle_share_deep_link(message, command.args)

    await message.answer(
        "👋 *Привет! Я — School Planner Bot.*\n"
        "Помогаю собирать уроки и внеурочку в одном расписании, показывать день или неделю и делиться ими с семьёй.\n\n"
        "*Что я умею*\n"
        "- /set_lessons — заполнить уроки выбранного дня\n"
        "- /set_extras — добавить кружки и секции\n"
        "- /today — показать расписание на сегодня\n"
        "- /week — вывести всю неделю\n"
        "- /share — создать ссылку-приглашение, чтобы друзья скопировали твоё расписание\n"
        "- /help — напомнить формат ввода",
        reply_markup=keyboards.main_menu_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Формат строк: HH:MM-HH:MM Название [локация] [комментарий]\n"
        "Примеры:\n"
        "08:30-09:15 Математика 204 (Иванова)\n"
        "16:00-17:00 Робототехника к.12\n"
        "Разделяйте дополнительные поля с помощью символов | или ; если нужно указать локацию/комментарий.\n\n"
        "Команда /share создаёт приглашение для импорта расписания другим пользователем.",
    )


@router.message(Command("share"))
async def cmd_share(message: Message) -> None:
    await message.answer(
        "Выберите, чем поделиться:",
        reply_markup=keyboards.share_scope_keyboard(),
    )


@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):  # type: ignore[arg-type]
        await message.answer("Эта команда доступна только администраторам.")
        return
    service = _get_admin_service(message)
    stats = await service.get_usage_stats()
    await message.answer(
        formatters.render_usage_stats(stats),
        reply_markup=keyboards.main_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("share:scope:"))
async def share_scope_chosen(callback: CallbackQuery) -> None:
    service = _get_service(callback)
    data = callback.data or ""
    scope_value = data.split(":")[-1]
    scope = _parse_share_scope(scope_value)
    share = await service.create_share_link(callback.from_user.id, scope)  # type: ignore[arg-type]

    bot_user = await callback.bot.get_me()
    if bot_user.username:
        browser_link = f"https://t.me/{bot_user.username}?start=share_{share.token}"
        deep_link = f"tg://resolve?domain={bot_user.username}&start=share_{share.token}"
        link_text = (
            f"[Открыть приглашение]({browser_link})\n"
            f"`{browser_link}`\n"
            "Альтернатива для открытия сразу в приложении:\n"
            f"`{deep_link}`"
        )
    else:
        link_text = (
            "Чтобы получать кликабельные ссылки, задайте username для бота в BotFather."
        )

    fallback = f"`/start share_{share.token}`"
    scope_label = "уроки и внеурочка" if scope == ShareScope.ALL else "только уроки"
    safe_scope = formatters.escape_markdown(scope_label)
    await callback.message.answer(
        f"Скопируйте ссылку для импорта ({safe_scope}):\n"
        f"{link_text}\n"
        f"Или передайте команду {fallback}\n\n"
        "Ссылка активна в течение 1 дня. Приглашённый пользователь перейдёт по ссылке и отправит /start, чтобы импортировать данные.",
    )
    await callback.answer("Ссылка создана")


@router.callback_query(F.data == "share:cancel")
async def share_cancel(callback: CallbackQuery) -> None:
    await callback.message.answer("Действие отменено.")
    await callback.answer()


async def _send_today(message: Message) -> None:
    service = _get_service(message)
    settings = _get_settings(message)
    now = datetime.now(tz=ZoneInfo(settings.default_tz))
    view = await service.get_day_view(message.from_user.id, now)  # type: ignore[arg-type]
    await message.answer(formatters.render_day_view(view))


async def _send_tomorrow(message: Message) -> None:
    service = _get_service(message)
    settings = _get_settings(message)
    tomorrow = datetime.now(tz=ZoneInfo(settings.default_tz)) + timedelta(days=1)
    view = await service.get_day_view(message.from_user.id, tomorrow)  # type: ignore[arg-type]
    await message.answer(formatters.render_day_view(view))


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    await _send_today(message)


@router.message(F.text == keyboards.MENU_TODAY_LABEL)
async def menu_today(message: Message) -> None:
    await _send_today(message)


@router.message(F.text == keyboards.MENU_TOMORROW_LABEL)
async def menu_tomorrow(message: Message) -> None:
    await _send_tomorrow(message)


async def _send_week(message: Message) -> None:
    service = _get_service(message)
    settings = _get_settings(message)
    now = datetime.now(tz=ZoneInfo(settings.default_tz))
    start_of_week = now - timedelta(days=now.weekday())
    views = await service.get_week_view(message.from_user.id, start_of_week.date())  # type: ignore[arg-type]
    await message.answer(formatters.render_week_view(views))


@router.message(Command("week"))
async def cmd_week(message: Message) -> None:
    await _send_week(message)


@router.message(F.text == keyboards.MENU_WEEK_LABEL)
async def menu_week(message: Message) -> None:
    await _send_week(message)


@router.message(Command(commands=["set_lessons", "setlessons"]))
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


@router.message(Command(commands=["set_extras", "setextras"]))
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
