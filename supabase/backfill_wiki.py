"""Підбір картинок для глобальних продуктів через Вікіпедію (без API-ключа).

Бере продукти без http- image_url (посівні, USDA, OFF-рядки з маркером «-»),
шукає статті за назвою через MediaWiki API (пакетно: до 50 назв у запиті),
кладе URL мініатюри 330px у колонку image_url. Якщо нічого не знайшлося — пише «-».

Використання:
    python3 supabase/backfill_wiki.py --dry-run --limit 10
    python3 supabase/backfill_wiki.py --limit 900
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL  # noqa: E402
from import_off import _supabase  # noqa: E402

UA = "CaloriesBot/1.0 (telegram @My_Caloric_bot)"
API = "https://{lang}.wikipedia.org/w/api.php"
NO_IMAGE = "-"
TITLES_PER_REQUEST = 50


def pending(limit: int) -> list[dict]:
    """Глобальні продукти без справжнього URL картинки."""
    path = (
        "products?user_id=is.null"
        "&or=(image_url.is.null,image_url.eq.,image_url.eq.-)"
        "&select=id,name,image_url"
        f"&limit={limit}"
    )
    return _supabase("GET", path) or []


def candidates(name: str) -> list[str]:
    """Варіанти назв для пошуку статті — від повної до першого слова."""
    base = re.sub(r"\s+", " ", str(name or "")).strip()
    out: list[str] = []

    def add(text: str) -> None:
        text = text.strip(" ,;:.()[]")
        if text and all(text.lower() != x.lower() for x in out):
            out.append(text)

    no_paren = re.sub(r"\([^)]*\)", " ", base)
    no_num = re.sub(r"\d+[.,]?\d*\s*%?", " ", no_paren)
    words = no_num.split()

    add(base)
    add(base.split(",")[0])
    add(no_paren)
    add(no_paren.split(",")[0])
    add(no_num)
    if len(words) >= 3:
        add(" ".join(words[:2]))
    if len(words) >= 2:
        add(words[0])
    return out[:5]


def _get_json(url: str, attempts: int = 4) -> dict:
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as err:
            if attempt == attempts or err.code not in (429, 500, 503, 504):
                raise
            wait = 10 * attempt
            print(f"    спроба {attempt}/{attempts}: {err}; чекаю {wait} с")
            time.sleep(wait)
        except (urllib.error.URLError, ValueError):
            if attempt == attempts:
                raise
            time.sleep(5)
    return {}


def wiki_images(titles: list[str], lang: str) -> dict[str, str]:
    """{назва-як-надіслали: URL мініатюри} для тих назв, де є картинка."""
    out: dict[str, str] = {}
    for start in range(0, len(titles), TITLES_PER_REQUEST):
        chunk = titles[start:start + TITLES_PER_REQUEST]
        params = {
            "action": "query",
            "prop": "pageimages",
            "piprop": "thumbnail",
            "pithumbsize": "330",
            "redirects": "1",
            "titles": "|".join(chunk),
            "format": "json",
            "formatversion": "2",
        }
        data = _get_json(f"{API.format(lang=lang)}?{urllib.parse.urlencode(params)}")
        query = data.get("query") or {}

        alias: dict[str, str] = {}
        for kind in ("normalized", "converted", "redirects"):
            for pair in query.get(kind) or []:
                if pair.get("from") and pair.get("to"):
                    alias[pair["from"]] = pair["to"]

        images: dict[str, str] = {}
        for page in query.get("pages") or []:
            if page.get("missing"):
                continue
            src = str((page.get("thumbnail") or {}).get("source") or "").split("?")[0]
            if src.startswith("http"):
                images[page.get("title") or ""] = src[:500]

        for title in chunk:
            seen: set[str] = set()
            current = title
            while current and current not in seen:
                seen.add(current)
                if current in images:
                    out[title] = images[current]
                    break
                current = alias.get(current)
        time.sleep(0.4)
    return out


def match_rows(rows: list[dict]) -> dict[int, str]:
    """{id продукту: image_url} — спершу рідна мова, потім англійська."""
    by_lang: dict[str, list[tuple[dict, list[str]]]] = {"uk": [], "en": []}
    for row in rows:
        name = str(row.get("name") or "")
        lang = "uk" if re.search(r"[а-яіїєґ]", name, re.I) else "en"
        by_lang[lang].append((row, candidates(name)))

    result: dict[int, str] = {}
    for lang in ("uk", "en"):
        pairs = [(r, c) for r, c in by_lang[lang] if r["id"] not in result]
        if not pairs:
            continue
        titles: list[str] = []
        for _, cands in pairs:
            for title in cands:
                if title not in titles:
                    titles.append(title)
        print(f"  {lang}: {len(pairs)} продуктів, {len(titles)} назв у запитах")
        images = wiki_images(titles, lang)
        for row, cands in pairs:
            for title in cands:
                if images.get(title):
                    result[row["id"]] = images[title]
                    break
        if lang == "uk":
            missing = sum(1 for r, _ in pairs if r["id"] not in result)
            if missing:
                print(f"    після uk без картинки: {missing} (далі en)")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Картинки продуктів з Вікіпедії")
    ap.add_argument("--limit", type=int, default=900, help="скільки рядків опрацювати")
    ap.add_argument("--dry-run", action="store_true", help="не писати в БД, лише показати")
    args = ap.parse_args()

    if not SUPABASE_SERVICE_ROLE_KEY:
        print("Немає SUPABASE_SERVICE_ROLE_KEY")
        return 1

    rows = pending(args.limit)
    if not rows:
        print("Немає продуктів без картинки — бекфіл завершено")
        return 0
    print(f"Без картинки: {len(rows)}")

    try:
        matched = match_rows(rows)
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as err:
        print(f"Вікіпедія недоступна ({err}) — перервано, запусти ще раз")
        return 1

    found = len(matched)
    sample = [r for r in rows if r["id"] in matched][:8]
    for row in sample:
        print(f"  · {row['name']} → {matched[row['id']]}")

    if args.dry_run:
        print(f"Знайдено було б: {found} із {len(rows)}")
        return 0

    failed = 0
    for i, row in enumerate(rows, 1):
        url = matched.get(row["id"], NO_IMAGE)
        try:
            _supabase(
                "PATCH",
                f"products?id=eq.{row['id']}&user_id=is.null",
                body={"image_url": url},
                headers={"Prefer": "return=minimal"},
            )
        except urllib.error.HTTPError as err:
            failed += 1
            print(f"  Помилка запису «{row['name']}»: {err}")
            continue
        if i % 100 == 0:
            print(f"  записано {i}/{len(rows)}")

    left = len(pending(1000))
    print(f"Опрацьовано: {len(rows)}, картинок знайдено: {found}, помилок: {failed}")
    print(f"Лишилося без картинки: {left}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
