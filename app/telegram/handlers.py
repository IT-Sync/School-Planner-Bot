from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from zoneinfo import ZoneInfo

from app.config import Settings
from app.domain import DayItemType, ShareScope
from app.services import AdminService, ScheduleService
from app.services.errors import InputValidationError, ShareImportError, ShareLinkNotFoundError
from app.telegram import formatters, keyboards, states
from app.utils import parsing

router = Router()
_schedule_service: ScheduleService | None = None
_admin_service: AdminService | None = None
_settings: Settings | None = None
_REMOVE_KEYBOARD = ReplyKeyboardRemove(remove_keyboard=True)
LEGACY_OPEN_MENU_LABEL = "Открыть расписание"


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


def _main_menu(event) -> ReplyKeyboardMarkup:
    settings = _get_settings(event)
    return keyboards.main_menu_keyboard(settings.webapp_url or None)


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


def _share_import_result_text(result) -> str:
    scope_label = "уроки и внеурочка" if result.scope == ShareScope.ALL else "только уроки"
    safe_scope = formatters.escape_markdown(scope_label)
    lines = [
        f"*Импортировано расписание* ({safe_scope}).",
        _format_days_stat("Уроки", result.lessons_days),
    ]
    if result.scope == ShareScope.ALL:
        lines.append(_format_days_stat("Внеурочка", result.extras_days))
    return "\n".join(lines)


def _message_target(event: Message | CallbackQuery) -> Message:
    if isinstance(event, CallbackQuery):
        if not event.message:
            raise RuntimeError("Callback without message")
        return event.message
    return event


async def _show_edit_entries(event: Message | CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    weekday = data.get("weekday")
    if not weekday:
        await state.set_state(states.EditState.choosing_day)
        await _message_target(event).answer(
            "Выберите день для редактирования:",
            reply_markup=keyboards.weekday_keyboard("edit"),
        )
        return
    service = _get_service(event)
    entries = await service.get_editable_entries(event.from_user.id, int(weekday))  # type: ignore[arg-type]
    if not entries:
        await state.set_state(states.EditState.choosing_day)
        await _message_target(event).answer(
            "На этот день больше нет записей. Выберите другой:",
            reply_markup=keyboards.weekday_keyboard("edit"),
        )
        return
    await state.set_state(states.EditState.choosing_entry)
    await _message_target(event).answer(
        formatters.render_edit_entries(int(weekday), entries),
        reply_markup=keyboards.edit_entries_keyboard(entries),
    )


async def _handle_share_deep_link(message: Message, args: str) -> bool:
    if not args.startswith("share_"):
        return False
    token = args.split("share_", 1)[1]
    if not token:
        await message.answer("Не удалось распознать приглашение.")
        return True

    service = _get_service(message)
    try:
        share = await service.resolve_share_token(token)
    except ShareLinkNotFoundError:
        await message.answer("Приглашение недействительно или устарело.")
        return True

    preview = await service.get_share_week_preview(share.owner_id, share.scope)
    preview_text = formatters.render_share_preview(share.scope, preview)
    await message.answer(
        preview_text + "\n\n_Нажмите «Импортировать», чтобы заменить своё расписание._",
        reply_markup=keyboards.share_import_keyboard(share.token),
    )
    return True


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject | None = None) -> None:
    service = _get_service(message)
    await service.ensure_user(message.from_user.id)  # type: ignore[arg-type]
    if command and command.args:
        handled = await _handle_share_deep_link(message, command.args)
        if handled:
            return

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
        reply_markup=_main_menu(message),
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


@router.message(Command("edit"))
async def cmd_edit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(states.EditState.choosing_day)
    await message.answer(
        "Режим редактирования.\nВыберите день:",
        reply_markup=keyboards.weekday_keyboard("edit"),
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
        reply_markup=_main_menu(message),
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
        "Ссылка активна в течение 1 дня. После перехода бот сразу покажет расписание и предложит подтвердить импорт.",
    )
    await callback.answer("Ссылка создана")


