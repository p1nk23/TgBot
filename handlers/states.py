from aiogram.fsm.state import State, StatesGroup

class Navigation(StatesGroup):
    current_forder_id = State()