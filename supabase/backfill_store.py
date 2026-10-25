#!/usr/bin/env python3
"""Фото продуктів із магазину zakaz.ua (АТБ/Silpo/Novus/Metro/Auchan).

Ланцюжок для рядка:
  1) пошук назви на zakaz.ua -> картки товарів (назва + фото 350x350 на білому фоні);
  2) нечіткий збіг назв (SequenceMatcher + покриття слів, без розмірів упаковки);
  3) фото скачується і кладеться в Supabase bucket photos (store/<id>.jpg);
  4) products.image_url = публічний URL бакета.
Якщо збіг непевний - рядок не чіпаємо (лишається попереднє фото/літера).

Використання:
    python3 supabase/backfill_store.py --dry-run --limit 20
    python3 supabase/backfill_store.py
    python3 supabase/backfill_store.py --only-blank
"""
import argparse
import difflib
import json
import random
import re
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL  # noqa: E402
from fix_food_images import (  # noqa: E402
    BAD_FILE,
    FORCE_BLANK,
    JUNK_FILE,
    LEAVE_AS_IS,
    _supabase,
)

STORE_JUNK = re.compile(
    r"свічк|свеч|декор|посуд|капсул|вітамін|таблет|крем для|шампун|зубн|"
    r"побутов|іграшк|листівк|канцеляр|фарб|клей|папір|серветк|пакет|"
    r"косметик|парфум|мило\b|гель для|порошок для|засіб|мийк|пральн",
    re.I,
)

SEARCH_URL = "https://zakaz.ua/uk/search/?q={}"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
CARD_RE = re.compile(r'<a title="([^"]+)" href="/uk/products/[^"]*">')
IMG_RE = re.compile(r'<img[^>]+src="(https://img\d*\.zakaz\.ua/[^"]+)"')
SIZE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:г|гр|кг|мл|л|шт|уп|порц)\b\.?", re.I)
CYR = re.compile(r"[а-яіїєґ]")
APOS = str.maketrans({"ʼ": "'", "’": "'", "`": "'", "´": "'"})
STOP = {"на", "з", "зі", "і", "й", "та", "у", "в", "до", "по", "для", "смак", "смаком",
        "смаку", "аромат", "ароматом", "наповнювач", "наповнювачем", "додаванням",
        "додавання", "без", "не", "що", "як", "це", "або"}


def norm(s: str) -> str:
    s = s.lower().translate(APOS)
    s = SIZE_RE.sub(" ", s)
    s = re.sub(r"[^\wа-яіїєґ%]+", " ", s, flags=re.I)
    words = [w for w in s.split() if w not in STOP]
    return " ".join(words)


def stem(w: str) -> str:
    return w[:4] if len(w) >= 4 else w


