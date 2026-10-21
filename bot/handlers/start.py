from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.db import get_last_error, get_profile
from bot.keyboards.menu import main_menu

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    text = "Вітаю! Я бот для підрахунку калорій.\n\nОбери дію в меню нижче."

    profile = get_profile(message.from_user.id)
    error = get_last_error()
    if error:
        text = (
            "⚠️ Немає доступу до бази даних.\n"
            "Перевір налаштування SUPABASE_JWT_SECRET і RLS-політики."
        )
    elif profile:
        text = (
            "Вітаю! Я бот для підрахунку калорій.\n\n"
            f"Твій профіль: {profile['sex']}, {profile['age']} р., "
            f"{profile['height']:.0f} см, {profile['weight']:.0f} кг\n"
            f"Добова норма: {profile['tdee']:.0f} ккал\n\n"
            "Обери дію в меню нижче."
        )

    await message.answer(text, reply_markup=main_menu(message.from_user.id))
