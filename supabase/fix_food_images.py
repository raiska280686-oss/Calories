"""Виправляє картинки продуктів, які показують рослину/кущ замість їжі.

Як визначаємо некоректність:
  1) опис статті Вікіпедії (перші речення) містить ознаки рослини/птахів:
     «вид рослин», «рослина роду», «кущ», «рід птахів»… (uk) / species of plant, shrub… (en);
  2) назва файлу-картинки містить flower/leaf/tree/illustration/квіт/листя/грядка…

Що робимо з некоректними:
  - пул кандидатів: пошук Wikimedia Commons за повною назвою + картинки з тієї ж
    статті (напр. «Гречана каша» у статті «Гречка»);
  - оцінка: плюс за слова їжі/збіг із назвою, мінус за слова рослини/бруку;
  - якщо доброго кандидата немає — ставимо «-» (у міні-аппі буде літерна аватарка).

Використання:
    python3 supabase/fix_food_images.py --dry-run
    python3 supabase/fix_food_images.py
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL  # noqa: E402
from backfill_wiki import API, NO_IMAGE, UA, _get_json, candidates, wiki_images  # noqa: E402
from import_off import _supabase  # noqa: E402

BAD_UK = re.compile(
    r"вид рослин|вид квіткових|рослин[аи] род|рід рослин|рослина|кущ|трав'янист|"
    r"рід птахів|вид птахів|рід тварин|горобцеподібн|птах|свійськ|курин|птиц",
    re.I,
)
BAD_EN = re.compile(
    r"\bspecies of (plant|bird|flowering|trees)\b|\bflowering plant\b|\bgenus\b|"
    r"\bcultivar\b|\bshrub\b|\bplant\b|\bbird\b|\btree\b|\bherb\b|\baquatic plant\b|"
    r"\bfowls?\b|\bpoultry\b|\bdomestic fowl\b",
    re.I,
)
BAD_FILE = re.compile(
    r"flower|blossom|in bloom|inflorescence|blüte|herbarium|köhler|medizinal|"
    r"illustration|woodcut|drawing|icon|\bleaf\b|leaves|\btree\b|\bbush\b|\bshrub\b|"
    r"\bfield\b|\bgarden\b|\bgrowing\b|plantation|flowerpot|in pot|"
    r"\bplant\b|\bplants\b|\bcultivar\b|\bspecies\b|\bgenus\b|"
    r"квіт|суцвіт|листя|дерев|кущ|грядк|рослин|плакат|герб|ілюстра|малюн|символ|"
    r"pdf|djvu|svg|frog|skeleton|diagram|logo|map\b",
    re.I,
)
JUNK_FILE = re.compile(
    r"pdf|djvu|svg|webm|ogv|logo|commons-logo|wiki|"
    r"dialectstat|statistic|histogram|\bdiagram\b|\bchart\b|\bgraph\b|"
    r"palace|castle|cathedral|church|monument|statue|museum|temple|"
    r"\broute\b|\bhighway\b|\bstreet\b|\broad\b|\bbuilding\b|facade|interior|aerial|panorama|"
    r"brew|\bpub\b|\bcafe\b|\brestaurant\b|plaque|\bsign\b|streetview|coordinate|"
    r"chicks?\b|\bhens?\b|\brooster\b|\bflock\b|\bcoop\b|free.?range|farmyard|"
    r"neocaridina|caridina|aquarium|aquascap|"
    r"\bDJ\b|by glenn francis|\bportrait\b|\bmural\b|poster|"

    r"gallopavo|meleagris|\bgallus\b|hypoga|bos taurus|sus scrofa|"
    r"histolog|physiolog|\banatom|\bembryo\b|inspection|abattoir|slaughter|carcass|"
    r"newborn|nimitz|\bsailor\b|\bnavy\b|aircraft|\bvine\b|\borchard\b|"
    r"cookbook|kokebok|kochbuch|housekeeper|almanac|\bin turkey\b|\bof turkey\b|"
    r"квочк|курочк|куриц[яі]|індик\b",
    re.I,
)

POSITIVE = re.compile(
    r"каш|відвар|варен|смаж|тушков|пече|пюре|страв|блюдо|свіж|суш|ядер|борщ|хліб|"
    r"молоч|м'яс|мяс|йогурт|сметан|квасол|гречк|картопл|помідор|томат|цибул|моркв|"
    r"капуст|буряк|овоч|фрукт|ягод|плод|рис\b|кукурудз|"
    r"\bporridge\b|\bboiled\b|\bfried\b|\bcooked\b|\bmashed\b|\broast|\bstew\b|"
    r"\bbread\b|\bcake\b|\bdish\b|\bmeal\b|\bserving\b|\bplate\b|\bfresh\b|\bdried\b|"
    r"\bfruit\b|\bvegetable\b|\bberry\b|\bmeat\b|\bfillet\b|\bsteak\b|cross section|"
    r"currant|johannisbeer|ribes|\bberr|"""
    r"\bhalved\b|\bsliced\b|\bpotato|\brice\b|\bcorn\b|\bmaize\b|\bbean\b|\bonion\b|"
    r"\bapple\b|\borange\b|\btomato\b|\bcheese\b|\bmilk\b|\bbutter\b|\byogurt\b|"
    r"\byoghurt\b|\bchicken\b|\bbeef\b|\bpork\b|\bcarrot\b|\bcabbage\b|\bnoodle\b|"
    r"\bpasta\b|\bsoup\b|\bsalad\b|\bjam\b|\bhoney\b|\blemon\b|\bgrape\b|\bpeach\b|"
    r"\bpear\b|\bcherry\b|\bstrawberr|\bblueberr|\bcucumber\b|\bpepper\b|aubergine|"
    r"eggplant|\bgarlic\b|\bpumpkin\b|\bmushroom\b|\bolive\b|\bnut\b|\bseed\b|"
    r"\basparagus\b|\bpeas?\b|\bbroccoli\b|\bcucumber\b|\bbeet\b|radish|turnip|"
    r"zucchini|courgette|sweet.?potato|\bfish\b|\bsalmon\b|\btuna\b|shrimp|prawn|"
    r"peanut|\bmozzarella\b|\bspinach\b|\bwings?\b|\bdip\b|\bfries\b|\bappetizer\b|"
    r"ketchup|mustard|mayonnaise|\bsauce\b|\bdessert\b|bacon|sausage|\bham\b|salami|"
    r"cracker|granola|\bcereal\b|muesli|oatmeal|pancake|waffle|omelette|omelet|"
    r"custard|pudding|mousse|burrito|dumpling|ravioli|gnocchi|croissant|baguette|"
    r"\bturkey\b|\blamb\b|\bveal\b|buckwheat|\blentil\b|chickpea|"
    r"варен|смаж",
    re.I,
)
PREPARED = re.compile(
    r"варен|відвар|смаж|тушков|печен|пюре|каша|на воді|пастеризован|ультрапастеризован|"
    r"\bboiled\b|\bfried\b|\bcooked\b|\bmashed\b|\broasted\b|\bstewed\b",
    re.I,
)
WORD = re.compile(r"[a-zа-яіїєґ0-9]{4,}", re.I)
FORCE_BLANK = {
    "Amaranth leaves, raw",
    "Amaranth leaves, cooked, boiled, drained, without salt",
    "Amaranth leaves, cooked, boiled, drained, with salt",
    "APPLEBEE'S, chili",
    "Asparagus, raw",
    "Asparagus, green, raw",
    "Королівський",
    "APPLEBEE'S, coleslaw",
}
# фото з їжею, яке формально підпадає під JUNK (шлях у назві файлу) — лишаємо як є
LEAVE_AS_IS = {"APPLEBEE'S, mozzarella sticks"}
DISH_ONLY = re.compile(
    r"sandwich|burger|pizza|hot.?dog|taco|sushi|bagel|donut|doughnut|"
    r"\bcookie\b|\bbiscuit\b|\bcupcake\b|muffin",
    re.I,
)


