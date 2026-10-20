import json
import urllib.parse
import urllib.request
from typing import Optional

from bot.config import SUPABASE_KEY, SUPABASE_URL


def _request(method: str, path: str, body: Optional[dict] = None, prefer: str = "") -> Optional[list]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
    except Exception:
        return None
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) else [parsed]


def save_profile(user_id: int, username: Optional[str], profile: dict) -> bool:
    row = {
        "user_id": user_id,
        "username": username,
        "sex": profile["sex"],
        "age": profile["age"],
        "height": profile["height"],
        "weight": profile["weight"],
        "activity": profile["activity"],
        "bmr": profile["bmr"],
        "tdee": profile["tdee"],
    }
    result = _request(
        "POST",
        "profiles?on_conflict=user_id",
        body=row,
        prefer="resolution=merge-duplicates,return=representation",
    )
    return result is not None


def get_profile(user_id: int) -> Optional[dict]:
    rows = _request("GET", f"profiles?user_id=eq.{user_id}&select=*&limit=1")
    return rows[0] if rows else None
