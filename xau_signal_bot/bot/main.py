from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from xau_signal_bot.bot.config import get_settings
from xau_signal_bot.bot.handlers import create_router
from xau_signal_bot.bot.scheduler import build_scheduler
from xau_signal_bot.bot.telegram_session import build_telegram_session
from xau_signal_bot.database.db import Database
from xau_signal_bot.services.signal_service import SignalService
from xau_signal_bot.utils.logger import setup_logging

logger = logging.getLogger(__name__)
POLLING_RETRY_SECONDS = 10


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    db = Database(settings)
    await db.init()

    bot = Bot(
        token=settings.telegram_bot_token,
        session=build_telegram_session(settings),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    signal_service = SignalService(settings)
    dispatcher.include_router(create_router(db, signal_service))

    scheduler = build_scheduler(settings, db, signal_service, bot)
    scheduler.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    polling_task = asyncio.create_task(_run_polling_with_retry(dispatcher, bot, stop_event))
    await stop_event.wait()
    polling_task.cancel()
    with suppress(asyncio.CancelledError):
        await polling_task
    scheduler.shutdown(wait=False)
    await bot.session.close()
    await db.close()


async def _run_polling_with_retry(dispatcher: Dispatcher, bot: Bot, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await dispatcher.start_polling(bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Telegram polling failed (%s); retrying in %s seconds", exc, POLLING_RETRY_SECONDS)
        else:
            if not stop_event.is_set():
                logger.warning("Telegram polling stopped unexpectedly; retrying in %s seconds", POLLING_RETRY_SECONDS)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLLING_RETRY_SECONDS)
        except TimeoutError:
            continue


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