def rows_to_fix() -> list[dict]:
    """Глобальні продукти з картинками Вікіпедії + рядки з маркером «-» (спробувати заповнити)."""
    rows, off = [], 0
    while True:
        page = _supabase(
            "GET",
            f"products?user_id=is.null&select=id,name,image_url&limit=1000&offset={off}",
        ) or []
        rows += page
        if len(page) < 1000:
            break
        off += 1000
    return [
        r for r in rows
        if (r["image_url"] or "").startswith("http")
        and ("wikimedia.org" in r["image_url"] or "wikipedia.org" in r["image_url"])
        or (r.get("image_url") or "") == "-"
    ]


def file_name_from_url(url: str) -> str:
    parts = [p for p in url.split("/") if p]
    if not parts:
        return ""
    name = parts[-1]
    if re.match(r"^\d+px-", name) and len(parts) >= 2:
        name = parts[-2]
    try:
        name = urllib.parse.unquote(name)
    except Exception:
        pass
    return name.replace("_", " ")


def match_articles(rows: list[dict]) -> dict[int, tuple[str, str]]:
    """{id: (назва_статті, картинка)} — як у backfill_wiki, але з назвою статті."""
    by_lang: dict[str, list[tuple[dict, list[str]]]] = {"uk": [], "en": []}
    for row in rows:
        lang = "uk" if re.search(r"[а-яіїєґ]", row["name"], re.I) else "en"
        by_lang[lang].append((row, candidates(row["name"])))

    result: dict[int, tuple[str, str]] = {}
    for lang in ("uk", "en"):
        pairs = by_lang[lang]
        if not pairs:
            continue
        titles: list[str] = []
        for _, cands in pairs:
            for title in cands:
                if title not in titles:
                    titles.append(title)
        print(f"  {lang}: {len(pairs)} продуктів, {len(titles)} назв статей")
        images = wiki_images(titles, lang)
        for row, cands in pairs:
            for title in cands:
                if images.get(title):
                    result[row["id"]] = (title, images[title])
                    break
    return result


