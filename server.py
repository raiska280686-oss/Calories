import asyncio
import logging
import sys

from aiogram import Bot
from aiohttp import web

from bot.app import create_bot, create_dispatcher
from bot.config import BOT_TOKEN, WEBHOOK_BASE_URL, WEBHOOK_SECRET

logging.basicConfig(level=logging.INFO)

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"


async def handle(request: web.Request) -> web.Response:
    bot: Bot = request.app["bot"]
    dp = request.app["dp"]

    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        raise web.HTTPForbidden()

    from aiogram.types import Update

    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return web.Response(text="ok")


async def on_startup(app: web.Application) -> None:
    bot: Bot = app["bot"]
    await bot.set_webhook(
        WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET or None,
        drop_pending_updates=True,
    )
    logging.info("Webhook set to %s", WEBHOOK_URL)


async def on_shutdown(app: web.Application) -> None:
    bot: Bot = app["bot"]
    await bot.delete_webhook()
    await bot.session.close()


async def main() -> None:
    if not WEBHOOK_BASE_URL:
        print("WEBHOOK_BASE_URL is not set", file=sys.stderr)
        return

    bot = create_bot()
    dp = create_dispatcher()

    app = web.Application()
    app["bot"] = bot
    app["dp"] = dp
    app.router.add_post(WEBHOOK_PATH, handle)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    logging.info("Server started on :8080")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
