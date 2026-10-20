from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from bot.config import WEBHOOK_BASE_URL


def main_menu() -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="Профіль"), KeyboardButton(text="Статистика")]]
    if WEBHOOK_BASE_URL:
        rows.insert(
            0,
            [
                KeyboardButton(
                    text="Відкрити щоденник",
                    web_app=WebAppInfo(url=f"{WEBHOOK_BASE_URL}/app/"),
                )
            ],
        )
    else:
        rows.insert(
            0, [KeyboardButton(text="Щоденник"), KeyboardButton(text="Пошук")]
        )
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
