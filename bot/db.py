import json
import urllib.error
import urllib.request
from typing import Optional

from bot.auth import make_jwt
from bot.config import SUPABASE_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL

_last_error: Optional[str] = None


def get_last_error() -> Optional[str]:
    """Остання помилка доступу до Supabase (None — все добре)."""
    return _last_error


def _auth_token(user_id: Optional[int]) -> str:
    """JWT користувача (RLS бачить telegram_id), service_role для бота або publishable key."""
    if SUPABASE_SERVICE_ROLE_KEY:
        return SUPABASE_SERVICE_ROLE_KEY
    if user_id is not None:
        try:
            return make_jwt(user_id)
        except RuntimeError:
            pass
    return SUPABASE_KEY


def _request(
    method: str,
    path: str,
    body: Optional[dict] = None,
    prefer: str = "",
    user_id: Optional[int] = None,
) -> Optional[list]:
    global _last_error
    _last_error = None
    if not SUPABASE_URL or not (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY):
        _last_error = "Не налаштовано SUPABASE_URL/SUPABASE_KEY"
        return None
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY,
        "Authorization": f"Bearer {_auth_token(user_id)}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as err:
        detail = ""
        try:
            detail = err.read().decode()[:200]
        except Exception:
            pass
        _last_error = f"HTTP {err.code}: {detail}"
        return None
    except Exception as err:
        _last_error = str(err)[:200]
        return None
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        _last_error = "Некоректна відповідь Supabase"
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
        user_id=user_id,
    )
    return result is not None


def get_profile(user_id: int) -> Optional[dict]:
    rows = _request(
        "GET", f"profiles?user_id=eq.{user_id}&select=*&limit=1", user_id=user_id
    )
    return rows[0] if rows else None


def get_entries(
    user_id: int, date_from: str, date_to: Optional[str] = None
) -> Optional[list]:
    """Записи щоденника в діапазоні дат (YYYY-MM-DD). None — помилка БД."""
    path = (
        f"diary_entries?user_id=eq.{user_id}&entry_date=gte.{date_from}"
        "&select=entry_date,meal,name,grams,calories,protein,fat,carbs"
        "&order=entry_date.asc,created_at.asc"
    )
    if date_to:
        path += f"&entry_date=lte.{date_to}"
    return _request("GET", path, user_id=user_id)