def _json(url: str, attempts: int = 3) -> dict:
    """_get_json + ретрай на обриві зʼязку (OSError, який _get_json не ловить)."""
    for attempt in range(1, attempts + 1):
        try:
            return _get_json(url)
        except OSError as err:
            if attempt == attempts:
                raise
            print(f"    обрив зʼязку ({err}); повтор {attempt}/{attempts}")
            time.sleep(10 * attempt)
    return {}


def fetch_extracts(items: dict[int, str], lang: str) -> dict[str, str]:
    """{назва_статті: перші речення} партіями по 20 (exlimit=20)."""
    titles = list(dict.fromkeys(items.values()))
    out: dict[str, str] = {}
    for start in range(0, len(titles), 20):
        params = {
            "action": "query", "prop": "extracts", "exintro": "1", "explaintext": "1",
            "exsentences": "2", "exlimit": "20", "redirects": "1",
            "titles": "|".join(titles[start:start + 20]),
            "format": "json", "formatversion": "2",
        }
        data = _json(f"{API.format(lang=lang)}?{urllib.parse.urlencode(params)}")
        for page in (data.get("query") or {}).get("pages") or []:
            if page.get("missing"):
                continue
            out[page.get("title") or ""] = (page.get("extract") or "").replace("\n", " ")
        time.sleep(0.35)
    return out


def article_images(title: str, lang: str) -> list[str]:
    """Список файлів, які використовуються у статті (крім бруку)."""
    params = {
        "action": "query", "prop": "images", "imlimit": "100", "redirects": "1",
        "titles": title, "format": "json", "formatversion": "2",
    }
    data = _json(f"{API.format(lang=lang)}?{urllib.parse.urlencode(params)}")
    pages = (data.get("query") or {}).get("pages") or []
    if not pages or pages[0].get("missing"):
        return []
    names = [i.get("title") or "" for i in pages[0].get("images") or []]
    return [n for n in names if not JUNK_FILE.search(urllib.parse.unquote(n))]