ENG2UKR = {
    "beef": "яловичина", "chicken": "курка", "pork": "свинина", "turkey": "індичка",
    "lamb": "баранина", "veal": "телятина", "rabbit": "кролик", "duck": "качка",
    "fish": "риба", "salmon": "лосось", "tuna": "тунець", "herring": "оселець",
    "mackerel": "скумбрія", "cod": "тріска", "shrimp": "креветки", "squid": "кальмар",
    "crab": "краб", "liver": "печінка", "ham": "шинка", "bacon": "бекон",
    "sausage": "ковбаса", "milk": "молоко", "cream": "вершки", "yogurt": "йогурт",
    "kefir": "кефір", "cheese": "сир", "butter": "масло", "egg": "яйце",
    "bread": "хліб", "rice": "рис", "potato": "картопля", "tomato": "помідор",
    "cucumber": "огірок", "cabbage": "капуста", "carrot": "морква", "onion": "цибуля",
    "beet": "буряк", "garlic": "часник", "pepper": "перець", "mushroom": "гриби",
    "pea": "горошок", "bean": "квасоля", "corn": "кукурудза", "pumpkin": "гарбуз",
    "zucchini": "кабачок", "spinach": "шпинат", "lettuce": "салат", "broccoli": "броколі",
    "apple": "яблуко", "banana": "банан", "orange": "апельсин", "grape": "виноград",
    "strawberry": "полуниця", "pear": "груша", "cherry": "черешня", "plum": "слива",
    "peach": "персик", "apricot": "абрикос", "melon": "диня", "watermelon": "кавун",
    "pineapple": "ананас", "lemon": "лимон", "kiwi": "ківі", "mango": "манго",
    "avocado": "авокадо", "coconut": "кокос", "raisin": "родзинки", "fig": "інжир",
    "almond": "мигдаль", "peanut": "арахіс", "walnut": "горіх", "nut": "горіх",
    "honey": "мед", "sugar": "цукор", "salt": "сіль", "flour": "борошно",
    "oat": "вівсянка", "oats": "вівсянка", "wheat": "пшениця", "rye": "жито",
    "buckwheat": "гречка", "barley": "ячмінь", "millet": "пшоно", "semolina": "манка",
    "pasta": "макарони", "noodle": "локшина", "juice": "сік", "coffee": "кава",
    "tea": "чай", "water": "вода", "oil": "олія", "chocolate": "шоколад",
    "candy": "цукерки", "cookie": "печиво", "cake": "торт", "pie": "пиріг",
    "soup": "суп", "sauce": "соус", "pudding": "пудинг", "cereal": "каша",
}
MOD_SKIP = {
    "raw", "cooked", "boiled", "baked", "fried", "roasted", "frozen", "canned",
    "dried", "fresh", "prepared", "unprepared", "ready", "eat", "with", "without",
    "added", "salt", "salted", "unsalted", "fat", "grease", "lean", "only", "meat",
    "skin", "bone", "liquid", "drained", "solids", "refuse", "portion", "and", "or",
    "the", "all", "types", "reduced", "low", "high", "nfs", "ns", "as", "to",
    "composite", "restaurant", "baby", "babyfood", "junior", "strained", "toddler",
    "formula", "powder", "mix", "dry", "sweetened", "unsweetened", "concentrate",
    "diluted", "volume", "ascorbic", "acid", "flavored", "flavour", "sodium",
}


def latin_uk_query(name: str) -> str:
    """Укр. запит з англ. назви, лише якщо всі значущі слова відомі."""
    words = re.findall(r"[a-z]+", name.lower())
    content = [w for w in words if len(w) > 2 and w not in MOD_SKIP]
    if not content:
        return ""
    mapped = [ENG2UKR.get(w) for w in content]
    if any(m is None for m in mapped):
        return ""
    out = []
    for m in mapped:
        if m not in out:
            out.append(m)
    pcts = re.findall(r"\d+(?:[.,]\d+)?%", name)
    return " ".join(out[:3] + pcts)


SYN_QUERIES = {
    "виноград": ["родзинки"],
    "кишмиш": ["родзинки"],
    "мюслі": ["батончик мюслі", "мюслі батончик"],
    "карпатський": ["йогурт галичина"],
    "паста krem": ["паста шоколадна", "горіхова паста"],
    "гарнір": ["овочевий гарнір"],
    "індичка грудка": ["грудка індички", "філе індички"],
    "курка грудка": ["грудка куряча", "філе куряче"],
    "риба біла": ["риба біла заморожена", "минтай"],
    "яйце жовток": ["яйця курячі"],
    "яйце білок": ["яйця курячі"],
    "макарони відварні": ["макарони"],
    "горох варений": ["горох зелений", "горох"],
}


def attempt_queries(name: str) -> list[str]:
    tokens = [w for w in norm(name).split() if len(w) > 2]
    raw = [name[:120], " ".join(tokens[:4]), " ".join(tokens[:2]),
           tokens[0] if tokens else name[:120]]
    low = name.lower()
    for k, extra in SYN_QUERIES.items():
        if k in low:
            raw = extra + raw
    out = []
    for q in raw:
        q = q.strip()
        if q and q not in out:
            out.append(q)
    return out


def plausible_title(title: str) -> bool:
    return not (JUNK_FILE.search(title) or BAD_FILE.search(title) or STORE_JUNK.search(title))


def name_score(query: str, title: str) -> tuple[float, float]:
    q, t = norm(query), norm(title)
    if not q or not t:
        return 0.0, 0.0
    ratio = difflib.SequenceMatcher(None, q, t).ratio()
    qw = {stem(w) for w in q.split() if len(w) > 1}
    tw = {stem(w) for w in t.split()}
    cover = len(qw & tw) / len(qw) if qw else 0.0
    q_pct = set(re.findall(r"\d+(?:[.,]\d+)?%", q))
    t_pct = set(re.findall(r"\d+(?:[.,]\d+)?%", t))
    if q_pct and t_pct and q_pct != t_pct:
        return 0.0, 0.0
    sc = 0.55 * ratio + 0.45 * cover
    if cover == 1.0:
        sc = max(sc, 0.65)
    return sc, cover


