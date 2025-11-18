from typing import Sequence

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.domain import DayItemType, EditableEntry
DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MENU_TODAY_LABEL = "Расписание на сегодня"
MENU_TOMORROW_LABEL = "Расписание на завтра"
MENU_WEEK_LABEL = "Расписание на неделю"
MENU_WEBAPP_LABEL = "Открыть расписание"


def weekday_keyboard(prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, label in enumerate(DAY_NAMES, start=1):
        builder.button(text=label, callback_data=f"{prefix}:day:{idx}")
    builder.button(text="Отмена", callback_data=f"{prefix}:cancel")
    builder.adjust(3, 3, 1)
    return builder.as_markup()


def confirmation_keyboard(prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Сохранить", callback_data=f"{prefix}:save")
    builder.button(text="Отмена", callback_data=f"{prefix}:cancel")
    builder.adjust(2)
    return builder.as_markup()


def share_scope_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Уроки + внеурочка", callback_data="share:scope:all")
    builder.button(text="Только уроки", callback_data="share:scope:lessons")
    builder.button(text="Отмена", callback_data="share:cancel")
    builder.adjust(1)
    return builder.as_markup()


def share_import_keyboard(token: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Импортировать", callback_data=f"share:preview:import:{token}")
    builder.button(text="Отмена", callback_data="share:preview:cancel")
    builder.adjust(1)
    return builder.as_markup()


def edit_entries_keyboard(entries: Sequence[EditableEntry]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, entry in enumerate(entries, start=1):
        entry_type = entry.type.value
        label = entry.label
        button_text = f"{idx}. {label[:40]}"
        builder.button(text=button_text, callback_data=f"edit:item:{entry_type}:{entry.id}")
    builder.button(text="Назад к дням", callback_data="edit:back")
    builder.button(text="Отмена", callback_data="edit:cancel")
    builder.adjust(1)
    return builder.as_markup()


def edit_entry_actions_keyboard(entry_type: DayItemType, entry_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Изменить название",
        callback_data=f"edit:action:rename:{entry_type.value}:{entry_id}",
    )
    builder.button(
        text="Удалить",
        callback_data=f"edit:action:delete:{entry_type.value}:{entry_id}",
    )
    builder.button(text="Назад", callback_data="edit:entries")
    builder.button(text="Отмена", callback_data="edit:cancel")
    builder.adjust(1)
    return builder.as_markup()


def main_menu_keyboard(webapp_url: str | None = None) -> ReplyKeyboardMarkup:
    keyboard: list[list[KeyboardButton]] = [
        [KeyboardButton(text=MENU_TODAY_LABEL)],
        [KeyboardButton(text=MENU_TOMORROW_LABEL)],
        [KeyboardButton(text=MENU_WEEK_LABEL)],
    ]
    if webapp_url:
        keyboard.insert(0, [KeyboardButton(text=MENU_WEBAPP_LABEL, web_app=WebAppInfo(url=webapp_url))])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
