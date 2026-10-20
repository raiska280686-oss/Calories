from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.db import get_profile
from bot.keyboards.menu import main_menu

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    text = "Вітаю! Я бот для підрахунку калорій.\n\nОбери дію в меню нижче."

    profile = get_profile(message.from_user.id)
    if profile:
        text = (
            "Вітаю! Я бот для підрахунку калорій.\n\n"
            f"Твій профіль: {profile['sex']}, {profile['age']} р., "
            f"{profile['height']:.0f} см, {profile['weight']:.0f} кг\n"
            f"Добова норма: {profile['tdee']:.0f} ккал\n\n"
            "Обери дію в меню нижче."
        )

    await message.answer(text, reply_markup=main_menu())
