"""Ендпоїнт /auth: підтверджує Telegram initData і видає Supabase JWT.

Виклик із міні-апу:
    POST /auth  {"init_data": "<Telegram.WebApp.initData>"}
Відповідь:
    {"token": "<jwt>", "user_id": 123, "username": "...", "expires_at": 1730000000, "rls_ok": true}
"""

import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from bot.auth import JWT_TTL, decode_jwt_header, make_jwt, verify_init_data
from bot.config import SUPABASE_KEY, SUPABASE_URL

PROBE_PATH = "profiles?select=user_id&limit=1"


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        init_data = self._extract(raw)
        self._handle(init_data)

    def do_GET(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        init_data = (params.get("initData") or params.get("init_data") or [""])[0]
        self._handle(init_data)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _extract(self, raw: str) -> str:
        raw = (raw or "").strip()
        if not raw:
            return ""
        if raw.startswith("{"):
            try:
                data = json.loads(raw)
            except ValueError:
                return ""
            for key in ("init_data", "initData", "data"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
            return ""
        if "=" in raw and "hash=" in raw:
            from urllib.parse import parse_qsl

            pairs = dict(parse_qsl(raw, keep_blank_values=True))
            return pairs.get("init_data") or pairs.get("initData") or raw
        return raw

    def _handle(self, init_data: str) -> None:
        verified = verify_init_data(init_data)
        if not verified:
            self._send(401, {"error": "invalid_init_data"})
            return

        user_id = verified["user_id"]
        try:
            token = make_jwt(user_id)
        except RuntimeError:
            self._send(503, {"error": "jwt_secret_missing"})
            return

        user = verified["user"]
        header = decode_jwt_header(token)
        self._send(
            200,
            {
                "token": token,
                "user_id": user_id,
                "username": user.get("username") or "",
                "first_name": user.get("first_name") or "",
                "expires_at": verified["auth_date"] + JWT_TTL,
                "alg": header.get("alg") or "",
                "rls_ok": self._probe(token),
            },
        )

    def _probe(self, token: str) -> bool:
        """Перевіряє, що підписаний токен приймається PostgREST (RLL увімкнено)."""
        if not SUPABASE_URL or not SUPABASE_KEY:
            return False
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/{PROBE_PATH}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as err:
            return 200 <= err.code < 300
        except Exception:
            return False

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass
