from aiogram import Router
from aiogram.types import CallbackQuery, Message

router = Router(name="menu")


@router.message(lambda m: m.text == "Профіль")
async def menu_profile(message: Message) -> None:
    await message.answer("Профіль: налаштування ваги, зросту, віку та активності.")


@router.message(lambda m: m.text == "Щоденник")
async def menu_diary(message: Message) -> None:
    await message.answer("Щоденник: тут буде облік прийомів їжі.")


@router.message(lambda m: m.text == "Пошук")
async def menu_search(message: Message) -> None:
    await message.answer("Пошук продуктів з'явиться тут.")


@router.message(lambda m: m.text == "Статистика")
async def menu_stats(message: Message) -> None:
    await message.answer("Статистика за день/тиждень з'явиться тут.")


@router.callback_query()
async def fallback_callback(callback: CallbackQuery) -> None:
    await callback.answer("Ще не реалізовано.")
