from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.db import get_profile, save_profile
from bot.keyboards.menu import main_menu
from bot.states.profile import ProfileForm
from bot.utils.calculator import calculate_norm

router = Router(name="profile")

ACTIVITY_LABELS = {
    1: "мінімальна",
    2: "низька",
    3: "середня",
    4: "висока",
    5: "дуже висока",
}

SEX_LABELS = {"male": "чоловіча", "female": "жіноча"}


def format_profile(profile: dict) -> str:
    return (
        "Твій профіль:\n\n"
        f"Стать: {SEX_LABELS.get(profile['sex'], profile['sex'])}\n"
        f"Вік: {profile['age']} р.\n"
        f"Зріст: {profile['height']:.0f} см\n"
        f"Вага: {profile['weight']:.0f} кг\n"
        f"Активність: {ACTIVITY_LABELS.get(profile['activity'], profile['activity'])}\n\n"
        f"BMR: {profile['bmr']:.0f} ккал\n"
        f"Добова норма: {profile['tdee']:.0f} ккал"
    )


def edit_profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Редагувати", callback_data="profile:edit")]
        ]
    )


@router.message(F.text == "Профіль")
async def show_profile(message: Message, state: FSMContext) -> None:
    await state.clear()
    profile = get_profile(message.from_user.id)
    if profile:
        await message.answer(
            format_profile(profile),
            reply_markup=edit_profile_keyboard(),
        )
    else:
        await state.set_state(ProfileForm.sex)
        await message.answer(
            "Профіль ще не створено. Вкажи стать: чоловіча чи жіноча."
        )


@router.callback_query(F.data == "profile:edit")
async def edit_profile(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileForm.sex)
    await callback.message.answer("Вкажи стать: чоловіча чи жіноча.")
    await callback.answer()


@router.message(ProfileForm.sex)
async def profile_sex(message: Message, state: FSMContext) -> None:
    value = message.text.strip().lower()
    if value.startswith("ч"):
        sex = "male"
    elif value.startswith("ж"):
        sex = "female"
    else:
        await message.answer("Будь ласка, напиши: чоловіча або жіноча.")
        return
    await state.update_data(sex=sex)
    await state.set_state(ProfileForm.age)
    await message.answer("Вкажи вік (років).")


@router.message(ProfileForm.age)
async def profile_age(message: Message, state: FSMContext) -> None:
    if not message.text.isdigit():
        await message.answer("Введи число.")
        return
    await state.update_data(age=int(message.text))
    await state.set_state(ProfileForm.height)
    await message.answer("Вкажи зріст (см).")


@router.message(ProfileForm.height)
async def profile_height(message: Message, state: FSMContext) -> None:
    try:
        height = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Введи число.")
        return
    await state.update_data(height=height)
    await state.set_state(ProfileForm.weight)
    await message.answer("Вкажи вагу (кг).")


@router.message(ProfileForm.weight)
async def profile_weight(message: Message, state: FSMContext) -> None:
    try:
        weight = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Введи число.")
        return
    await state.update_data(weight=weight)
    await state.set_state(ProfileForm.activity)
    await message.answer(
        "Рівень активності:\n"
        "1 - мінімальна\n"
        "2 - низька\n"
        "3 - середня\n"
        "4 - висока\n"
        "5 - дуже висока"
    )


@router.message(ProfileForm.activity)
async def profile_activity(message: Message, state: FSMContext) -> None:
    if message.text not in {"1", "2", "3", "4", "5"}:
        await message.answer("Введи цифру від 1 до 5.")
        return
    data = await state.get_data()
    await state.clear()

    norm = calculate_norm(
        sex=data["sex"],
        age=data["age"],
        height=data["height"],
        weight=data["weight"],
        activity=int(message.text),
    )

    profile = {**data, "activity": int(message.text), **norm}
    saved = save_profile(message.from_user.id, message.from_user.username, profile)

    await message.answer(
        "Профіль збережено"
        + ("" if saved else " локально (хранилище недоступне)")
        + ".\n\n"
        f"BMR: {norm['bmr']:.0f} ккал\n"
        f"Добова норма: {norm['tdee']:.0f} ккал",
        reply_markup=main_menu(),
    )
