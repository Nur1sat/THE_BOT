from __future__ import annotations

import aiohttp

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.http import fetch_json, fetch_text
from xau_signal_bot.services.models import CalendarEvent, Direction, NewsItem, SourceResult
from xau_signal_bot.services.parsing import headline_direction, normalize_impact, parse_datetime


class FXStreetService:
    news_name = "FXStreet News"
    calendar_name = "FXStreet Calendar"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_gold_news(self, session: aiohttp.ClientSession) -> SourceResult:
        url = self.settings.fxstreet_news_rss_url
        try:
            import feedparser
        except ImportError:
            return SourceResult.unavailable(self.news_name, "feedparser is not installed", url=url)
        try:
            text = await fetch_text(session, url)
            feed = feedparser.parse(text)
            items: list[NewsItem] = []
            for entry in feed.entries[:30]:
                title = str(getattr(entry, "title", ""))
                if not any(keyword in title.lower() for keyword in ("gold", "xau", "xau/usd", "dollar", "fed")):
                    continue
                items.append(
                    NewsItem(
                        title=title,
                        source=self.news_name,
                        published_at=parse_datetime(str(getattr(entry, "published", ""))),
                        url=str(getattr(entry, "link", "")) or None,
                        direction=headline_direction(title),
                    )
                )
                if len(items) >= 10:
                    break
            direction = _aggregate_news_direction(items)
            return SourceResult(
                name=self.news_name,
                ok=True,
                direction=direction,
                summary=f"{len(items)} relevant headlines",
                data={"items": [item.to_dict() for item in items]},
                url=url,
            )
        except Exception as exc:  # noqa: BLE001
            return SourceResult.unavailable(self.news_name, str(exc), url=url)

    async def get_calendar(self, session: aiohttp.ClientSession) -> SourceResult:
        url = self.settings.fxstreet_calendar_api_url
        if not url:
            return SourceResult.unavailable(
                self.calendar_name,
                "FXSTREET_CALENDAR_API_URL is not configured.",
            )
        headers = {"Authorization": f"Bearer {self.settings.fxstreet_api_key}"} if self.settings.fxstreet_api_key else {}
        try:
            payload = await fetch_json(session, url, headers=headers, params={"currency": "USD"})
            raw_events = payload.get("events", payload if isinstance(payload, list) else [])
            events = [
                CalendarEvent(
                    title=str(item.get("title") or item.get("event") or "Economic event"),
                    currency="USD",
                    impact=normalize_impact(str(item.get("impact") or item.get("importance") or "")),
                    starts_at=parse_datetime(str(item.get("date") or item.get("time") or item.get("datetime") or "")),
                    source=self.calendar_name,
                    url=url,
                )
                for item in raw_events
                if "USD" in str(item.get("currency") or item.get("country") or "USD").upper()
            ]
            return SourceResult(
                name=self.calendar_name,
                ok=True,
                direction=Direction.NEUTRAL,
                summary=f"{len(events)} USD events",
                data={"events": [event.to_dict() for event in events]},
                url=url,
            )
        except Exception as exc:  # noqa: BLE001
            return SourceResult.unavailable(self.calendar_name, str(exc), url=url)


def _aggregate_news_direction(items: list[NewsItem]) -> Direction:
    bullish = sum(item.direction == Direction.BULLISH for item in items)
    bearish = sum(item.direction == Direction.BEARISH for item in items)
    if bullish > bearish:
        return Direction.BULLISH
    if bearish > bullish:
        return Direction.BEARISH
    return Direction.NEUTRAL