def _bare(title: str) -> str:
    return title.split(":", 1)[1] if ":" in title else title


def file_thumbs(files: list[str]) -> dict[str, str]:
    """{Файл:X: URL 330px} партіями по 50 (Commons приймає лише «File:»)."""
    out: dict[str, str] = {}
    wanted: dict[str, str] = {}
    for title in files:
        wanted.setdefault(_bare(title).lower(), title)
    keys = list(wanted)
    for start in range(0, len(keys), 50):
        chunk = keys[start:start + 50]
        params = {
            "action": "query", "prop": "imageinfo", "iiprop": "url|mime",
            "iiurlwidth": "330", "titles": "|".join("File:" + k for k in chunk),
            "format": "json", "formatversion": "2",
        }
        data = _json(f"https://commons.wikimedia.org/w/api.php?{urllib.parse.urlencode(params)}")
        for page in (data.get("query") or {}).get("pages") or []:
            if page.get("missing"):
                continue
            info = (page.get("imageinfo") or [{}])[0]
            mime = info.get("mime") or ""
            thumb = (info.get("thumburl") or info.get("url") or "").split("?")[0]
            title = page.get("title") or ""
            if not thumb.startswith("http") or not mime.startswith("image/"):
                continue
            if JUNK_FILE.search(title):
                continue
            out[wanted.get(_bare(title).lower(), title)] = thumb[:500]
        time.sleep(0.35)
    return out


def commons_search(name: str) -> list[str]:
    """URL-и картинок із Commons за повною назвою продукту."""
    params = {
        "action": "query", "generator": "search", "gsrsearch": name,
        "gsrnamespace": "6", "gsrlimit": "8", "prop": "imageinfo",
        "iiprop": "url|mime", "iiurlwidth": "330", "format": "json", "formatversion": "2",
    }
    data = _json(f"https://commons.wikimedia.org/w/api.php?{urllib.parse.urlencode(params)}")
    out = []
    for page in (data.get("query") or {}).get("pages") or []:
        title = page.get("title") or ""
        info = (page.get("imageinfo") or [{}])[0]
        mime = info.get("mime") or ""
        thumb = (info.get("thumburl") or "").split("?")[0]
        if not thumb.startswith("http"):
            continue
        if not mime.startswith("image/"):
            continue
        if JUNK_FILE.search(title) or BAD_FILE.search(title):
            continue
        out.append(thumb[:500])
    return out


def score(url: str, name: str) -> int:
    title = file_name_from_url(url)
    if not title or JUNK_FILE.search(title):
        return -99
    value = 0
    if POSITIVE.search(title):
        value += 3
    if BAD_FILE.search(title):
        value -= 4
    if DISH_ONLY.search(title) and not DISH_ONLY.search(name):
        value -= 3
    name_tokens = set(t.lower() for t in WORD.findall(name))
    file_tokens = set(t.lower() for t in WORD.findall(title))
    value += min(2, len(name_tokens & file_tokens))
    return value


def pick(cands: list[str], name: str, min_score: int = 0) -> str:
    best_url, best_score = "", -99
    for url in cands:
        if not POSITIVE.search(file_name_from_url(url)):
            continue
        s = score(url, name)
        if s > best_score:
            best_url, best_score = url, s
    prepared = bool(PREPARED.search(name))
    need = max(3 if prepared else 0, min_score)
    return best_url if best_score >= need else NO_IMAGE


