"""Telegram mesaj kuyruğu (rate-limit dostu, mesaj kaybetmez)."""
import asyncio
import logging
from datetime import timedelta

import config

logger = logging.getLogger("BIST_QUANT")


class TelegramQueue:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.bot = None
        if not config.DRY_RUN:
            from telegram import Bot
            self.bot = Bot(token=config.TELEGRAM_TOKEN)

    async def send_photo(self, photo: bytes, caption: str):
        await self.queue.put(("photo", photo, caption))

    async def send_text(self, text: str):
        await self.queue.put(("text", None, text))

    async def _deliver(self, kind, photo, text):
        from telegram import InputFile
        if kind == "photo":
            await self.bot.send_photo(config.CHAT_ID, photo=InputFile(photo, filename="chart.png"),
                                      caption=text, parse_mode="HTML")
        else:
            await self.bot.send_message(config.CHAT_ID, text=text, parse_mode="HTML")

    async def worker(self):
        if config.DRY_RUN:
            logger.warning("DRY_RUN: Telegram bilgisi yok, mesajlar sadece loglanacak.")
            while True:
                kind, _, text = await self.queue.get()
                logger.info(f"[DRY_RUN {kind}] {text}")
                self.queue.task_done()

        from telegram.error import RetryAfter, NetworkError, TimedOut
        async with self.bot:  # PTB v20+ : initialize/shutdown
            logger.info("📨 Mesaj kuyruğu hazır")
            while True:
                kind, photo, text = await self.queue.get()
                for attempt in range(1, 4):
                    try:
                        await self._deliver(kind, photo, text)
                        break
                    except RetryAfter as e:
                        wait = e.retry_after
                        wait = wait.total_seconds() if isinstance(wait, timedelta) else float(wait)
                        logger.warning(f"Telegram rate limit: {wait:.0f}s bekleniyor")
                        await asyncio.sleep(wait + 1)
                    except (NetworkError, TimedOut) as e:
                        logger.warning(f"Telegram ağ hatası ({attempt}/3): {e}")
                        await asyncio.sleep(5 * attempt)
                    except Exception as e:
                        logger.error(f"Telegram mesaj hatası: {e}")
                        break
                self.queue.task_done()
                await asyncio.sleep(3)  # grup sohbetlerinde ~20 msg/dk sınırı
