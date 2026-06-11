from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.database.db import Database
from xau_signal_bot.services.models import Decision
from xau_signal_bot.services.signal_service import SignalService
from xau_signal_bot.utils.formatting import format_signal_alert

logger = logging.getLogger(__name__)


def build_scheduler(settings: Settings, db: Database, signal_service: SignalService, bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_alert_scan,
        "interval",
        minutes=settings.alert_interval_minutes,
        args=[settings, db, signal_service, bot],
        id="xau_signal_alert_scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_alert_scan,
        "date",
        args=[settings, db, signal_service, bot],
        id="xau_signal_alert_scan_startup",
        replace_existing=True,
    )
    return scheduler


async def run_alert_scan(settings: Settings, db: Database, signal_service: SignalService, bot: Bot) -> None:
    users = await db.get_alert_users()
    for user, db_settings in users:
        prefs = db.to_signal_settings(db_settings)
        try:
            result = await signal_service.analyze(prefs)
            if result.decision == Decision.NO_TRADE:
                continue
            if not result.risk:
                continue
            if result.confidence < prefs.minimum_confidence:
                continue
            if not _cooldown_passed(db_settings.last_alert_at, settings.alert_cooldown_minutes):
                continue
            key = _alert_key(result)
            if key == db_settings.last_alert_key:
                continue
            await bot.send_message(user.telegram_id, format_signal_alert(result))
            await db.save_signal(result, user.telegram_id)
            await db.update_alert_state(db_settings.id, key)
        except TelegramNetworkError as exc:
            logger.warning("Alert send failed for user %s (%s)", user.telegram_id, exc)
        except Exception:
            logger.exception("Alert scan failed for user %s", user.telegram_id)


def _cooldown_passed(last_alert_at: datetime | None, cooldown_minutes: int) -> bool:
    if not last_alert_at:
        return True
    if last_alert_at.tzinfo is None:
        last_alert_at = last_alert_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last_alert_at >= timedelta(minutes=cooldown_minutes)


def _alert_key(result) -> str:
    entry = result.risk.entry if result.risk else 0
    return f"{result.decision.value}:{round(entry, 1)}:{result.confidence}"