def main() -> int:
    ap = argparse.ArgumentParser(description="Виправлення картинок-рослин на їжу")
    ap.add_argument("--dry-run", action="store_true", help="не писати в БД, лише показати")
    ap.add_argument("--max", type=int, default=100000, help="ліміт некоректних рядків")
    args = ap.parse_args()

    if not SUPABASE_SERVICE_ROLE_KEY:
        print("Немає SUPABASE_SERVICE_ROLE_KEY")
        return 1

    rows = rows_to_fix()
    print(f"Рядків на опрацювання (картинки Вікіпедії + рядки «-»): {len(rows)}")
    try:
        matched = match_articles(rows)
    except OSError as err:
        print(f"Обрив зʼязку на підборі статей ({err}) — повтор через 15 с")
        time.sleep(15)
        matched = match_articles(rows)
    print(f"Статей підібрано: {len(matched)}")

    extracts: dict[str, str] = {}
    lang_of = {r["id"]: ("uk" if re.search(r"[а-яіїєґ]", r["name"], re.I) else "en") for r in rows}
    for lang in ("uk", "en"):
        items = {rid: t for rid, (t, _) in matched.items() if lang_of.get(rid) == lang}
        if items:
            try:
                extracts.update(fetch_extracts(items, lang))
            except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as err:
                print(f"  Описи статей «{lang}» недоступні ({err}) — пропускаю")

    def is_blank(row: dict) -> bool:
        return not (row.get("image_url") or "").startswith("http")

    bad = []
    for row in rows:
        info = matched.get(row["id"])
        if is_blank(row):
            bad.append((row, info[0] if info else ""))
            continue
        if not info:
            continue
        title, _img = info
        text = extracts.get(title, "")
        lang_bad = BAD_UK if lang_of.get(row["id"]) == "uk" else BAD_EN
        if (
            lang_bad.search(text)
            or BAD_FILE.search(file_name_from_url(row["image_url"]))
            or JUNK_FILE.search(file_name_from_url(row["image_url"]))
        ):
            bad.append((row, title))

    print(f"До опрацювання: {len(bad)} (некоректні з картинкою + порожні «-»)")
    bad = [
        (r, t) for r, t in bad
        if r["name"] not in FORCE_BLANK and r["name"] not in LEAVE_AS_IS
    ]
    if len(bad) > args.max:
        bad = bad[: args.max]

    changed, blanked = [], 0
    for i, (row, title) in enumerate(bad, 1):
        name = row["name"]
        lang = lang_of.get(row["id"]) or ("uk" if re.search(r"[а-яіїєґ]", name, re.I) else "en")
        blank = is_blank(row)
        floor = 1 if blank else 0
        old_url = row["image_url"]
        prepared = bool(PREPARED.search(name))
        need = max(3 if prepared else 0, floor)
        if not blank:
            old_fn = file_name_from_url(old_url)
            if POSITIVE.search(old_fn) and score(old_url, name) >= need:
                continue
        try:
            new_url = pick(commons_search(name), name, floor)
            time.sleep(0.4)
            if new_url == NO_IMAGE and title:
                files = article_images(title, lang)
                time.sleep(0.4)
                new_url = pick(list(file_thumbs(files).values()), name, floor)
                time.sleep(0.4)
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, OSError) as err:
            print(f"  · «{name}» — джерело недоступне ({err}), пропускаю")
            continue
        old_url = row["image_url"]
        if new_url == old_url:
            continue
        if new_url == NO_IMAGE:
            blanked += 1
        else:
            changed.append((name, new_url, blank))
        if not args.dry_run:
            try:
                _supabase(
                    "PATCH", f"products?id=eq.{row['id']}&user_id=is.null",
                    body={"image_url": new_url}, headers={"Prefer": "return=minimal"},
                )
            except urllib.error.HTTPError as err:
                print(f"  Помилка запису «{name}»: {err}")
        if i % 25 == 0:
            print(f"  опрацьовано {i}/{len(bad)} (оновлено {len(changed)}, прибрано {blanked})")

    filled = sum(1 for _, _, was in changed if was)
    print(f"\n{'Було б' if args.dry_run else ''} оновлено картинок: {len(changed)} "
          f"(з них заповнено порожніх «-»: {filled}), "
          f"прибрано (літерна аватарка): {blanked}, "
          f"без змін: {len(bad) - len(changed) - blanked}")
    for name, url, _ in changed[:15]:
        print(f"  · {name} → {file_name_from_url(url)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
