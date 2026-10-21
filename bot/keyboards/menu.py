from typing import Optional

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from bot.auth import app_user_signature
from bot.config import WEBHOOK_BASE_URL


def main_menu(user_id: Optional[int] = None) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="Профіль"), KeyboardButton(text="Статистика")]]
    if WEBHOOK_BASE_URL:
        url = f"{WEBHOOK_BASE_URL}/app"
        if user_id:
            url += f"?user_id={user_id}"
            sig = app_user_signature(user_id)
            if sig:
                url += f"&sig={sig}"
        rows.insert(
            0,
            [KeyboardButton(text="Відкрити щоденник", web_app=WebAppInfo(url=url))],
        )
    else:
        rows.insert(
            0, [KeyboardButton(text="Щоденник"), KeyboardButton(text="Пошук")]
        )
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
