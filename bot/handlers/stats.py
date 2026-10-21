from datetime import date, timedelta
from typing import Optional

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.db import get_entries, get_last_error, get_profile

router = Router(name="stats")

MEAL_LABELS = {
    "breakfast": "Сніданок",
    "lunch": "Обід",
    "dinner": "Вечеря",
    "snack": "Перекус",
}
MEAL_ORDER = ("breakfast", "lunch", "dinner", "snack")
MONTHS_GEN = (
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
)
WEEKDAYS_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд")

EMPTY_TOTALS = {"calories": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}


def _add(totals: dict, entry: dict) -> None:
    for key in EMPTY_TOTALS:
        totals[key] += float(entry.get(key) or 0)


def _fmt_g(value: float) -> str:
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def progress_bar(percent: Optional[float], width: int = 10) -> str:
    filled = 0
    if percent is not None:
        filled = max(0, min(width, round(percent / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def build_day(user_id: int, day: Optional[date] = None) -> Optional[dict]:
    """Підсумки за день. None — не вдалося прочитати БД."""
    day = day or date.today()
    entries = get_entries(user_id, day.isoformat(), day.isoformat())
    if entries is None:
        return None

    totals = dict(EMPTY_TOTALS)
    by_meal: dict[str, float] = {key: 0.0 for key in MEAL_ORDER}
    for entry in entries:
        _add(totals, entry)
        meal = entry.get("meal")
        if meal in by_meal:
            by_meal[meal] += float(entry.get("calories") or 0)

    profile = get_profile(user_id)
    tdee = float(profile["tdee"]) if profile and profile.get("tdee") else None
    return {
        "period": "day",
        "date": day,
        "totals": totals,
        "count": len(entries),
        "by_meal": [
            (MEAL_LABELS[key], by_meal[key])
            for key in MEAL_ORDER
            if by_meal[key] or any(e.get("meal") == key for e in entries)
        ],
        "tdee": tdee,
    }


def build_week(user_id: int, today: Optional[date] = None) -> Optional[dict]:
    """Підсумки за останні 7 днів (включно зі сьогодні). None — помилка БД."""
    today = today or date.today()
    start = today - timedelta(days=6)
    entries = get_entries(user_id, start.isoformat(), today.isoformat())
    if entries is None:
        return None

    per_day = {start + timedelta(days=i): {"calories": 0.0, "count": 0} for i in range(7)}
    totals = dict(EMPTY_TOTALS)
    for entry in entries:
        _add(totals, entry)
        try:
            entry_day = date.fromisoformat(str(entry.get("entry_date"))[:10])
        except ValueError:
            continue
        if entry_day in per_day:
            per_day[entry_day]["calories"] += float(entry.get("calories") or 0)
            per_day[entry_day]["count"] += 1

    active_days = sum(1 for cell in per_day.values() if cell["count"])
    average = totals["calories"] / active_days if active_days else 0.0
    profile = get_profile(user_id)
    tdee = float(profile["tdee"]) if profile and profile.get("tdee") else None
    return {
        "period": "week",
        "start": start,
        "end": today,
        "days": [(day, per_day[day]["calories"], per_day[day]["count"]) for day in per_day],
        "totals": totals,
        "active_days": active_days,
        "span": 7,
        "avg": average,
        "tdee": tdee,
    }


def format_day(stats: dict) -> str:
    totals = stats["totals"]
    tdee = stats["tdee"]
    date_label = f"{stats['date'].day} {MONTHS_GEN[stats['date'].month - 1]}"
    lines = [f"📊 <b>Статистика за сьогодні</b> · {date_label}"]

    if tdee:
        percent = totals["calories"] / tdee * 100
        left = tdee - totals["calories"]
        lines.append(
            f"Калорії: <b>{round(totals['calories'])}</b> / {round(tdee)} ккал "
            f"({round(percent)}%)"
        )
        if left >= 0:
            lines.append(f"{progress_bar(percent)}  Залишилось {round(left)} ккал")
        else:
            lines.append(f"{progress_bar(percent)}  Перевищено на {round(-left)} ккал")
    else:
        lines.append(
            f"Калорії: <b>{round(totals['calories'])}</b> ккал · норма не задана"
        )

    lines.append(
        f"Білки: {_fmt_g(totals['protein'])} г · "
        f"Жири: {_fmt_g(totals['fat'])} г · "
        f"Вуглеводи: {_fmt_g(totals['carbs'])} г"
    )
    lines.append("")
    if stats["count"]:
        lines.append(f"Записів: {stats['count']}")
        for label, kcal in stats["by_meal"]:
            lines.append(f"• {label} — {round(kcal)} ккал")
    else:
        lines.append("Ще немає записів за сьогодні. Додай їх у щоденнику 📖")
    return "\n".join(lines)


def format_week(stats: dict) -> str:
    totals = stats["totals"]
    tdee = stats["tdee"]
    lines = [
        f"📊 <b>Статистика за 7 днів</b> · "
        f"{stats['start'].strftime('%d.%m')}–{stats['end'].strftime('%d.%m')}"
    ]
    lines.append(f"Днів із записами: <b>{stats['active_days']}</b>/{stats['span']}")
    lines.append(f"Усього: <b>{round(totals['calories'])}</b> ккал")

    if stats["active_days"]:
        lines.append(f"У середньому: {round(stats['avg'])} ккал/день")
        if tdee:
            diff = stats["avg"] - tdee
            sign = "+" if diff >= 0 else "−"
            lines.append(
                f"Норма {round(tdee)} → у середньому {sign}{round(abs(diff))} ккал/день"
            )
    else:
        lines.append("Норма: —" if not tdee else f"Норма: {round(tdee)} ккал/день")

    lines.append(
        f"Білки: {_fmt_g(totals['protein'])} г · "
        f"Жири: {_fmt_g(totals['fat'])} г · "
        f"Вуглеводи: {_fmt_g(totals['carbs'])} г"
    )
    lines.append("")
    if not stats["active_days"]:
        lines.append("Ще немає записів за цей тиждень. Додай їх у щоденнику 📖")
        return "\n".join(lines)

    for day, kcal, count in stats["days"]:
        label = f"{WEEKDAYS_SHORT[day.weekday()]} {day.strftime('%d.%m')}"
        if not count:
            lines.append(f"{label}  —")
            continue
        if tdee:
            percent = kcal / tdee * 100
            lines.append(
                f"{label}  {round(kcal):>4} ккал  {progress_bar(percent)} {round(percent)}%"
            )
        else:
            lines.append(f"{label}  {round(kcal):>4} ккал")
    return "\n".join(lines)


def render(payload: Optional[dict]) -> str:
    if payload is None:
        return "⚠️ Не вдалося отримати статистику: " + (get_last_error() or "помилка БД")
    if payload["period"] == "week":
        return format_week(payload)
    return format_day(payload)


def stats_keyboard(period: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="📅 Сьогодні" if period != "day" else "📅 Сьогодні •",
                callback_data="stats:day",
            ),
            InlineKeyboardButton(
                text="🗓 За 7 днів" if period != "week" else "🗓 За 7 днів •",
                callback_data="stats:week",
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "Статистика")
async def show_stats(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        render(build_day(message.from_user.id)),
        reply_markup=stats_keyboard("day"),
    )


@router.callback_query(F.data.in_({"stats:day", "stats:week"}))
async def stats_callback(callback: CallbackQuery) -> None:
    period = callback.data.split(":", 1)[1]
    builder = build_week if period == "week" else build_day
    payload = builder(callback.from_user.id)
    text = render(payload)
    message = callback.message
    if message:
        try:
            await message.edit_text(text, reply_markup=stats_keyboard(period))
        except TelegramBadRequest:
            pass
    await callback.answer()
