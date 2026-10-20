import json
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse


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
        url = (
            "https://world.openfoodfacts.org/api/v2/product/"
            f"{code}.json?fields=product_name,product_name_uk,generic_name,"
            "brands,nutriments"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "CaloriesBot/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            return None
        if data.get("status") != 1 or not data.get("product"):
            return None
        p = data["product"]
        n = p.get("nutriments") or {}
        kcal = n.get("energy-kcal_100g")
        if kcal is None and n.get("energy_100g"):
            kcal = round(n["energy_100g"] / 4.184, 1)
        name = p.get("product_name_uk") or p.get("product_name") or p.get("generic_name") or ""
        if not name:
            return None
        return {
            "found": True,
            "name": name + (f" ({p['brands']})" if p.get("brands") else ""),
            "calories": kcal or 0,
            "protein": n.get("proteins_100g") or 0,
            "fat": n.get("fat_100g") or 0,
            "carbs": n.get("carbohydrates_100g") or 0,
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
