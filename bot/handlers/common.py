from aiogram import Router
from aiogram.types import CallbackQuery, Message

router = Router(name="menu")


@router.message(lambda m: m.text == "Щоденник")
async def menu_diary(message: Message) -> None:
    await message.answer("Щоденник: тут буде облік прийомів їжі.")


@router.message(lambda m: m.text == "Пошук")
async def menu_search(message: Message) -> None:
    await message.answer("Пошук продуктів з'явиться тут.")


@router.callback_query()
async def fallback_callback(callback: CallbackQuery) -> None:
    await callback.answer("Ще не реалізовано.")
