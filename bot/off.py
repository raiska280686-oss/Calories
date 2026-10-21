"""Пошук продукту за штрихкодом у Open Food Facts.

Open Food Facts — відкрита база продуктів (ODbL): назва, бренд та харчова
цінність на 100 г. Використовується тільки для читання, запити кешуються
в таблиці products, тож один і той самий штрихкод не опитується повторно.
"""

import json
import urllib.request

OFF_PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
OFF_FIELDS = (
    "product_name,product_name_uk,generic_name,brands,nutriments,"
    "image_front_url,image_url,categories_tags"
)
OFF_USER_AGENT = "CaloriesBot/1.0 (Telegram calorie tracker mini app)"


def lookup_barcode(code: str, timeout: int = 12) -> dict | None:
    """Повертає дані продукту з OFF або None, якщо продукту немає."""
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())[:14]
    if len(digits) < 6:
        return None

    url = OFF_PRODUCT_URL.format(code=digits) + "?fields=" + OFF_FIELDS
    req = urllib.request.Request(
        url,
        headers={"User-Agent": OFF_USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None

    if data.get("status") != 1 or not data.get("product"):
        return None
    product = data["product"]
    nut = product.get("nutriments") or {}

    kcal = nut.get("energy-kcal_100g")
    if kcal is None and nut.get("energy_100g"):
        try:
            kcal = round(float(nut["energy_100g"]) / 4.184, 1)
        except (TypeError, ValueError):
            kcal = None

    name = (
        product.get("product_name_uk")
        or product.get("product_name")
        or product.get("generic_name")
        or ""
    ).strip()
    if not name:
        return None

    brand = (product.get("brands") or "").strip()
    return {
        "code": digits,
        "name": name,
        "brand": brand,
        "display_name": f"{name} ({brand})" if brand else name,
        "calories": float(kcal or 0),
        "protein": float(nut.get("proteins_100g") or 0),
        "fat": float(nut.get("fat_100g") or 0),
        "carbs": float(nut.get("carbohydrates_100g") or 0),
        "image_url": product.get("image_front_url") or product.get("image_url") or "",
        "categories": [c for c in (product.get("categories_tags") or []) if isinstance(c, str)][:8],
    }


def download_image(url: str, timeout: int = 15, max_bytes: int = 5 * 1024 * 1024):
    """Завантажує картинку продукту. Повертає (bytes, content_type) або None."""
    if not url or not url.startswith("http"):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": OFF_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(max_bytes + 1)
            ctype = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
    except Exception:
        return None
    if len(raw) > max_bytes or len(raw) < 100:
        return None
    if not ctype.startswith("image/"):
        return None
    return raw, ctype
