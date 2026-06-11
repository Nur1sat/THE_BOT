from __future__ import annotations

from datetime import datetime, timezone

import aiohttp

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.http import fetch_json
from xau_signal_bot.services.models import Direction, MarketData, SourceResult


class SwissquoteService:
    name = "Swissquote XAU/USD"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_live_quote(self, session: aiohttp.ClientSession) -> tuple[MarketData | None, SourceResult]:
        url = self.settings.swissquote_xauusd_url
        try:
            payload = await fetch_json(session, url)
            if not isinstance(payload, list) or not payload:
                return None, SourceResult.unavailable(self.name, "Swissquote returned an empty quote list", url=url)
            quote = self._select_quote(payload)
            if not quote:
                return None, SourceResult.unavailable(self.name, "Swissquote quote did not include bid/ask", url=url)
            bid = float(quote["bid"])
            ask = float(quote["ask"])
            price = (bid + ask) / 2
            timestamp_ms = int(quote.get("ts") or 0)
            timestamp = datetime.now(timezone.utc)
            if timestamp_ms > 0:
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
            market_data = MarketData(
                source=self.name,
                symbol="XAU/USD",
                price=price,
                candles=None,
                timestamp=timestamp,
            )
            return (
                market_data,
                SourceResult(
                    name=self.name,
                    ok=True,
                    direction=Direction.NEUTRAL,
                    summary=f"Bid {bid:.2f} / Ask {ask:.2f}",
                    data={"symbol": "XAU/USD", "bid": bid, "ask": ask, "mid": price},
                    url=url,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return None, SourceResult.unavailable(self.name, str(exc), url=url)

    @staticmethod
    def _select_quote(payload: list[dict]) -> dict | None:
        for venue in payload:
            timestamp_ms = venue.get("ts")
            prices = venue.get("spreadProfilePrices") or []
            preferred = next((item for item in prices if item.get("spreadProfile") == "prime"), None)
            selected = preferred or (prices[0] if prices else None)
            if selected and selected.get("bid") is not None and selected.get("ask") is not None:
                return {**selected, "ts": timestamp_ms}
        return None
