"""Бекфіл image_url для глобальних продуктів, уже імпортованих з Open Food Facts.

Бере глобальні продукти зі штрихкодом (brand — число) і порожнім image_url,
питає у OFF картинку за кодом і пише її в колонку image_url.
Маркер «-» означає, що у OFF картинки немає — такий рядок більше не чіпаємо.

Використання:
    python3 supabase/backfill_images.py --dry-run --limit 20
    python3 supabase/backfill_images.py --limit 1000
"""

import argparse
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL  # noqa: E402
from import_off import _get_json, _supabase  # noqa: E402

NO_IMAGE = "-"


def pending(limit: int) -> list[dict]:
    """Глобальні продукти зі штрихкодом і без картинки."""
    path = (
        "products?user_id=is.null&brand=not.is.null&brand=not.like.fdc-*"
        "&or=(image_url.is.null,image_url.eq.)"
        f"&select=id,brand,image_url&limit={limit}"
    )
    return _supabase("GET", path) or []


def image_for(code: str) -> str:
    """URL картинки з OFF (400px) або маркер «-», якщо картинки немає."""
    try:
        data = _get_json(
            "https://world.openfoodfacts.org/api/v2/product/"
            f"{code}?fields=image_front_url,image_url",
            attempts=3,
        )
    except urllib.error.HTTPError as err:
        if err.code in (404, 400):
            return NO_IMAGE
        raise
    if not isinstance(data, dict) or data.get("status") != 1:
        return NO_IMAGE
    product = data.get("product") or {}
    url = str(product.get("image_front_url") or product.get("image_url") or "").strip()
    return url[:500] if url.startswith("http") else NO_IMAGE


def main() -> int:
    ap = argparse.ArgumentParser(description="Бекфіл image_url з Open Food Facts")
    ap.add_argument("--limit", type=int, default=1000, help="скільки рядків опрацювати за раз")
    ap.add_argument("--sleep", type=float, default=0.5, help="пауза між запитами до OFF, с")
    ap.add_argument("--dry-run", action="store_true", help="не писати в БД, лише показати")
    args = ap.parse_args()

    if not SUPABASE_SERVICE_ROLE_KEY:
        print("Немає SUPABASE_SERVICE_ROLE_KEY")
        return 1

    rows = pending(args.limit)
    if not rows:
        print("Немає продуктів без картинки — бекфіл завершено")
        return 0

    print(f"Без картинки (зі штрихкодом): {len(rows)}")
    done = no_image = failed = 0
    for row in rows:
        code = str(row.get("brand") or "")
        try:
            url = image_for(code)
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as err:
            print(f"OFF недоступний ({err}) — перериваю, запусти ще раз")
            break

        if url == NO_IMAGE:
            no_image += 1
        if args.dry_run:
            done += 1
            if done <= 15:
                print(f"  · {code} → {url}")
            continue

        try:
            _supabase(
                "PATCH",
                f"products?id=eq.{row['id']}&user_id=is.null",
                body={"image_url": url},
                headers={"Prefer": "return=minimal"},
            )
        except urllib.error.HTTPError as err:
            failed += 1
            print(f"  Помилка запису {code}: {err}")
            continue
        done += 1
        if done % 100 == 0:
            print(f"  оновлено {done}...")
        time.sleep(args.sleep)

    print(
        f"{'Опрацювано було б' if args.dry_run else 'Опрацювано'}: {done}, "
        f"без картинки в OFF: {no_image}, помилок запису: {failed}"
    )
    left = pending(1)
    print(f"Лишилося без картинки: {len(left)}{'+' if len(left) else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
