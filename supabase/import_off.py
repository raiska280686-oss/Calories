"""Масовий імпорт продуктів з Open Food Facts у глобальну таблицю products.

Продукти зберігаються як глобальні (user_id = null): їх бачать усі користувачі.
У колонку brand записується штрихкод — так само, як у кеші barcode_lookup.

Використання:
    python3 supabase/import_off.py --dry-run --limit 50   # подивитися приклади
    python3 supabase/import_off.py --limit 1500           # імпортувати
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL  # noqa: E402

OFF_API = "https://world.openfoodfacts.org/api/v2/search"
UA = "CaloriesBot/1.0 (telegram @My_Caloric_bot)"
PAGE_SIZE = 100
MAX_KCAL = 900


def _get_json(url: str, attempts: int = 8) -> dict:
    """GET з повторами: OFF іноді віддає 5xx на важких запитах."""
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as err:
            if attempt == attempts:
                raise
            wait = min(4 * attempt, 30)
            print(f"    спроба {attempt}/{attempts} не вдалася ({err}); чекаю {wait} с")
            time.sleep(wait)


def _supabase(method: str, path: str, body=None, headers: dict | None = None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    base = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    base.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=base, method=method)
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode()
    return json.loads(raw) if raw else None


def existing_codes() -> set:
    """Усі штрихкоди, які вже є в products (brand = код)."""
    codes = set()
    offset = 0
    while True:
        rows = _supabase(
            "GET", f"products?select=brand&brand=not.is.null&limit=1000&offset={offset}"
        ) or []
        codes.update(str(r["brand"]) for r in rows)
        if len(rows) < 1000:
            return codes
        offset += 1000


def clean_name(raw) -> str:
    return " ".join(str(raw or "").split())[:200]


def consistent(calories: float, protein: float, fat: float, carbs: float,
               alcohol: float = 0.0) -> bool:
    """Перевірка за Атуотером: ккал має бути близьким до 4·Б + 9·Ж + 4·В + 7·СПТ.

    Ловить записи, де ккал вказано «на пачку/порцію», а не на 100 г.
    """
    atwater = 4 * protein + 9 * fat + 4 * carbs + 7 * alcohol
    if calories <= 5 and atwater <= 5:
        return True  # дієт-напої/вода з округленими нулями
    if atwater <= 0:
        return False
    return 0.5 * atwater <= calories <= 2.0 * atwater


def consistent_row(row: dict) -> bool:
    """Мʼякша перевірка для вже завантажених рядків (без даних про спирт)."""
    calories = float(row["calories"] or 0)
    atwater = (
        4 * float(row["protein"] or 0)
        + 9 * float(row["fat"] or 0)
        + 4 * float(row["carbs"] or 0)
    )
    if calories <= 5:
        return True
    if atwater <= 0:
        return False
    if calories > 300 and calories > 3 * atwater:
        return False  # явно «не на 100 г»
    return calories >= 0.25 * atwater


def to_row(p: dict) -> dict | None:
    code = str(p.get("code") or "").strip()
    if not code.isdigit() or not (6 <= len(code) <= 14):
        return None
    name = clean_name(p.get("product_name_uk")) or clean_name(p.get("product_name"))
    if not name:
        return None

    nutriments = p.get("nutriments") or {}

    def num(key):
        try:
            return float(nutriments.get(key))
        except (TypeError, ValueError):
            return None

    kcal = num("energy-kcal_100g")
    if kcal is None:
        kj = num("energy-kj_100g")
        kcal = round(kj / 4.184, 1) if kj else None
    if kcal is None or not (0 < kcal <= MAX_KCAL):
        return None

    protein = round(max(0.0, num("proteins_100g") or 0.0), 1)
    fat = round(max(0.0, num("fat_100g") or 0.0), 1)
    carbs = round(max(0.0, num("carbohydrates_100g") or 0.0), 1)
    alcohol = round(max(0.0, num("alcohol_100g") or 0.0), 1)
    if not consistent(kcal, protein, fat, carbs, alcohol):
        return None

    return {
        "user_id": None,
        "name": name,
        "calories": round(kcal, 1),
        "protein": protein,
        "fat": fat,
        "carbs": carbs,
        "brand": code,
    }


def fetch_products(country: str, pages: int, sleep: float, sort: str = "", start: int = 1):
    for page in range(start, start + pages):
        params = {
            "page_size": str(PAGE_SIZE),
            "page": str(page),
            "fields": "code,product_name,product_name_uk,brands,nutriments",
        }
        if country:
            params["countries_tags_en"] = country
        if sort:
            params["sort_by"] = sort
        data = _get_json(f"{OFF_API}?{urllib.parse.urlencode(params)}")
        products = data.get("products") or []
        print(f"  сторінка {page}: {len(products)} записів (усього в базі OFF: {data.get('count')})")
        if not products:
            return
        yield from products
        time.sleep(sleep)


def recheck_global(dry_run: bool = False) -> int:
    """Видаляє глобальні продукти з непослідовною калорійністю (ккал vs Б/Ж/В)."""
    rows, offset = [], 0
    while True:
        page = _supabase(
            "GET",
            f"products?user_id=is.null&select=id,name,calories,protein,fat,carbs"
            f"&limit=1000&offset={offset}",
        ) or []
        rows.extend(page)
        if len(page) < 1000:
            break
        offset += 1000

    bad = [r for r in rows if not consistent_row(r)]
    print(f"Перевірено глобальних продуктів: {len(rows)}, непослідовних: {len(bad)}")
    for r in bad[:8]:
        print(
            f"  · {r['name']} — {r['calories']} ккал, "
            f"Б/Ж/В {r['protein']}/{r['fat']}/{r['carbs']}"
        )
    if dry_run:
        return len(bad)
    for i in range(0, len(bad), 500):
        chunk = ",".join(str(r["id"]) for r in bad[i:i + 500])
        _supabase("DELETE", f"products?id=in.({chunk})&user_id=is.null")
        print(f"  видалено {min(500, len(bad) - i)}")
    return len(bad)


def main() -> int:
    ap = argparse.ArgumentParser(description="Імпорт продуктів з Open Food Facts")
    ap.add_argument("--limit", type=int, default=2000, help="скільки продуктів додати")
    ap.add_argument("--pages", type=int, default=60, help="максимум сторінок OFF")
    ap.add_argument("--start-page", type=int, default=1, help="з якої сторінки продовжити")
    ap.add_argument("--country", default="ukraine", help="країна (порожній рядок — будь-яка)")
    ap.add_argument("--sleep", type=float, default=8.0, help="пауза між запитами до OFF, с")
    ap.add_argument("--sort", default="", help="сортування OFF (напр. popularity_key; зараз 503)")
    ap.add_argument("--batch", type=int, default=200, help="розмір пакета в Supabase")
    ap.add_argument("--dry-run", action="store_true", help="не писати в БД, лише показати")
    ap.add_argument("--recheck", action="store_true",
                    help="перевірити наявні глобальні продукти й видалити непослідовні")
    args = ap.parse_args()

    if not SUPABASE_SERVICE_ROLE_KEY:
        print("Немає SUPABASE_SERVICE_ROLE_KEY")
        return 1

    if args.recheck:
        recheck_global(args.dry_run)
        return 0

    print(f"Наявні штрихкоди в БД...", end=" ", flush=True)
    known = existing_codes()
    print(f"{len(known)}")

    added, skipped_dup, skipped_invalid, scanned = [], 0, 0, 0
    buffer = []
    error = None
    try:
        for product in fetch_products(args.country, args.pages, args.sleep, args.sort, args.start_page):
            scanned += 1
            row = to_row(product)
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
    except (urllib.error.HTTPError, urllib.error.URLError) as err:
        error = err

    if buffer and not args.dry_run:
        _supabase("POST", "products", body=buffer, headers={"Prefer": "return=minimal"})
        added.extend(buffer)

    print(f"\nПереглянуто записів OFF: {scanned}")
    print(f"Без назви або без поживних речовин: {skipped_invalid}")
    print(f"Пропущено дублікатів: {skipped_dup}")
    print(f"{'Додано було б' if args.dry_run else 'Додано'}: {len(added)}")
    for row in added[:5]:
        print(
            f"  · {row['name']} — {row['calories']} ккал, "
            f"Б/Ж/В {row['protein']}/{row['fat']}/{row['carbs']} (код {row['brand']})"
        )
    if error:
        print(f"\nOFF недоступний ({error}). Запусти команду ще раз — наявні штрихкоди пропускаються.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
