from typing import Optional

from supabase import Client, create_client

from bot.config import SUPABASE_KEY, SUPABASE_URL

_client: Optional[Client] = None
_init_failed = False


def get_client() -> Optional[Client]:
    global _client, _init_failed
    if _client is not None:
        return _client
    if _init_failed or not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        _init_failed = True
        return None
    return _client


def save_profile(user_id: int, username: Optional[str], profile: dict) -> bool:
    client = get_client()
    if client is None:
        return False
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
    try:
        client.table("profiles").upsert(row, on_conflict="user_id").execute()
        return True
    except Exception:
        return False


def get_profile(user_id: int) -> Optional[dict]:
    client = get_client()
    if client is None:
        return None
    try:
        res = client.table("profiles").select("*").eq("user_id", user_id).limit(1).execute()
    except Exception:
        return None
    return res.data[0] if res.data else None
