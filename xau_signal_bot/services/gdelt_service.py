from __future__ import annotations

from urllib.parse import quote_plus

import aiohttp

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.http import fetch_json
from xau_signal_bot.services.models import Direction, NewsItem, SourceResult
from xau_signal_bot.services.parsing import headline_direction, parse_datetime


class GdeltService:
    name = "GDELT Open News"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_gold_news(self, session: aiohttp.ClientSession) -> SourceResult:
        query = 'gold'
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": "8",
            "timespan": "3h",
            "sort": "datedesc",
        }
        url = self.settings.gdelt_doc_api_url
        try:
            payload = await fetch_json(session, url, params=params)
        except Exception as exc:  # noqa: BLE001
            fallback = f"{url}?query={quote_plus(query)}&mode=artlist&format=json&maxrecords=15&timespan=6h"
            return SourceResult.unavailable(self.name, str(exc), url=fallback)

        items: list[NewsItem] = []
        for article in payload.get("articles", [])[:20]:
            title = str(article.get("title") or "").strip()
            if not title:
                continue
            if not any(keyword in title.lower() for keyword in ("gold", "xau", "dollar", "fed", "treasury", "yield", "inflation", "rate")):
                continue
            domain = str(article.get("domain") or article.get("sourceCollectionIdentifier") or "GDELT")
            items.append(
                NewsItem(
                    title=title,
                    source=f"GDELT/{domain}",
                    published_at=parse_datetime(str(article.get("seendate") or article.get("datetime") or "")),
                    url=str(article.get("url") or "") or None,
                    direction=headline_direction(title),
                )
            )
            if len(items) >= 12:
                break

        direction = self._aggregate(items)
        confidence = self._confidence(items, direction)
        summary = f"{len(items)} open-news headlines in 3h"
        if direction in {Direction.BULLISH, Direction.BEARISH}:
            summary = f"{direction.value}: {summary}"

        return SourceResult(
            name=self.name,
            ok=True,
            direction=direction,
            confidence=confidence,
            summary=summary,
            data={
                "items": [item.to_dict() for item in items],
                "query": query,
                "timespan": "3h",
                "note": "GDELT is used as open headline metadata, not republished article text.",
            },
            url=url,
        )

    @staticmethod
    def _aggregate(items: list[NewsItem]) -> Direction:
        bullish = sum(item.direction == Direction.BULLISH for item in items)
        bearish = sum(item.direction == Direction.BEARISH for item in items)
        if bullish > bearish:
            return Direction.BULLISH
        if bearish > bullish:
            return Direction.BEARISH
        return Direction.NEUTRAL

    @staticmethod
    def _confidence(items: list[NewsItem], direction: Direction) -> float:
        if not items:
            return 25.0
        if direction == Direction.NEUTRAL:
            return 40.0
        bullish = sum(item.direction == Direction.BULLISH for item in items)
        bearish = sum(item.direction == Direction.BEARISH for item in items)
        edge = abs(bullish - bearish)
        return float(min(78, 45 + edge * 8))
