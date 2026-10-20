from aiogram.fsm.state import State, StatesGroup


class ProfileForm(StatesGroup):
    sex = State()
    age = State()
    height = State()
    weight = State()
    activity = State()
