#!/usr/bin/env python3
"""Фото страв: англ. запити в Commons -> MealDB -> "-".

Ланцюжок для проблемного рядка:
  1) переклад назви (словник uk->en) -> запит у Commons ("boiled chicken breast",
     "stewed beef", "peanuts") з фільтрами: у назві файлу має бути СЛОВО
     ПРОДУКТУ, а для варених/смажених - ще й слово приготування;
  2) якщо нічого - TheMealDB (реальні фото страв);
  3) інакше "-" (літерна аватарка у застосунку).
"Babyfood"/"Baby Toddler" (USDA) - без мережі, одразу "-".
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

from backfill_wiki import UA  # noqa: E402
from fix_food_images import (  # noqa: E402
    BAD_FILE,
    FORCE_BLANK,
    JUNK_FILE,
    LEAVE_AS_IS,
    NO_IMAGE,
    POSITIVE,
    PREPARED,
    _supabase,
    commons_search,
    file_name_from_url,
    rows_to_fix,
    score,
)

UK_EN = {
    "курят": "chicken", "курк": "chicken", "курич": "chicken", "куряч": "chicken",
    "індич": "turkey", "свинин": "pork", "свиняч": "pork", "ялович": "beef",
    "телятин": "veal", "баранин": "lamb", "кролик": "rabbit", "м\u02bcяс": "meat", "мяс": "meat",
    "печінк": "liver", "риб": "fish", "скумбрі": "mackerel", "сьомг": "salmon",
    "оселед": "herring", "тунец": "tuna", "кревет": "shrimp",
    "арахіс": "peanut", "горіх": "walnut", "мигдал": "almond",
    "фундук": "hazelnut", "соняшник": "sunflower seeds", "гарбузов": "pumpkin seeds",
    "картопл": "potato", "помідор": "tomato", "томат": "tomato", "огірк": "cucumber",
    "моркв": "carrot", "буряк": "beet", "капуст": "cabbage", "цибул": "onion",
    "часник": "garlic", "перець": "pepper", "кабач": "zucchini", "баклаж": "eggplant",
    "броколі": "broccoli", "шпинат": "spinach", "салат": "salad", "гриб": "mushroom",
    "яблук": "apple", "груш": "pear", "апельсин": "orange", "мандарин": "tangerine",
    "лимон": "lemon", "банан": "banana", "виноград": "grape", "полуниц": "strawberry",
    "малин": "raspberry", "чорниц": "blueberry", "вишн": "cherry", "слив": "plum",
    "персик": "peach", "абрикос": "apricot", "кавун": "watermelon", "смородин": "blackcurrant", "манн": "semolina", "дин": "melon",
    "хурм": "persimmon", "ананас": "pineapple", "ківі": "kiwi", "гранат": "pomegranate",
    "рис": "rice", "гречк": "buckwheat", "вівсян": "oats", "пшон": "millet",
    "перлов": "barley", "макарон": "pasta", "вермішел": "noodles",
    "локшин": "noodles", "борошн": "flour", "хліб": "bread", "батон": "bread",
    "круасан": "croissant", "торт": "cake", "тістечк": "cake", "печив": "cookie",
    "цукерк": "candy", "шоколад": "chocolate", "морозив": "ice cream",
    "сир": "cheese", "молок": "milk", "кефір": "kefir", "йогурт": "yogurt",
    "сметан": "sour cream", "масл": "butter", "яйц": "egg", "ковбас": "sausage",
    "шинк": "ham", "бекон": "bacon", "сіль": "salt", "цукор": "sugar", "мед": "honey",
    "джем": "jam", "варення": "jam", "кетчуп": "ketchup", "майонез": "mayonnaise",
    "гірчиц": "mustard", "соус": "sauce", "суп": "soup", "борщ": "borscht",
    "каш": "porridge", "котлет": "cutlet", "шашлик": "kebab", "піц": "pizza",
    "бургер": "burger", "чіпс": "chips", "попкорн": "popcorn", "сочевиц": "lentil",
    "нут": "chickpea", "квасол": "bean", "горох": "peas", "кукурудз": "corn",
    "авокадо": "avocado", "оливк": "olives", "фарш": "minced meat", "стейк": "steak",
    "філе": "fillet", "хіноа": "quinoa", "кускус": "couscous", "сирник": "pancake",
    "млинц": "pancake", "вареник": "dumpling", "голубц": "cabbage rolls",
    "паштет": "pate", "сирков": "cheese", "сирн": "cheese",
}
PARTS = {
    "грудк": "breast", "стегн": "thigh", "ніжк": "drumstick", "філе": "fillet",
    "ребер": "ribs", "лопатк": "shoulder", "сідниц": "rump", "вирізк": "tenderloin",
    "язик": "tongue",
}
COOKED_MAP = {
    "варен": ("boiled", "cooked"), "відвар": ("boiled", "cooked"),
    "смаж": ("fried", "cooked"), "тушков": ("stewed", "cooked"),
    "пече": ("roasted", "cooked"), "печен": ("roasted", "cooked"),
    "копч": ("smoked", "cooked"), "суш": ("dried", "cooked"),
    "марин": ("pickled", "cooked"), "гриль": ("grilled", "cooked"),
    "паров": ("steamed", "cooked"), "консерв": ("canned", "cooked"),
    "олів": ("mixed salad", None),
}
EN_NOUNS = set(
    """chicken turkey beef pork lamb veal rabbit fish salmon mackerel herring tuna
    shrimp peanut walnut almond hazelnut potato tomato cucumber carrot beet cabbage
    onion garlic pepper zucchini eggplant broccoli spinach lettuce mushroom apple
    pear orange tangerine lemon banana grape strawberry raspberry blueberry cherry
    plum peach apricot watermelon melon persimmon pineapple kiwi pomegranate rice
    buckwheat oats millet barley pasta noodle bread croissant cake cookie biscuit
    candy chocolate ice cream cheese milk yogurt butter egg sausage ham bacon salt
    sugar honey jam ketchup mayonnaise mustard sauce soup borscht porridge meat
    steak cutlet kebab pizza burger chips popcorn lentil chickpea bean pea corn
    avocado olive tofu tempeh lentils noodles dumpling cabbage""".split()
)
EN_COOKED = (
    "boiled", "stewed", "cooked", "fried", "roasted", "braised", "grilled",
    "steamed", "canned", "baked", "smoked", "dried", "minced",
)
COOKED_FILE = re.compile(
    r"варен|відвар|смаж|тушков|пече|копче|суш|маринован|"
    r"\bboil|\bstew|\broast|\bfri|\bfry|\bcook|\bbrais|\bgrill|\bbake|"
    r"\bcasserol|\bkebab|shashlyk|\bcurry|\bsteamed|\bsimmer|\bpoach|\bminced|\bmashed",
    re.I,
)
CYR = re.compile(r"[а-яіїєґ]", re.I)


def unfixable(name: str) -> bool:
    return name.startswith(("Babyfood", "Baby Toddler"))


def analyze(name: str):
    """(назва англ., варіанти слова приготування, частина туші) - або (None, ...)."""
    low = name.lower()
    noun = None
    noun2 = None
    cooked = None
    part = None
    if CYR.search(name):
        hits = sorted((low.find(k), -len(k), k) for k in UK_EN if k in low)
        if hits:
            noun = UK_EN[hits[0][2]]
        for _, _, k in hits:
            if len(k) >= 4 and UK_EN[k] != noun:
                noun2 = UK_EN[k]
                break
        for key in sorted(COOKED_MAP, key=len, reverse=True):
            if key in low:
                cooked = COOKED_MAP[key]
                break
        for key in sorted(PARTS, key=len, reverse=True):
            if key in low:
                part = PARTS[key]
                break
    else:
        words = set(re.findall(r"[a-z]+", low))
        for w in EN_NOUNS:
            if w in words:
                noun = w
                break
        for w in EN_COOKED:
            if w in words:
                cooked = (w, None)
                break
    return noun, cooked, part, noun2


def queries(noun: str, cooked, part: str | None, noun2: str | None = None):
    """(запити з половиною туші, запити без неї) — перші пріоритетніші."""
    with_part, no_part = [], []
    if cooked and cooked[0]:
        alts = [c for c in (cooked[0], cooked[1]) if c]
        for c in alts:
            if part and part != noun:
                with_part.append(f"{c} {noun} {part}")
            no_part.append(f"{c} {noun}")
    else:
        if noun2:
            no_part.append(f"{noun2} {noun}")
        no_part.append(noun if noun.endswith("s") else noun + "s")
        no_part.append(noun)
        if part:
            with_part.append(f"{noun} {part}")
    dedup = lambda xs: list(dict.fromkeys(xs))
    return dedup(with_part), dedup(no_part)


COOK_ROOT = {
    "boiled": "boil", "fried": "fri|fry", "stewed": "stew", "roasted": "roast",
    "smoked": "smok", "dried": "dri", "pickled": "pickl", "grilled": "grill",
    "steamed": "stea", "cooked": "cook", "canned": "can",
}


def pick_shelf(cands: list[str], name: str, noun: str | None, prepared: bool,
               part: str | None = None, root: str | None = None) -> str:
    """root (якщо задано) — обовʼязковий корінь способу приготування у назві файлу."""
    noun_re = re.compile(r"\b" + re.escape(noun) + r"s?\b", re.I) if noun else None
    part_re = re.compile(r"\b" + re.escape(part) + r"s?\b", re.I) if part else None
    root_re = re.compile(r"\b(?:" + root + ")", re.I) if root else None
    kept = []
    for url in cands:
        title = file_name_from_url(url)
        if not title or not POSITIVE.search(title):
            continue
        if JUNK_FILE.search(title) or BAD_FILE.search(title):
            continue
        if noun_re and not noun_re.search(title):
            continue
        if part_re and not part_re.search(title):
            continue
        if root_re and not root_re.search(title):
            continue
        if prepared and not COOKED_FILE.search(title):
            continue
        kept.append((score(url, name), url))
    best_score = max((s for s, _ in kept), default=-99)
    best = next((u for s, u in kept if s == best_score), "")
    need = 3 if prepared else 0
    return best if best_score >= need else NO_IMAGE


def mealdb(noun: str, cooked) -> str:
    """TheMealDB: реальне фото страви з назвою продукту."""
    url = ("https://www.themealdb.com/api/json/v1/1/search.php?s="
           + urllib.parse.quote(noun))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as err:
        print(f"    MealDB недоступний: {err}")
        return NO_IMAGE
    meals = data.get("meals") or []
    cooked_re = re.compile(r"boil|stew|roast|fri|cook|bake|grill|curry|brais|simmer", re.I)
    noun_re = re.compile(r"\b" + re.escape(noun) + r"s?\b", re.I)
    want = cooked[0] if cooked and cooked[0] else None
    best = None
    for m in meals:
        t = m.get("strMeal") or ""
        ok_noun = bool(noun_re.search(t))
        ok_cooked = bool(cooked_re.search(t))
        if want and ok_noun and ok_cooked:
            best = m
            break
        if best is None and ok_noun and ok_cooked:
            best = m
        if best is None and ok_noun:
            best = m
    if best is None and meals:
        best = meals[0]
    thumb = (best or {}).get("strMealThumb") or ""
    return thumb if thumb.startswith("http") else NO_IMAGE


def patch(row: dict, url: str, dry: bool) -> None:
    if dry:
        return
    try:
        _supabase(
            "PATCH", f"products?id=eq.{row['id']}&user_id=is.null",
            body={"image_url": url}, headers={"Prefer": "return=minimal"},
        )
    except urllib.error.HTTPError as err:
        print(f"  Помилка запису «{row['name']}»: {err}")


def needs_fix(row: dict) -> bool:
    url = row.get("image_url") or ""
    if not url.startswith("http"):
        return True
    title = file_name_from_url(url)
    if BAD_FILE.search(title) or JUNK_FILE.search(title):
        return True
    name = row["name"]
    if PREPARED.search(name) and not COOKED_FILE.search(title):
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Фото страв: Commons(en) -> MealDB -> літера")
    ap.add_argument("--dry-run", action="store_true", help="не писати в БД")
    ap.add_argument("--limit", type=int, default=100000)
    args = ap.parse_args()

    rows = rows_to_fix()
    print(f"Рядків на опрацювання: {len(rows)}")

    work = []
    instant = 0
    for row in rows:
        name = row["name"]
        if name in FORCE_BLANK or name in LEAVE_AS_IS:
            continue
        if unfixable(name):
            if (row.get("image_url") or "") != "-":
                patch(row, "-", args.dry_run)
                instant += 1
            continue
        if not needs_fix(row):
            continue
        work.append(row)
    print(f"Одразу в літеру (без мережі): {instant}; до опрацювання мережею: {len(work)}")
    if len(work) > args.limit:
        work = work[: args.limit]

    filled, blanked = [], 0
    for i, row in enumerate(work, 1):
        name = row["name"]
        noun, cooked, part, noun2 = analyze(name)
        prepared = bool(PREPARED.search(name))
        new_url = NO_IMAGE
        # 1) Commons з англійським запитом (спершу з половиною туші)
        if noun:
            part_qs, noun_qs = queries(noun, cooked, part, noun2)
            steps = []
            if cooked and cooked[0]:
                root = COOK_ROOT.get(cooked[0])
                if part:
                    steps.append((part_qs, True, root))
                if part:
                    steps.append((part_qs, True, None))
                steps.append((noun_qs, False, root))
                steps.append((noun_qs, False, None))
            else:
                if part:
                    steps.append((part_qs, True, None))
                steps.append((noun_qs, False, None))
            for qs, use_part, root in steps:
                if new_url != NO_IMAGE:
                    break
                for q in qs:
                    try:
                        cands = commons_search(q)
                    except (urllib.error.HTTPError, urllib.error.URLError,
                            ValueError, OSError) as err:
                        print(f"  «{name}»: Commons недоступний ({err}) — далі MealDB")
                        break
                    time.sleep(1.3)
                    new_url = pick_shelf(cands, name, noun, prepared,
                                         part if use_part else None, root)
                    if new_url != NO_IMAGE:
                        break
        # 2) MealDB
        if new_url == NO_IMAGE and noun and prepared:
            new_url = mealdb(noun, cooked)
            time.sleep(0.5)
        # 3) без перекладу (кирилиця без словника) - запит як є
        if new_url == NO_IMAGE and not noun and CYR.search(name):
            try:
                cands = commons_search(name)
                time.sleep(1.3)
                noun_local = None
                new_url = pick_shelf(cands, name, noun_local, prepared)
            except (urllib.error.HTTPError, urllib.error.URLError,
                    ValueError, OSError) as err:
                print(f"  «{name}»: Commons недоступний ({err})")

        old = row.get("image_url") or ""
        if new_url == old:
            continue
        if new_url == NO_IMAGE:
            blanked += 1
        else:
            filled.append((name, new_url))
        patch(row, new_url, args.dry_run)
        if i % 10 == 0:
            print(f"  опрацьовано {i}/{len(work)} (заповнено {len(filled)}, літер {blanked})")

    print(f"\n{'Було б ' if args.dry_run else ''}заповнено: {len(filled)}, "
          f"залишено літер: {blanked}")
    for name, url in filled[:25]:
        print(f"  · {name} -> {file_name_from_url(url)[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
