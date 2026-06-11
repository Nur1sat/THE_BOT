from __future__ import annotations

import asyncio
import contextlib
import logging

import aiohttp
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from xau_signal_bot.database.db import Database
from xau_signal_bot.services.models import UserSignalSettings
from xau_signal_bot.services.signal_service import SignalService
from xau_signal_bot.utils.formatting import (
    format_calendar,
    format_help,
    format_live_price,
    format_price,
    format_sentiment,
    format_settings,
    format_signal,
    format_sources,
)

logger = logging.getLogger(__name__)
_price_tasks: dict[int, asyncio.Task[None]] = {}
SIGNAL_TIMEFRAMES = ("1m", "3m", "5m")


def create_router(db: Database, signal_service: SignalService) -> Router:
    router = Router()

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        await _ensure_user(db, message)
        await message.answer(
            "This bot analyzes XAU/USD from multiple independent source adapters and returns LONG, SHORT, or NO TRADE. "
            "Use /signal to choose a 1-minute, 3-minute, or 5-minute trade time. No signal is guaranteed.\n\n"
            + format_help()
        )

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await _ensure_user(db, message)
        await message.answer(format_help())

    @router.message(Command("signal"))
    async def signal(message: Message) -> None:
        await _ensure_user(db, message)
        args = _command_args(message)
        if args:
            timeframe = _parse_signal_timeframe(args[0])
            if timeframe:
                await _send_signal_for_timeframe(message, db, signal_service, message.from_user.id, timeframe)
                return
        await message.answer("Choose XAU/USD signal trade time:", reply_markup=_signal_timeframe_keyboard())

    @router.callback_query(F.data.startswith("signal_timeframe:"))
    async def signal_timeframe(callback: CallbackQuery) -> None:
        timeframe = _parse_signal_timeframe((callback.data or "").split(":", 1)[-1])
        if not timeframe:
            await callback.answer("Unsupported timeframe", show_alert=True)
            return
        await callback.answer()
        if not callback.message:
            return
        await db.get_or_create_user(
            callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        await _send_signal_for_timeframe(callback.message, db, signal_service, callback.from_user.id, timeframe, edit=True)

    @router.message(Command("price"))
    async def price(message: Message) -> None:
        await _ensure_user(db, message)
        chat_id = message.chat.id
        await _stop_price_task(chat_id)
        live_message = await message.answer("Starting live XAU/USD price...")
        task = asyncio.create_task(_run_live_price(live_message, signal_service))
        _price_tasks[chat_id] = task
        task.add_done_callback(lambda _: _price_tasks.pop(chat_id, None))

    @router.message(Command("price_stop"))
    async def price_stop(message: Message) -> None:
        stopped = await _stop_price_task(message.chat.id)
        if stopped:
            await message.answer("Live XAU/USD price updates stopped.")
        else:
            await message.answer("No live price updater is running in this chat.")

    @router.message(Command("sources"))
    async def sources(message: Message) -> None:
        await _ensure_user(db, message)
        prefs = await db.get_user_settings(message.from_user.id)
        source_results = await signal_service.sources(prefs)
        await message.answer(format_sources(source_results))

    @router.message(Command("sentiment"))
    async def sentiment(message: Message) -> None:
        await _ensure_user(db, message)
        source = await signal_service.sentiment()
        await message.answer(format_sentiment(source))

    @router.message(Command("calendar"))
    async def calendar(message: Message) -> None:
        await _ensure_user(db, message)
        events, source_results = await signal_service.calendar()
        await message.answer(format_calendar(events, source_results))

    @router.message(Command("settings"))
    async def settings(message: Message) -> None:
        await _ensure_user(db, message)
        args = _command_args(message)
        if not args:
            prefs = await db.get_user_settings(message.from_user.id)
            await message.answer(format_settings(prefs))
            return
        updates, error = _parse_settings(args)
        if error:
            prefs = await db.get_user_settings(message.from_user.id)
            await message.answer(f"{error}\n\n{format_settings(prefs)}")
            return
        prefs = await db.update_user_settings(message.from_user.id, updates)
        await message.answer(format_settings(prefs))

    return router


async def _run_live_price(message: Message, signal_service: SignalService) -> None:
    refresh_seconds = max(1.0, float(signal_service.settings.price_live_refresh_seconds))
    try:
        timeout = aiohttp.ClientTimeout(total=signal_service.settings.http_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                market_data, sources = await signal_service.price_service.get_live_quote(session)
                text = format_live_price(market_data, sources, refresh_seconds)
                try:
                    await message.edit_text(text)
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(float(exc.retry_after))
                    continue
                except TelegramBadRequest as exc:
                    if "message is not modified" not in str(exc).lower():
                        raise
                await asyncio.sleep(refresh_seconds)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Live price updater failed")
        with contextlib.suppress(Exception):
            await message.edit_text("Live XAU/USD price updater stopped because the price source failed.")


async def _stop_price_task(chat_id: int) -> bool:
    task = _price_tasks.pop(chat_id, None)
    if not task:
        return False
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    return True


async def _ensure_user(db: Database, message: Message) -> None:
    if not message.from_user:
        return
    await db.get_or_create_user(
        message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )


def _command_args(message: Message) -> list[str]:
    if not message.text:
        return []
    parts = message.text.split()
    return parts[1:]


def _parse_settings(args: list[str]) -> tuple[dict[str, object], str | None]:
    if len(args) < 2:
        return {}, "Use /settings <field> <value>."
    field = args[0].lower()
    value = args[1].lower()
    if field == "timeframe":
        if value not in set(SIGNAL_TIMEFRAMES):
            return {}, "Timeframe must be one of: 1m, 3m, 5m."
        return {"timeframe": value}, None
    if field in {"min_confidence", "minimum_confidence"}:
        try:
            confidence = int(value)
        except ValueError:
            return {}, "Minimum confidence must be a number from 0 to 100."
        if not 0 <= confidence <= 100:
            return {}, "Minimum confidence must be from 0 to 100."
        return {"minimum_confidence": confidence}, None
    if field == "alerts":
        if value not in {"on", "off"}:
            return {}, "Alerts must be on or off."
        return {"alerts_enabled": value == "on"}, None
    if field == "risk":
        try:
            risk = float(value)
        except ValueError:
            return {}, "Risk must be a number, for example 1.0."
        if risk <= 0 or risk > 10:
            return {}, "Risk percentage must be greater than 0 and no more than 10."
        return {"risk_percentage": risk}, None
    if field == "news_filter":
        if value not in {"on", "off"}:
            return {}, "News filter must be on or off."
        return {"news_filter_enabled": value == "on"}, None
    return {}, "Unknown setting field."


def settings_from_db(settings) -> UserSignalSettings:
    return UserSignalSettings(
        timeframe=settings.timeframe,
        minimum_confidence=settings.minimum_confidence,
        alerts_enabled=settings.alerts_enabled,
        risk_percentage=settings.risk_percentage,
        news_filter_enabled=settings.news_filter_enabled,
    )


async def _send_signal_for_timeframe(
    message: Message,
    db: Database,
    signal_service: SignalService,
    telegram_id: int,
    timeframe: str,
    *,
    edit: bool = False,
) -> None:
    label = _timeframe_label(timeframe)
    if edit:
        await message.edit_text(f"Analyzing XAU/USD {label} signal...")
        progress = message
    else:
        progress = await message.answer(f"Analyzing XAU/USD {label} signal...")
    prefs = await db.get_user_settings(telegram_id)
    prefs.timeframe = timeframe
    result = await signal_service.analyze(prefs)
    await db.save_signal(result, telegram_id)
    await progress.edit_text(format_signal(result))


def _signal_timeframe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 minute", callback_data="signal_timeframe:1m"),
                InlineKeyboardButton(text="3 minutes", callback_data="signal_timeframe:3m"),
                InlineKeyboardButton(text="5 minutes", callback_data="signal_timeframe:5m"),
            ]
        ]
    )


def _parse_signal_timeframe(value: str) -> str | None:
    normalized = value.strip().lower()
    aliases = {
        "1": "1m",
        "1m": "1m",
        "1min": "1m",
        "1minute": "1m",
        "3": "3m",
        "3m": "3m",
        "3min": "3m",
        "3minutes": "3m",
        "5": "5m",
        "5m": "5m",
        "5min": "5m",
        "5minutes": "5m",
    }
    return aliases.get(normalized)


def _timeframe_label(timeframe: str) -> str:
    return {
        "1m": "1 minute",
        "3m": "3 minutes",
        "5m": "5 minutes",
    }.get(timeframe, timeframe)
