from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


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