@router.callback_query(F.data == "share:cancel")
async def share_cancel(callback: CallbackQuery) -> None:
    await callback.message.answer("Действие отменено.")
    await callback.answer()


@router.callback_query(F.data == "share:preview:cancel")
async def share_preview_cancel(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.edit_reply_markup()
        await callback.message.answer("Импорт отменён.")
    await callback.answer()


@router.callback_query(F.data.startswith("share:preview:import:"))
async def share_preview_import(callback: CallbackQuery) -> None:
    data = callback.data or ""
    token = data.split("share:preview:import:", 1)[-1]
    service = _get_service(callback)
    try:
        result = await service.import_shared_schedule(callback.from_user.id, token)  # type: ignore[arg-type]
    except ShareLinkNotFoundError:
        await callback.message.answer("Приглашение недействительно или устарело.")
        await callback.answer()
        return
    except ShareImportError as exc:
        await callback.message.answer(str(exc))
        await callback.answer()
        return

    if callback.message:
        await callback.message.edit_reply_markup()
        await callback.message.answer(_share_import_result_text(result))
    await callback.answer("Импортировано")


@router.message(states.EditState.waiting_for_label)
async def edit_receive_label(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Название не может быть пустым. Попробуйте снова или введите Отмена.")
        return
    if text.lower() == "отмена":
        await state.set_state(states.EditState.choosing_entry)
        await message.answer("Изменение отменено.")
        await _show_edit_entries(message, state)
        return
    data = await state.get_data()
    entry_type_value = data.get("entry_type")
    entry_id = data.get("entry_id")
    if entry_type_value is None or entry_id is None:
        await state.set_state(states.EditState.choosing_day)
        await message.answer(
            "Не удалось определить запись. Выберите день ещё раз:",
            reply_markup=keyboards.weekday_keyboard("edit"),
        )
        return
    entry_type = DayItemType(entry_type_value)
    service = _get_service(message)
    try:
        updated = await service.update_entry_label(message.from_user.id, entry_type, int(entry_id), text)  # type: ignore[arg-type]
    except InputValidationError as exc:
        await message.answer("\n".join(exc.errors))
        return
    if updated:
        await message.answer("Название обновлено.")
    else:
        await message.answer("Не удалось обновить запись. Возможно, она была удалена.")
    await _show_edit_entries(message, state)


@router.callback_query(states.EditState.choosing_day, F.data.startswith("edit:day:"))
async def edit_choose_day(callback: CallbackQuery, state: FSMContext) -> None:
    weekday = int(callback.data.split(":")[-1])
    service = _get_service(callback)
    entries = await service.get_editable_entries(callback.from_user.id, weekday)  # type: ignore[arg-type]
    await state.update_data(weekday=weekday)
    if not entries:
        await callback.message.answer(
            "На этот день пока нет записей. Выберите другой:",
            reply_markup=keyboards.weekday_keyboard("edit"),
        )
        await callback.answer()
        return
    await state.set_state(states.EditState.choosing_entry)
    await callback.message.answer(
        formatters.render_edit_entries(weekday, entries),
        reply_markup=keyboards.edit_entries_keyboard(entries),
    )
    await callback.answer()


@router.callback_query(F.data == "edit:back")
async def edit_back(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(states.EditState.choosing_day)
    await callback.message.answer(
        "Выберите день:",
        reply_markup=keyboards.weekday_keyboard("edit"),
    )
    await callback.answer()


@router.callback_query(F.data == "edit:entries")
async def edit_entries_back(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_edit_entries(callback, state)
    await callback.answer()


@router.callback_query(F.data == "edit:cancel")
async def edit_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Режим редактирования завершён.")
    await callback.answer()


@router.callback_query(states.EditState.choosing_entry, F.data.startswith("edit:item:"))
async def edit_entry_selected(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, type_value, entry_id = callback.data.split(":", 3)
    entry_type = DayItemType(type_value)
    await state.update_data(entry_type=entry_type.value, entry_id=int(entry_id))
    await state.set_state(states.EditState.choosing_action)
    await callback.message.answer(
        "Что сделать с этой записью?",
        reply_markup=keyboards.edit_entry_actions_keyboard(entry_type, int(entry_id)),
    )
    await callback.answer()


@router.callback_query(states.EditState.choosing_action, F.data.startswith("edit:action:"))
async def edit_entry_action(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, action, type_value, entry_id = callback.data.split(":", 4)
    entry_type = DayItemType(type_value)
    entry_id_int = int(entry_id)
    await state.update_data(entry_type=entry_type.value, entry_id=entry_id_int)
    service = _get_service(callback)
    if action == "rename":
        await state.set_state(states.EditState.waiting_for_label)
        await callback.message.answer("Введите новое название (или напишите Отмена):")
        await callback.answer()
        return
    if action == "delete":
        deleted = await service.delete_entry(callback.from_user.id, entry_type, entry_id_int)  # type: ignore[arg-type]
        if deleted:
            await callback.message.answer("Запись удалена.")
        else:
            await callback.message.answer("Не удалось удалить запись. Возможно, она уже изменена.")
        await _show_edit_entries(callback, state)
    await callback.answer()


async def _send_today(message: Message, clear_keyboard: bool = False) -> None:
    service = _get_service(message)
    settings = _get_settings(message)
    now = datetime.now(tz=ZoneInfo(settings.default_tz))
    view = await service.get_day_view(message.from_user.id, now)  # type: ignore[arg-type]
    reply_markup = _REMOVE_KEYBOARD if clear_keyboard else None
    await message.answer(formatters.render_day_view(view), reply_markup=reply_markup)


async def _send_tomorrow(message: Message, clear_keyboard: bool = False) -> None:
    service = _get_service(message)
    settings = _get_settings(message)
    tomorrow = datetime.now(tz=ZoneInfo(settings.default_tz)) + timedelta(days=1)
    view = await service.get_day_view(message.from_user.id, tomorrow)  # type: ignore[arg-type]
    reply_markup = _REMOVE_KEYBOARD if clear_keyboard else None
    await message.answer(formatters.render_day_view(view), reply_markup=reply_markup)


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    await _send_today(message)


@router.message(F.text == keyboards.MENU_TODAY_LABEL)
async def menu_today(message: Message) -> None:
    await _send_today(message, clear_keyboard=True)


@router.message(F.text == keyboards.MENU_TOMORROW_LABEL)
async def menu_tomorrow(message: Message) -> None:
    await _send_tomorrow(message, clear_keyboard=True)


async def _send_week(message: Message, clear_keyboard: bool = False) -> None:
    service = _get_service(message)
    settings = _get_settings(message)
    now = datetime.now(tz=ZoneInfo(settings.default_tz))
    start_of_week = now - timedelta(days=now.weekday())
    views = await service.get_week_view(message.from_user.id, start_of_week.date())  # type: ignore[arg-type]
    reply_markup = _REMOVE_KEYBOARD if clear_keyboard else None
    await message.answer(formatters.render_week_view(views), reply_markup=reply_markup)


@router.message(Command("week"))
async def cmd_week(message: Message) -> None:
    await _send_week(message)


@router.message(F.text == keyboards.MENU_WEEK_LABEL)
async def menu_week(message: Message) -> None:
    await _send_week(message, clear_keyboard=True)


@router.message(F.text == LEGACY_OPEN_MENU_LABEL)
async def legacy_open_schedule(message: Message) -> None:
    await message.answer(
        "Эта кнопка больше не поддерживается. Используйте команды или актуальное меню.",
        reply_markup=_REMOVE_KEYBOARD,
    )


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
