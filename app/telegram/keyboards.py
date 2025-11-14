from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MENU_TODAY_LABEL = "Расписание на сегодня"
MENU_WEEK_LABEL = "Расписание на неделю"


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


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_TODAY_LABEL)],
            [KeyboardButton(text=MENU_WEEK_LABEL)],
        ],
        resize_keyboard=True,
    )
