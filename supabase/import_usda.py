"""Імпорт продуктів з USDA FoodData Central у глобальну таблицю products.

Назви англійські, значення на 100 г (Foundation / SR Legacy / Survey FNDDS).
Береться DEMO_KEY, тому діють ліміти запитів USDA — при потребі передай свій
ключ: --api-key <KEY>.

Використання:
    python3 supabase/import_usda.py --dry-run --limit 30   # подивитися приклади
    python3 supabase/import_usda.py --limit 2000           # імпортувати
"""

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from import_off import (  # noqa: E402
    MAX_KCAL,
    _get_json,
    _supabase,
    clean_name,
    consistent,
    existing_codes,
)

USDA_API = "https://api.nal.usda.gov/fdc/v1/foods/list"
DEFAULT_KEY = "DEMO_KEY"
PAGE_SIZE = 200
DEFAULT_TYPES = ["Foundation", "SR Legacy", "Survey (FNDDS)"]

PROTEIN_IDS = {"203", "1003"}
FAT_IDS = {"204", "1004"}
CARB_IDS = {"205", "1005"}
ALCOHOL_IDS = {"221", "1001", "501"}
ENERGY_PREF = ("957", "208", "1008", "2047", "958", "2048")


def fetch_pages(api_key: str, data_types: list, pages: int, sleep: float, start: int = 1):
    for page in range(start, start + pages):
        params = [
            ("api_key", api_key),
            ("pageSize", str(PAGE_SIZE)),
            ("pageNumber", str(page)),
        ]
        params += [("dataType", dt) for dt in data_types]
        data = _get_json(f"{USDA_API}?{urllib.parse.urlencode(params)}", attempts=2)
        foods = data if isinstance(data, list) else (data.get("foods") or [])
        print(f"  сторінка {page}: {len(foods)} записів")
        if not foods:
            return
        yield from foods
        time.sleep(sleep)


def _num(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def extract(food: dict) -> dict | None:
    items = food.get("foodNutrients") or food.get("nutrients") or []
    protein = fat = carbs = alcohol = None
    energies: dict[str, float] = {}
    for item in items:
        number = item.get("number")
        if number is None:
            number = item.get("nutrientNumber")
        num = str(number or "")
        name = str(item.get("name") or item.get("nutrientName") or "")
        unit = str(item.get("unitName") or "").upper()
        value = _num(item.get("amount") if item.get("amount") is not None else item.get("value"))
        if value is None:
            continue
        if num in PROTEIN_IDS:
            protein = value
        elif num in FAT_IDS:
            fat = value
        elif num in CARB_IDS:
            carbs = value
        elif num in ALCOHOL_IDS:
            alcohol = value
        elif name.startswith("Energy") and unit in ("", "KCAL"):
            energies.setdefault(num, value)

    kcal = next((energies[key] for key in ENERGY_PREF if energies.get(key)), None)
    if kcal is None:
        kcal = next((v for v in energies.values() if v), None)
    name = clean_name(food.get("description"))
    if not name or kcal is None or not (0 < kcal <= MAX_KCAL):
        return None

    protein = round(max(0.0, protein or 0.0), 1)
    fat = round(max(0.0, fat or 0.0), 1)
    carbs = round(max(0.0, carbs or 0.0), 1)
    alcohol = round(max(0.0, alcohol or 0.0), 1)
    if not consistent(kcal, protein, fat, carbs, alcohol):
        return None

    fdc_id = food.get("fdcId")
    if not fdc_id:
        return None
    return {
        "user_id": None,
        "name": name,
        "calories": round(kcal, 1),
        "protein": protein,
        "fat": fat,
        "carbs": carbs,
        "brand": f"fdc-{fdc_id}",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Імпорт продуктів з USDA FoodData Central")
    ap.add_argument("--limit", type=int, default=2000, help="скільки продуктів додати")
    ap.add_argument("--pages", type=int, default=30, help="максимум сторінок USDA")
    ap.add_argument("--start-page", type=int, default=1, help="з якої сторінки продовжити")
    ap.add_argument("--types", default=",".join(DEFAULT_TYPES),
                    help="dataType через кому (Foundation, SR Legacy, Survey (FNDDS))")
    ap.add_argument("--sleep", type=float, default=1.5, help="пауза між запитами до USDA, с")
    ap.add_argument("--batch", type=int, default=200, help="розмір пакета в Supabase")
    ap.add_argument("--api-key", default=DEFAULT_KEY, help="ключ USDA (DEMO_KEY за замовчуванням)")
    ap.add_argument("--dry-run", action="store_true", help="не писати в БД, лише показати")
    args = ap.parse_args()

    data_types = [t.strip() for t in args.types.split(",") if t.strip()]
    print("Наявні коди в БД...", end=" ", flush=True)
    known = existing_codes()
    print(f"{len(known)}")

    added, skipped_dup, skipped_invalid, scanned = [], 0, 0, 0
    buffer = []
    error = None
    try:
        for food in fetch_pages(args.api_key, data_types, args.pages, args.sleep, args.start_page):
            scanned += 1
            row = extract(food)
            if not row:
                skipped_invalid += 1
                continue
            if row["brand"] in known:
                skipped_dup += 1
                continue
            known.add(row["brand"])

            if args.dry_run:
                added.append(row)
                if len(added) >= args.limit:
                    break
                continue

            buffer.append(row)
            if len(buffer) >= args.batch:
                _supabase("POST", "products", body=buffer, headers={"Prefer": "return=minimal"})
                added.extend(buffer)
                buffer.clear()
                print(f"  вставлено {len(added)} (переглянуто {scanned}, дублікатів {skipped_dup})")
            if len(added) >= args.limit:
                break
    except Exception as err:  # ліміт USDA / мережа — просто зупиняємось
        error = err

    if buffer and not args.dry_run:
        _supabase("POST", "products", body=buffer, headers={"Prefer": "return=minimal"})
        added.extend(buffer)

    print(f"\nПереглянуто записів USDA: {scanned}")
    print(f"Без назви/калорій або непослідовних: {skipped_invalid}")
    print(f"Пропущено дублікатів: {skipped_dup}")
    print(f"{'Додано було б' if args.dry_run else 'Додано'}: {len(added)}")
    for row in added[:5]:
        print(
            f"  · {row['name']} — {row['calories']} ккал, "
            f"Б/Ж/В {row['protein']}/{row['fat']}/{row['carbs']} ({row['brand']})"
        )
    if error:
        print(f"\nUSDA недоступний ({error}). Запусти ще раз — наявні коди пропускаються.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
