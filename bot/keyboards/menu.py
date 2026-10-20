from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Щоденник"), KeyboardButton(text="Пошук")],
            [KeyboardButton(text="Профіль"), KeyboardButton(text="Статистика")],
        ],
        resize_keyboard=True,
    )
