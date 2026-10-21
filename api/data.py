"""Ендпоїнт /data — єдиний доступ міні-апу до Supabase.

Міні-апп не має ключів: він надсилає Telegram initData + операцію, а сервер
перевіряє підпис initData, виконує запит до Supabase з service_role
(обхід RLS) і повертає результат. Кожна операція має явний whitelist полів,
тож клієнт не може записати чужі дані (user_id береться з initData).
"""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

from bot.auth import verify_app_user_signature, verify_init_data_reason
from bot.config import (
    SUPABASE_KEY,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)

PHOTO_KIND = {"products": "product", "dishes": "dish"}
MEALS = {"breakfast", "lunch", "dinner", "snack"}


def _supabase(method: str, path: str, body=None, prefer: str = ""):
    """Прямий запит до PostgREST з service_role."""
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as err:
        detail = ""
        try:
            detail = err.read().decode()[:300]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {err.code}: {detail}")
    if not raw:
        return None
    return json.loads(raw)


def _storage(method: str, path: str, body=None, headers_extra=None, raw_body=None):
    url = f"{SUPABASE_URL}/storage/v1/{path}"
    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    headers.update(headers_extra or {})
    data = raw_body
    if body is not None:
        headers.setdefault("Content-Type", "application/json")
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as err:
        detail = ""
        try:
            detail = err.read().decode()[:300]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {err.code}: {detail}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Allow", "POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            payload = json.loads(raw or "{}")
        except ValueError:
            self._send(400, {"error": "bad_json"})
            return

        raw_init = str(payload.get("init_data", "") or "")
        verified, reason = verify_init_data_reason(raw_init)
        if verified:
            user_id = verified["user_id"]
        else:
            # Запасний шлях: підписаний ботом user_id із посилання на міні-апп
            # (використовується, коли Telegram не передав initData).
            auth = payload.get("auth") or {}
            try:
                signed_id = int(auth.get("user_id") or 0)
            except (TypeError, ValueError):
                signed_id = 0
            signature = str(auth.get("sig") or "")
            if not signed_id or not verify_app_user_signature(signed_id, signature):
                self._send(
                    401,
                    {
                        "error": "invalid_init_data",
                        "reason": reason,
                        "init_len": len(raw_init),
                        "has_auth": bool(auth),
                        "auth_user_id": signed_id or None,
                        "sig_len": len(signature),
                    },
                )
                return
            user_id = signed_id

        op = payload.get("op", "")
        params = payload.get("params") or {}
        try:
            result = self._dispatch(op, user_id, params)
        except RuntimeError as err:
            self._send(400, {"error": str(err)[:300]})
            return
        except Exception as err:  # noqa: BLE001
            self._send(500, {"error": str(err)[:300]})
            return
        self._send(200, {"ok": True, "user_id": user_id, "data": result})

    # --- операції -------------------------------------------------
    def _dispatch(self, op: str, user_id: int, p: dict):
        handler = getattr(self, f"_op_{op}", None)
        if handler is None:
            raise RuntimeError("unknown_op")
        return handler(user_id, p)

    def _op_profile_get(self, user_id: int, p: dict):
        rows = _supabase(
            "GET", f"profiles?user_id=eq.{user_id}&select=tdee&limit=1"
        )
        return {"tdee": rows[0]["tdee"] if rows else None}

    def _op_day_get(self, user_id: int, p: dict):
        day = str(p.get("date", ""))[:10]
        return _supabase(
            "GET",
            f"diary_entries?user_id=eq.{user_id}&entry_date=eq.{day}"
            "&select=*&order=created_at.asc",
        )

    def _op_entry_add(self, user_id: int, p: dict):
        meal = str(p.get("meal", ""))
        if meal not in MEALS:
            raise RuntimeError("bad_meal")
        grams = _num(p.get("grams"))
        if grams <= 0:
            raise RuntimeError("bad_grams")
        row = {
            "user_id": user_id,
            "entry_date": str(p.get("date", ""))[:10],
            "meal": meal,
            "product_id": p.get("product_id") if p.get("product_id") else None,
            "name": str(p.get("name", ""))[:200],
            "grams": grams,
            "calories": _num(p.get("calories")),
            "protein": _num(p.get("protein")),
            "fat": _num(p.get("fat")),
            "carbs": _num(p.get("carbs")),
        }
        return _supabase("POST", "diary_entries", body=row, prefer="return=representation")

    def _op_entry_delete(self, user_id: int, p: dict):
        entry_id = _int(p.get("id"))
        if not entry_id:
            raise RuntimeError("bad_id")
        _supabase("DELETE", f"diary_entries?id=eq.{entry_id}&user_id=eq.{user_id}")
        return True

    def _op_products_list(self, user_id: int, p: dict):
        q = str(p.get("q", "")).strip()
        base = f"products?or=(user_id.is.null,user_id.eq.{user_id})"
        if q:
            path = f"{base}&name=ilike.*{urllib.parse.quote(q)}*&select=*&limit=60"
        else:
            path = f"{base}&select=*&limit=60&order=name.asc"
        return _supabase("GET", path)

    def _op_product_save(self, user_id: int, p: dict):
        name = str(p.get("name", "")).strip()[:200]
        if not name:
            raise RuntimeError("bad_name")
        body = {
            "user_id": user_id,
            "name": name,
            "calories": _num(p.get("calories")),
            "protein": _num(p.get("protein")),
            "fat": _num(p.get("fat")),
            "carbs": _num(p.get("carbs")),
            "brand": p.get("brand") or None,
        }
        product_id = _int(p.get("id"))
        if product_id:
            rows = _supabase(
                "PATCH",
                f"products?id=eq.{product_id}&user_id=eq.{user_id}",
                body=body,
                prefer="return=representation",
            )
            return rows[0] if rows else {"id": product_id}
        rows = _supabase("POST", "products", body=body, prefer="return=representation")
        return rows[0] if rows else {"id": None}

    def _op_product_by_barcode(self, user_id: int, p: dict):
        code = str(p.get("code", "")).strip()[:60]
        if not code:
            raise RuntimeError("bad_code")
        rows = _supabase(
            "GET",
            f"products?user_id=eq.{user_id}&brand=eq.{urllib.parse.quote(code)}"
            "&select=*&limit=1",
        )
        return rows[0] if rows else None

    def _op_product_delete(self, user_id: int, p: dict):
        product_id = _int(p.get("id"))
        if not product_id:
            raise RuntimeError("bad_id")
        _supabase("DELETE", f"products?id=eq.{product_id}&user_id=eq.{user_id}")
        return True

    def _op_dishes_list(self, user_id: int, p: dict):
        q = str(p.get("q", "")).strip()
        base = f"dishes?or=(user_id.is.null,user_id.eq.{user_id})"
        if q:
            path = f"{base}&name=ilike.*{urllib.parse.quote(q)}*&select=*&limit=60"
        else:
            path = f"{base}&select=*&limit=60&order=created_at.desc"
        return _supabase("GET", path)

    def _op_dish_save(self, user_id: int, p: dict):
        name = str(p.get("name", "")).strip()[:200]
        if not name:
            raise RuntimeError("bad_name")
        items = p.get("items") or []
        if not items:
            raise RuntimeError("no_items")
        body = {
            "user_id": user_id,
            "name": name,
            "total_grams": _num(p.get("total_grams")),
            "calories": _num(p.get("calories")),
            "protein": _num(p.get("protein")),
            "fat": _num(p.get("fat")),
            "carbs": _num(p.get("carbs")),
        }
        dish_id = _int(p.get("id"))
        if dish_id:
            _supabase(
                "PATCH",
                f"dishes?id=eq.{dish_id}&user_id=eq.{user_id}",
                body=body,
            )
            _supabase("DELETE", f"dish_items?dish_id=eq.{dish_id}")
        else:
            rows = _supabase("POST", "dishes", body=body, prefer="return=representation")
            dish_id = rows[0]["id"] if rows else None
        if not dish_id:
            raise RuntimeError("dish_not_saved")
        payload = [
            {
                "dish_id": dish_id,
                "name": str(it.get("name", ""))[:200],
                "grams": _num(it.get("grams")),
                "calories": _num(it.get("calories")),
                "protein": _num(it.get("protein")),
                "fat": _num(it.get("fat")),
                "carbs": _num(it.get("carbs")),
            }
            for it in items
        ]
        _supabase("POST", "dish_items", body=payload, prefer="return=representation")
        return {"id": dish_id}

    def _op_dish_delete(self, user_id: int, p: dict):
        dish_id = _int(p.get("id"))
        if not dish_id:
            raise RuntimeError("bad_id")
        owned = _supabase(
            "GET", f"dishes?id=eq.{dish_id}&user_id=eq.{user_id}&select=id&limit=1"
        )
        if not owned:
            raise RuntimeError("forbidden")
        _supabase("DELETE", f"dish_items?dish_id=eq.{dish_id}")
        _supabase("DELETE", f"dishes?id=eq.{dish_id}&user_id=eq.{user_id}")
        return True

    def _op_dish_items_get(self, user_id: int, p: dict):
        dish_id = _int(p.get("id"))
        if not dish_id:
            raise RuntimeError("bad_id")
        rows = _supabase("GET", f"dish_items?dish_id=eq.{dish_id}&select=*")
        owned = _supabase(
            "GET", f"dishes?id=eq.{dish_id}&user_id=eq.{user_id}&select=id&limit=1"
        )
        if not owned:
            return []
        return rows

    def _op_photos_list(self, user_id: int, p: dict):
        prefix = f"u{user_id}/"
        rows = _storage("POST", "object/list/photos", body={"prefix": prefix, "limit": 1000})
        names = []
        for row in rows or []:
            name = row.get("name") if isinstance(row, dict) else None
            if not name:
                continue
            names.append(name if name.startswith(prefix) else prefix + name)
        return names

    def _op_photos_upload(self, user_id: int, p: dict):
        kind = str(p.get("kind", ""))
        if kind not in PHOTO_KIND:
            raise RuntimeError("bad_kind")
        object_id = _int(p.get("id"))
        if not object_id:
            raise RuntimeError("bad_id")
        content = str(p.get("content", ""))
        try:
            raw = base64.b64decode(content)
        except Exception:
            raise RuntimeError("bad_content")
        if len(raw) > 25 * 1024 * 1024:
            raise RuntimeError("too_large")
        mime = str(p.get("mime", "image/jpeg"))[:60]
        name = f"u{user_id}/{PHOTO_KIND[kind]}-{object_id}.jpg"
        _storage(
            "POST",
            f"object/photos/{name}",
            raw_body=raw,
            headers_extra={"Content-Type": mime, "x-upsert": "true"},
        )
        return {"name": name, "url": f"{SUPABASE_URL}/storage/v1/object/public/photos/{name}"}

    def _op_photos_delete(self, user_id: int, p: dict):
        name = str(p.get("name", ""))
        prefix = f"u{user_id}/"
        if not name.startswith(prefix):
            raise RuntimeError("forbidden")
        _storage("DELETE", f"object/photos/{name}")
        return True

    def _op_photo_url(self, user_id: int, p: dict):
        kind = str(p.get("kind", ""))
        if kind not in PHOTO_KIND:
            raise RuntimeError("bad_kind")
        object_id = _int(p.get("id"))
        if not object_id:
            raise RuntimeError("bad_id")
        name = f"u{user_id}/{PHOTO_KIND[kind]}-{object_id}.jpg"
        return {"url": f"{SUPABASE_URL}/storage/v1/object/public/photos/{name}"}

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass
