from aiogram.fsm.state import State, StatesGroup


class LessonsState(StatesGroup):
    choosing_day = State()
    waiting_for_text = State()
    confirming = State()


class ExtrasState(StatesGroup):
    choosing_day = State()
    waiting_for_text = State()
    confirming = State()
