from __future__ import annotations

import aiohttp

from xau_signal_bot.bot.config import Settings
from urllib.parse import urlparse

from xau_signal_bot.services.http import fetch_json, fetch_text
from xau_signal_bot.services.models import Direction, NewsItem, SourceResult
from xau_signal_bot.services.parsing import headline_direction, parse_datetime


class NewsService:
    name = "Gold/USD News"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_recent_news(self, session: aiohttp.ClientSession) -> SourceResult:
        items: list[NewsItem] = []
        errors: list[str] = []

        if self.settings.news_api_key:
            newsapi_items, newsapi_error = await self._newsapi(session)
            items.extend(newsapi_items)
            if newsapi_error:
                errors.append(newsapi_error)

        if self.settings.reuters_api_url:
            reuters_items, reuters_error = await self._reuters(session)
            items.extend(reuters_items)
            if reuters_error:
                errors.append(reuters_error)

        rss_items, rss_errors = await self._rss(session)
        items.extend(rss_items)
        errors.extend(rss_errors)

        unique: dict[str, NewsItem] = {}
        for item in items:
            unique[item.url or item.title] = item
        items = list(unique.values())[:15]

        if not items and errors:
            return SourceResult.unavailable(self.name, "; ".join(errors))

        direction = self._aggregate(items)
        return SourceResult(
            name=self.name,
            ok=True,
            direction=direction,
            summary=f"{len(items)} relevant headlines",
            data={"items": [item.to_dict() for item in items], "errors": errors},
        )

    async def get_rss_source(self, session: aiohttp.ClientSession, url: str) -> SourceResult:
        try:
            import feedparser
        except ImportError:
            return SourceResult.unavailable(self._rss_name(url), "feedparser is not installed", url=url)
        try:
            text = await fetch_text(session, url)
            feed = feedparser.parse(text)
            name = str(getattr(feed.feed, "title", "") or self._rss_name(url))
            items: list[NewsItem] = []
            for entry in feed.entries[:30]:
                title = str(getattr(entry, "title", ""))
                description = str(getattr(entry, "description", ""))
                searchable = f"{title} {description}".lower()
                if not any(keyword in searchable for keyword in ("gold", "xau", "dollar", "usd", "fed", "treasury", "inflation", "rates")):
                    continue
                items.append(
                    NewsItem(
                        title=title,
                        source=name,
                        published_at=parse_datetime(str(getattr(entry, "published", ""))),
                        url=str(getattr(entry, "link", "")) or None,
                        direction=headline_direction(f"{title} {description}"),
                    )
                )
                if len(items) >= 10:
                    break
            return SourceResult(
                name=name,
                ok=True,
                direction=self._aggregate(items),
                summary=f"{len(items)} relevant headlines",
                data={"items": [item.to_dict() for item in items]},
                url=url,
            )
        except Exception as exc:  # noqa: BLE001
            return SourceResult.unavailable(self._rss_name(url), str(exc), url=url)

    async def _newsapi(self, session: aiohttp.ClientSession) -> tuple[list[NewsItem], str | None]:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": '(gold OR XAUUSD OR "XAU/USD") AND (dollar OR USD OR Fed)',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 10,
            "apiKey": self.settings.news_api_key,
        }
        try:
            payload = await fetch_json(session, url, params=params)
            return [
                NewsItem(
                    title=str(article.get("title") or ""),
                    source=str((article.get("source") or {}).get("name") or "NewsAPI"),
                    published_at=parse_datetime(str(article.get("publishedAt") or "")),
                    url=str(article.get("url") or "") or None,
                    direction=headline_direction(str(article.get("title") or "")),
                )
                for article in payload.get("articles", [])
                if article.get("title")
            ], None
        except Exception as exc:  # noqa: BLE001
            return [], f"NewsAPI: {exc}"

    async def _reuters(self, session: aiohttp.ClientSession) -> tuple[list[NewsItem], str | None]:
        headers = {"Authorization": f"Bearer {self.settings.reuters_api_key}"} if self.settings.reuters_api_key else {}
        try:
            payload = await fetch_json(session, self.settings.reuters_api_url, headers=headers, params={"q": "gold USD"})
            raw_items = payload.get("items") or payload.get("articles") or []
            return [
                NewsItem(
                    title=str(item.get("title") or item.get("headline") or ""),
                    source="Reuters",
                    published_at=parse_datetime(str(item.get("publishedAt") or item.get("date") or "")),
                    url=str(item.get("url") or "") or None,
                    direction=headline_direction(str(item.get("title") or item.get("headline") or "")),
                )
                for item in raw_items
                if item.get("title") or item.get("headline")
            ], None
        except Exception as exc:  # noqa: BLE001
            return [], f"Reuters: {exc}"

    async def _rss(self, session: aiohttp.ClientSession) -> tuple[list[NewsItem], list[str]]:
        try:
            import feedparser
        except ImportError:
            return [], ["RSS: feedparser is not installed"]
        items: list[NewsItem] = []
        errors: list[str] = []
        for url in self.settings.news_rss_urls:
            try:
                text = await fetch_text(session, url)
                feed = feedparser.parse(text)
                for entry in feed.entries[:20]:
                    title = str(getattr(entry, "title", ""))
                    if not any(keyword in title.lower() for keyword in ("gold", "xau", "dollar", "fed", "treasury")):
                        continue
                    items.append(
                        NewsItem(
                            title=title,
                            source=str(getattr(feed.feed, "title", "RSS")),
                            published_at=parse_datetime(str(getattr(entry, "published", ""))),
                            url=str(getattr(entry, "link", "")) or None,
                            direction=headline_direction(title),
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url}: {exc}")
        return items, errors

    @staticmethod
    def _rss_name(url: str) -> str:
        host = urlparse(url).netloc.replace("www.", "")
        return f"{host} RSS"

    @staticmethod
    def _aggregate(items: list[NewsItem]) -> Direction:
        bullish = sum(item.direction == Direction.BULLISH for item in items)
        bearish = sum(item.direction == Direction.BEARISH for item in items)
        if bullish > bearish:
            return Direction.BULLISH
        if bearish > bullish:
            return Direction.BEARISH
        return Direction.NEUTRAL
