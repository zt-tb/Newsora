# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).
import asyncio

_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

import logging
from datetime import datetime

from pyrogram import Client, idle
from pyrogram.enums import ParseMode

import config
import store
from engine import Engine
from panel import Panel


class IraqTimeFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, tz=config.IRAQ_TZ).strftime("%Y-%m-%d %H:%M:%S")


_h = logging.StreamHandler()
_h.setFormatter(IraqTimeFormatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_h])
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("telethon").setLevel(logging.WARNING)
logger = logging.getLogger("main")


async def main():
    settings = store.Settings()
    hashes = store.HashStore()

    app = Client(
        "newsbot", api_id=config.API_ID, api_hash=config.API_HASH, bot_token=config.BOT_TOKEN,
        in_memory=True, parse_mode=ParseMode.DISABLED,
    )

    holder = {}

    async def notify(text):
        await holder["panel"].notify(text)

    engine = Engine(app, settings, hashes, notify)
    panel = Panel(app, engine, settings)
    holder["panel"] = panel
    panel.register()

    await app.start()
    me = await app.get_me()
    logger.info("bot started as @%s | owner=%s | target=%s", me.username, config.OWNER_ID, config.TARGET_CHANNEL)

    await engine.start()
    try:
        warn = ""
        if config.ON_RAILWAY and not config.PERSISTENT:
            warn = ("\n\n⚠️ ما لقيت Volume مربوط: السجل والسيشن يضيعون مع كل نشر جديد. "
                    "أنشئ Volume وربطه بالمسار /data وضع DATA_DIR=/data.")
        await panel.notify("🤖 البوت اشتغل. افتح اللوحة:" + warn)
    except Exception as e:
        logger.warning("لم أستطع مراسلة المالك (افتح البوت وأرسل /start مرة وحدة): %s", e)

    await idle()
    logger.info("shutting down…")
    await engine.shutdown()
    await app.stop()


if __name__ == "__main__":
    _loop.run_until_complete(main())