def _stuck(_sig, _frame):
    raise TimeoutError("network call stuck")


signal.signal(signal.SIGALRM, _stuck)


def guarded(fn, *args, **kwargs):
    signal.alarm(45)
    try:
        return fn(*args, **kwargs)
    finally:
        signal.alarm(0)


OFF_SEARCH = "https://search.openfoodfacts.org/search?{}"
OFF_UA = "kalorii-app/1.0 (products photos)"


def off_search(query: str) -> list[tuple[str, str]]:
    params = urllib.parse.urlencode({
        "q": query[:80], "page_size": 12,
        "fields": "product_name,image_front_url",
    })
    req = urllib.request.Request(
        OFF_SEARCH.format(params),
        headers={"User-Agent": OFF_UA, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    out = []
    for h in data.get("hits") or []:
        name = (h.get("product_name") or "").strip()
        img = (h.get("image_front_url") or "").strip()
        if name and img.startswith("http"):
            out.append((name, img))
    return out


def off_pick(name: str) -> tuple[float, str, str] | None:
    cyr = bool(CYR.search(name))
    best = None
    for attempt in attempt_queries(name):
        try:
            hits = guarded(off_search, attempt)
        except (TimeoutError, urllib.error.HTTPError, urllib.error.URLError, OSError):
            continue
        for title, img in hits:
            sc, cover = name_score(name, title)
            if cyr and cover < 0.8:
                continue
            if not cyr and cover < 0.5:
                continue
            if sc < 0.55:
                continue
            if best is None or sc > best[0]:
                best = (sc, title, img)
        if best and best[0] >= 0.85:
            break
        time.sleep(0.5)
    return best


def fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": BROWSER_UA, "Accept-Language": "uk-UA,uk;q=0.9"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def search_products(name: str) -> list[tuple[str, str]]:
    html = fetch(SEARCH_URL.format(urllib.parse.quote(name[:120])))
    cards, seen = [], set()
    starts = [m.start() for m in CARD_RE.finditer(html)]
    for i, pos in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else pos + 4000
        block = html[pos:end]
        title = CARD_RE.match(block).group(1)
        img = IMG_RE.search(block)
        if not img:
            continue
        key = (title, img.group(1))
        if key in seen:
            continue
        seen.add(key)
        cards.append(key)
    return cards


def fetch_image(url: str) -> tuple[bytes, str] | None:
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read(5 * 1024 * 1024 + 1)
            ctype = (r.headers.get("Content-Type") or "").lower()
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return None
    if len(raw) > 5 * 1024 * 1024 or len(raw) < 200 or "image" not in ctype:
        return None
    return raw, ctype


def upload_photo(product_id: int, raw: bytes, ctype: str = "image/jpeg") -> str:
    ext = {"image/png": "png", "image/webp": "webp"}.get(ctype, "jpg")
    name = f"store/{product_id}.{ext}"
    key = SUPABASE_SERVICE_ROLE_KEY
    req = urllib.request.Request(
        f"{SUPABASE_URL}/storage/v1/object/photos/{name}",
        data=raw,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": ctype,
            "x-upsert": "true",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60):
        pass
    return f"{SUPABASE_URL}/storage/v1/object/public/photos/{name}"


def load_rows(only_blank: bool) -> list[dict]:
    rows, off = [], 0
    while True:
        page = _supabase(
            "GET",
            "products?user_id=is.null&select=id,name,image_url"
            f"&limit=1000&offset={off}",
        ) or []
        rows += page
        if len(page) < 1000:
            break
        off += 1000
    out = []
    for r in rows:
        if r["name"] in FORCE_BLANK or r["name"] in LEAVE_AS_IS:
            continue
        url = r.get("image_url") or ""
        if only_blank and url.startswith("http"):
            continue
        if not only_blank and "/storage/v1/object/public/photos/store/" in url:
            continue
        out.append(r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Фото продуктів із zakaz.ua у bucket photos")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=100000)
    ap.add_argument("--only-blank", action="store_true", help="лише рядки без фото")
    ap.add_argument("--off", action="store_true",
                    help="друга стадія: Open Food Facts, якщо zakaz.ua не знайшов")
    ap.add_argument("--source", choices=["all", "wiki", "blank"], default="all",
                    help="all | wiki (лише з Вікіпедії) | blank (лише без фото)")
    ap.add_argument("--min-score", type=float, default=0.60)
    ap.add_argument("--min-cover", type=float, default=0.5)
    args = ap.parse_args()

    only_blank = args.only_blank or args.source == "blank"
    rows = load_rows(only_blank)
    if args.source == "wiki":
        rows = [r for r in rows if any(
            d in (r.get('image_url') or '') for d in ('wikimedia.org', 'wikipedia.org'))]
    rows = rows[: args.limit]
    print(f"Рядків до обробки: {len(rows)}")

    filled, weak, errors = [], [], 0
    for i, row in enumerate(rows, 1):
        if i % 50 == 0:
            print(f"  {i}/{len(rows)}: замінено {len(filled)}, непевних {len(weak)}, "
                  f"помилок {errors}", flush=True)
        name = row["name"]
        query_name = name
        cover_req = args.min_cover
        if not CYR.search(name):
            query_name = latin_uk_query(name)
            cover_req = 1.0
        cards, best, netdown = [], None, False
        for attempt in (attempt_queries(query_name) if query_name else []):
            try:
                found = guarded(search_products, attempt)
            except urllib.error.HTTPError as err:
                if err.code in (403, 429) or err.code >= 500:
                    errors += 1
                    print(f"  «{name}»: HTTP {err.code}, чекаю")
                    netdown = True
                    time.sleep(30)
                    break
                found = []
            except (TimeoutError, urllib.error.URLError, OSError) as err:
                errors += 1
                print(f"  «{name}»: пошук недоступний ({err})")
                netdown = True
                time.sleep(15)
                break
            cards += [c for c in found if c not in cards]
            score_q = attempt if (not CYR.search(name) and query_name) else attempt
            if not CYR.search(name) and query_name:
                score_q = query_name
            elif not CYR.search(name):
                score_q = name
            else:
                score_q = attempt
            for title, img in found:
                if not plausible_title(title):
                    continue
                sc, cover = name_score(score_q, title)
                if cover < cover_req or sc < args.min_score:
                    continue
                if best is None or sc > best[0]:
                    best = (sc, title, img)
            if best and best[0] >= 0.85:
                break
            time.sleep(0.7 + random.random() * 0.4)
        if netdown:
            if errors >= 5:
                print("Забагато помилок мережі - зупиняюсь.")
                break
            continue
        if best is None and args.off:
            off = off_pick(name)
            if off:
                best = off
        time.sleep(0.9 + random.random() * 0.4)
        if not best:
            weak.append((name, cards[0][0] if cards else "", cards and name_score(name, cards[0][0])[0] or 0.0))
            if args.dry_run:
                good = [c for c in cards if plausible_title(c[0])]
                top = max(good, key=lambda c: name_score(query_name, c[0])[0]) if good else None
                print(f"  ✗ «{name}»" + (f" ~ {top[0][:60]} [{name_score(query_name, top[0])[0]:.2f}]" if top else " (нічого)"))
            continue
        sc, title, img = best
        if args.dry_run:
            print(f"  ✓ «{name}» -> {title[:60]} [{sc:.2f}]")
            filled.append((name, img))
            continue
        fetched = guarded(fetch_image, img)
        if not fetched:
            errors += 1
            print(f"  «{name}»: фото не скачалось")
            continue
        raw, ctype = fetched
        try:
            public = guarded(upload_photo, row["id"], raw, ctype)
            guarded(
                _supabase,
                "PATCH",
                f"products?id=eq.{row['id']}&user_id=is.null",
                body={"image_url": public},
                headers={"Prefer": "return=minimal"},
            )
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, RuntimeError) as err:
            errors += 1
            print(f"  «{name}»: запис не вдався ({err})")
            continue
        filled.append((name, title, sc))

    print(f"\n{'Було б замінено' if args.dry_run else 'Замінено'}: {len(filled)}, "
          f"непевних: {len(weak)}, помилок: {errors}")
    if not args.dry_run and weak:
        log = Path(__file__).resolve().parent.parent / ".logs" / "store_unmatched.txt"
        log.write_text("".join(f"{n}\t{t}\t{s:.2f}\n" for n, t, s in weak))
        print(f"Непевні збіги: {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
