import asyncio
from http.server import BaseHTTPRequestHandler

from aiogram.types import Update

from bot.app import create_bot, create_dispatcher
from bot.auth import webhook_secret_token
from bot.config import BOT_TOKEN, WEBHOOK_SECRET


def _valid_secrets() -> set:
    """Прийнятні секрети: заданий у env або детермінований із BOT_TOKEN."""
    tokens = set()
    if WEBHOOK_SECRET:
        tokens.add(WEBHOOK_SECRET)
    derived = webhook_secret_token(BOT_TOKEN)
    if derived:
        tokens.add(derived)
    return tokens


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length).decode("utf-8")

        secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        valid = _valid_secrets()
        if valid and secret not in valid:
            self.send_response(403)
            self.end_headers()
            return

        asyncio.run(self._process(body))

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    async def _process(self, body: str) -> None:
        bot = create_bot()
        dp = create_dispatcher()
        update = Update.model_validate_json(body)
        try:
            await dp.feed_update(bot, update)
        finally:
            await bot.session.close()

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"bot is alive")

    def log_message(self, *args) -> None:
        pass
