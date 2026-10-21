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
import urllib.request
import uuid
from typing import Optional, Tuple

from bot.config import (
    BOT_TOKEN,
    SUPABASE_JWT_KID,
    SUPABASE_JWT_SECRET,
    SUPABASE_PROJECT_REF,
    SUPABASE_URL,
)

INIT_DATA_MAX_AGE = 24 * 60 * 60
JWT_TTL = 7 * 24 * 60 * 60
JWT_ISSUER = "supabase"
TELEGRAM_UUID_NAMESPACE = uuid.NAMESPACE_URL

_kid_cache: Optional[str] = None


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


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


def webhook_secret_token(bot_token: str = BOT_TOKEN) -> str:
    """Секретний токен для Telegram webhook.

    Telegram вимагає, щоб значення secret_token збігалося на обох кінцях
    (при setWebhook і в заголовку X-Telegram-Bot-Api-Secret-Token).
    Щоб налаштування на Vercel і локально не могли розійтися, токен
    детерміновано виводиться з BOT_TOKEN.
    """
    if not bot_token:
        return ""
    digest = hmac.new(
        b"calories-webhook-secret", bot_token.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return digest[:32]


def jwks_kid() -> str:
    """Key ID активного ключа підпису Supabase (для заголовка JWT)."""
    global _kid_cache
    if _kid_cache is not None:
        return _kid_cache
    if SUPABASE_JWT_KID:
        _kid_cache = SUPABASE_JWT_KID
        return _kid_cache
    _kid_cache = ""
    if SUPABASE_URL:
        try:
            req = urllib.request.Request(
                f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            keys = data.get("keys") or []
            if keys:
                _kid_cache = keys[0].get("kid") or ""
        except Exception:
            _kid_cache = ""
    return _kid_cache


def _load_private_key(material: str):
    """Завантажує приватний EC-ключ із PEM/base64/JSON."""
    from cryptography.hazmat.primitives import serialization

    text = (material or "").strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            data = {}
        for key in ("private_key", "privateKey", "secret", "secret_key", "key"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break

    if "-----BEGIN" in text:
        return serialization.load_pem_private_key(text.encode("utf-8"), password=None)

    try:
        raw = base64.b64decode(text, validate=True)
    except Exception:
        raise RuntimeError("SUPABASE_JWT_SECRET не є приватним ключем")

    if raw.startswith(b"-----BEGIN"):
        return serialization.load_pem_private_key(raw, password=None)
    return serialization.load_der_private_key(raw, password=None)


def _load_key(material: str) -> Tuple[str, object]:
    """Визначає алгоритм: ES256 (приватний ключ) або HS256 (legacy-секрет)."""
    text = (material or "").strip()
    if not text:
        raise RuntimeError("SUPABASE_JWT_SECRET не налаштований")

    looks_like_key = "-----BEGIN" in text or text.startswith("{")
    if looks_like_key:
        return "ES256", _load_private_key(text)

    try:
        raw = base64.b64decode(text, validate=True)
    except Exception:
        raw = b""
    if raw:
        try:
            return "ES256", _load_private_key(text)
        except Exception:
            pass
    return "HS256", text


def _sign_es256(key, data: bytes) -> bytes:
    """Підпис ECDSA P-256 у форматі JOSE (r||s)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    der_signature = key.sign(data, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def make_jwt(
    telegram_id: int,
    secret: str = SUPABASE_JWT_SECRET,
    ttl: int = JWT_TTL,
) -> str:
    """Підписує JWT для Supabase від імені telegram-користувача.

    secret: приватний EC-ключ (PEM/base64) -> ES256, або legacy-секрет -> HS256.
    """
    alg, key = _load_key(secret)

    now = int(time.time())
    header = {"alg": alg, "typ": "JWT"}
    if alg == "ES256":
        kid = jwks_kid()
        if kid:
            header["kid"] = kid
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
    if alg == "ES256":
        signature = _sign_es256(key, signing_input)
    else:
        signature = hmac.new(
            key.encode("utf-8"), signing_input, hashlib.sha256
        ).digest()
    segments.append(_b64url(signature))
    return ".".join(segments)


def decode_jwt(token: str) -> dict:
    """Декодує payload JWT (без перевірки підпису) — для тестів і логів."""
    parts = (token or "").split(".")
    if len(parts) < 2:
        raise ValueError("некоректний JWT")
    return json.loads(_b64url_decode(parts[1]).decode("utf-8"))


def decode_jwt_header(token: str) -> dict:
    """Декодує заголовок JWT (alg, kid)."""
    parts = (token or "").split(".")
    if len(parts) < 2:
        raise ValueError("некоректний JWT")
    return json.loads(_b64url_decode(parts[0]).decode("utf-8"))
