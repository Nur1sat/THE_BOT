from __future__ import annotations

import re
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import aiohttp

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.http import fetch_text
from xau_signal_bot.services.models import CalendarEvent, Direction, SourceResult


MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


class FedService:
    name = "Federal Reserve Calendar"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_calendar(self, session: aiohttp.ClientSession) -> SourceResult:
        url = self.settings.fed_calendar_url
        try:
            try:
                from bs4 import BeautifulSoup
            except ImportError:
                return SourceResult.unavailable(self.name, "beautifulsoup4 is not installed", url=url)

            html = await fetch_text(session, url)
            text = BeautifulSoup(html, "html.parser").get_text("\n")
            events = self._parse_events(text, url)
            return SourceResult(
                name=self.name,
                ok=True,
                direction=Direction.NEUTRAL,
                summary=f"{len(events)} upcoming FOMC events parsed",
                data={"events": [event.to_dict() for event in events]},
                url=url,
            )
        except Exception as exc:  # noqa: BLE001
            return SourceResult.unavailable(self.name, str(exc), url=url)

    def _parse_events(self, text: str, url: str) -> list[CalendarEvent]:
        eastern = ZoneInfo("America/New_York")
        now = datetime.now(timezone.utc)
        current_year = now.year
        events: list[CalendarEvent] = []
        active_year = current_year
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            year_match = re.search(r"\b(20\d{2})\b", line)
            if year_match:
                active_year = int(year_match.group(1))
            month_match = re.search(
                r"\b("
                + "|".join(MONTHS)
                + r")\s+(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?",
                line,
                flags=re.IGNORECASE,
            )
            if not month_match:
                continue
            month = MONTHS[month_match.group(1).lower()]
            day = int(month_match.group(3) or month_match.group(2))
            try:
                starts_at = datetime.combine(
                    datetime(active_year, month, day).date(),
                    time(hour=14, minute=0),
                    tzinfo=eastern,
                ).astimezone(timezone.utc)
            except ValueError:
                continue
            if starts_at < now:
                continue
            events.append(
                CalendarEvent(
                    title="FOMC rate decision / statement",
                    currency="USD",
                    impact="High",
                    starts_at=starts_at,
                    source=self.name,
                    url=url,
                )
            )
        deduped: dict[str, CalendarEvent] = {}
        for event in events:
            key = event.starts_at.isoformat() if event.starts_at else event.title
            deduped[key] = event
        return sorted(deduped.values(), key=lambda event: event.starts_at or datetime.max.replace(tzinfo=timezone.utc))
