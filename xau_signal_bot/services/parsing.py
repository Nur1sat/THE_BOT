from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser

from xau_signal_bot.services.models import Direction


BULLISH_WORDS = {
    "advance",
    "advances",
    "bullish",
    "climb",
    "climbs",
    "gain",
    "gains",
    "higher",
    "jump",
    "jumps",
    "rally",
    "rebounds",
    "rise",
    "rises",
    "surge",
    "surges",
    "up",
}
BEARISH_WORDS = {
    "bearish",
    "drop",
    "drops",
    "fall",
    "falls",
    "lower",
    "plunge",
    "plunges",
    "retreat",
    "retreats",
    "selloff",
    "sink",
    "sinks",
    "slip",
    "slips",
    "weak",
}
DOLLAR_STRENGTH_WORDS = {"dollar rises", "dollar gains", "strong dollar", "usd rises", "usd gains"}
DOLLAR_WEAKNESS_WORDS = {"dollar falls", "dollar slips", "weak dollar", "usd falls", "usd slips"}


def direction_from_text(value: str | None) -> Direction:
    text = (value or "").lower().replace("_", " ").replace("-", " ")
    if any(word in text for word in ("strong buy", "buy", "bullish", "long")):
        return Direction.BULLISH
    if any(word in text for word in ("strong sell", "sell", "bearish", "short")):
        return Direction.BEARISH
    if any(word in text for word in ("neutral", "hold", "mixed")):
        return Direction.NEUTRAL
    return Direction.UNKNOWN


def headline_direction(title: str) -> Direction:
    text = title.lower()
    if any(phrase in text for phrase in DOLLAR_STRENGTH_WORDS):
        return Direction.BEARISH
    if any(phrase in text for phrase in DOLLAR_WEAKNESS_WORDS):
        return Direction.BULLISH
    bullish = any(word in text.split() for word in BULLISH_WORDS)
    bearish = any(word in text.split() for word in BEARISH_WORDS)
    if bullish and not bearish:
        return Direction.BULLISH
    if bearish and not bullish:
        return Direction.BEARISH
    return Direction.NEUTRAL


def parse_datetime(value: str | None, *, default_tz: str | None = None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = date_parser.parse(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(default_tz) if default_tz else timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_impact(value: str | None) -> str:
    text = (value or "").strip().lower()
    if "high" in text:
        return "High"
    if "medium" in text or "med" in text:
        return "Medium"
    if "low" in text:
        return "Low"
    return value.strip() if value else "Unknown"
