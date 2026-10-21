import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from bot.off import lookup_barcode


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        code = (params.get("code") or [""])[0].strip()
        if not code.isdigit():
            self._send(400, {"found": False, "error": "bad_code"})
            return
        product = self._lookup(code)
        self._send(200, product or {"found": False})

    def _lookup(self, code: str) -> dict | None:
        found = lookup_barcode(code)
        if not found:
            return None
        return {
            "found": True,
            "name": found["display_name"],
            "calories": found["calories"],
            "protein": found["protein"],
            "fat": found["fat"],
            "carbs": found["carbs"],
            "image_url": found["image_url"],
        }

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass
