from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from io import StringIO

import aiohttp
import pandas as pd

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.http import fetch_text
from xau_signal_bot.services.models import Direction, MarketData, SourceResult
from xau_signal_bot.services.oanda_service import OandaService
from xau_signal_bot.services.swissquote_service import SwissquoteService
from xau_signal_bot.services.yahoo_service import YahooService


class PriceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.oanda = OandaService(settings)
        self.swissquote = SwissquoteService(settings)
        self.yahoo = YahooService(settings)

    async def collect_market_data(
        self,
        session: aiohttp.ClientSession,
        timeframe: str,
    ) -> tuple[MarketData | None, list[SourceResult]]:
        results: list[SourceResult] = []
        oanda_data = None
        oanda_task = None
        if self.oanda.configured():
            oanda_task = asyncio.create_task(self.oanda.get_market_data(session, timeframe))
        swissquote_task = asyncio.create_task(self.swissquote.get_live_quote(session))
        yahoo_task = asyncio.create_task(self.yahoo.get_market_data(session, timeframe))

        if oanda_task:
            oanda_data, oanda_source = await oanda_task
            results.append(oanda_source)
        swissquote_data, swissquote_source = await swissquote_task
        yahoo_data, yahoo_source = await yahoo_task
        results.append(swissquote_source)
        results.append(yahoo_source)

        stooq_data = None
        if self.settings.stooq_enabled:
            stooq_data, stooq_source = await self.get_stooq_quote(session)
            results.append(stooq_source)

        selected = oanda_data or self._combine_spot_and_candles(swissquote_data, yahoo_data) or yahoo_data or swissquote_data or stooq_data
        return selected, results

    async def get_live_quote(self, session: aiohttp.ClientSession) -> tuple[MarketData | None, list[SourceResult]]:
        results: list[SourceResult] = []
        oanda_data = None
        if self.oanda.configured():
            oanda_data, oanda_source = await self.oanda.get_market_data(session, "5m")
            results.append(oanda_source)
            if oanda_data:
                return oanda_data, results
        swissquote_data, swissquote_source = await self.swissquote.get_live_quote(session)
        results.append(swissquote_source)
        if swissquote_data:
            return swissquote_data, results
        yahoo_data, yahoo_source = await self.yahoo.get_live_quote(session)
        results.append(yahoo_source)
        if yahoo_data:
            return yahoo_data, results
        stooq_data = None
        if self.settings.stooq_enabled:
            stooq_data, stooq_source = await self.get_stooq_quote(session)
            results.append(stooq_source)
        return oanda_data or swissquote_data or yahoo_data or stooq_data, results

    @staticmethod
    def _combine_spot_and_candles(
        spot_data: MarketData | None,
        candle_data: MarketData | None,
    ) -> MarketData | None:
        if not spot_data or not candle_data or candle_data.candles is None:
            return None
        return MarketData(
            source=f"{spot_data.source} + {candle_data.source}",
            symbol=f"{spot_data.symbol} spot / {candle_data.symbol} candles",
            price=spot_data.price,
            candles=candle_data.candles,
            timestamp=spot_data.timestamp,
        )

    async def get_stooq_quote(self, session: aiohttp.ClientSession) -> tuple[MarketData | None, SourceResult]:
        symbol = self.settings.stooq_symbol
        url = "https://stooq.com/q/l/"
        params = {"s": symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"}
        try:
            text = await fetch_text(session, url, params=params)
            frame = pd.read_csv(StringIO(text))
            if frame.empty or "Close" not in frame.columns:
                return None, SourceResult.unavailable("Stooq", "CSV response did not include a Close value", url=url)
            close = frame["Close"].iloc[0]
            if str(close).lower() in {"nan", "n/a", "0"}:
                return None, SourceResult.unavailable("Stooq", f"No quote for symbol {symbol}", url=url)
            price = float(close)
            data = MarketData(
                source="Stooq",
                symbol=symbol,
                price=price,
                candles=None,
                timestamp=datetime.now(timezone.utc),
            )
            return (
                data,
                SourceResult(
                    name="Stooq",
                    ok=True,
                    direction=Direction.NEUTRAL,
                    summary=f"Quote OK for {symbol}",
                    data={"symbol": symbol, "price": price},
                    url=url,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return None, SourceResult.unavailable("Stooq", str(exc), url=url)
