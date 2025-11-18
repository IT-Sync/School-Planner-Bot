from aiogram.fsm.state import State, StatesGroup


class LessonsState(StatesGroup):
    choosing_day = State()
    waiting_for_text = State()
    confirming = State()


class ExtrasState(StatesGroup):
    choosing_day = State()
    waiting_for_text = State()
    confirming = State()


class EditState(StatesGroup):
    choosing_day = State()
    choosing_entry = State()
    choosing_action = State()
    waiting_for_label = State()
