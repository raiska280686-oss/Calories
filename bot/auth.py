"""Авторизація: перевірка Telegram initData та підпис Supabase JWT.

Схема:
1. Mini App передає на сервер `initData` (підписаний Telegram).
2. Сервер перевіряє HMAC-SHA256 (secret key = HMAC_SHA256("WebAppData", BOT_TOKEN)).
3. Сервер випускає власний JWT (HS256, secret = SUPABASE_JWT_SECRET) з claim
   `telegram_id` та детермінованим `sub` (uuid5). Supabase PostgREST приймає
   такий токен як `Authorization: Bearer <jwt>` і віддає запити від імені
   користувача (role=authenticated), тому RLS-політики можуть фільтрувати дані
   за `public.tg_uid()`.
"""

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import uuid
from typing import Optional

from bot.config import BOT_TOKEN, SUPABASE_JWT_SECRET, SUPABASE_PROJECT_REF

INIT_DATA_MAX_AGE = 24 * 60 * 60
JWT_TTL = 7 * 24 * 60 * 60
JWT_ISSUER = "supabase"
TELEGRAM_UUID_NAMESPACE = uuid.NAMESPACE_URL


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def parse_init_data(init_data: str) -> dict:
    pairs = urllib.parse.parse_qsl(init_data or "", keep_blank_values=True)
    return {key: value for key, value in pairs}


def verify_init_data(init_data: str, bot_token: str = BOT_TOKEN) -> Optional[dict]:
    """Перевіряє підпис Telegram initData. Повертає дані користувача або None."""
    if not init_data or not bot_token:
        return None
    try:
        params = parse_init_data(init_data)
    except Exception:
        return None

    received_hash = params.pop("hash", "")
    if not received_hash:
        return None

    check_string = "\n".join(f"{key}={params[key]}" for key in sorted(params))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key, check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    try:
        auth_date = int(params.get("auth_date", "0") or "0")
    except ValueError:
        auth_date = 0
    if auth_date and (time.time() - auth_date) > INIT_DATA_MAX_AGE:
        return None

    raw_user = params.get("user")
    if not raw_user:
        return None
    try:
        user = json.loads(raw_user)
    except ValueError:
        return None
    if not isinstance(user, dict) or not user.get("id"):
        return None

    return {
        "user": user,
        "user_id": int(user["id"]),
        "auth_date": auth_date,
        "params": params,
    }


def telegram_uuid(telegram_id: int) -> str:
    """Детермінований UUID для telegram id (потрібен для claim `sub`)."""
    return str(uuid.uuid5(TELEGRAM_UUID_NAMESPACE, f"telegram:{int(telegram_id)}"))


def make_jwt(
    telegram_id: int,
    secret: str = SUPABASE_JWT_SECRET,
    ttl: int = JWT_TTL,
) -> str:
    """Підписує JWT (HS256) для Supabase від імені telegram-користувача."""
    if not secret:
        raise RuntimeError("SUPABASE_JWT_SECRET не налаштований")

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": JWT_ISSUER,
        "ref": SUPABASE_PROJECT_REF,
        "role": "authenticated",
        "aud": "authenticated",
        "sub": telegram_uuid(telegram_id),
        "session_id": str(uuid.uuid4()),
        "telegram_id": int(telegram_id),
        "iat": now,
        "exp": now + int(ttl),
    }
    segments = [
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    segments.append(_b64url(signature))
    return ".".join(segments)


def decode_jwt(token: str) -> dict:
    """Декодує payload JWT (без перевірки підпису) — для тестів і логів."""
    parts = (token or "").split(".")
    if len(parts) < 2:
        raise ValueError("некоректний JWT")
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
