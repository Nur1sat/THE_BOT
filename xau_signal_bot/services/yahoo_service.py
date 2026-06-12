from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

import aiohttp
import pandas as pd

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.http import fetch_json
from xau_signal_bot.services.models import Direction, MarketData, SourceResult


INTERVALS = {
    "1m": ("1m", "5d"),
    "3m": ("1m", "5d"),
    "5m": ("5m", "5d"),
    "15m": ("15m", "10d"),
    "1h": ("60m", "60d"),
    "4h": ("60m", "60d"),
}
YAHOO_CHART_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
YAHOO_GOLD_CANDLE_SYMBOLS = ("GC=F", "MGC=F")


class YahooService:
    name = "Yahoo Finance"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_market_data(
        self,
        session: aiohttp.ClientSession,
        timeframe: str,
    ) -> tuple[MarketData | None, SourceResult]:
        interval, data_range = INTERVALS.get(timeframe, INTERVALS["5m"])
        errors: list[str] = []
        for symbol in self._ordered_symbols():
            params = {"interval": interval, "range": data_range, "includePrePost": "false"}
            for host in YAHOO_CHART_HOSTS:
                url = f"https://{host}/v8/finance/chart/{quote(symbol)}"
                try:
                    payload = await fetch_json(session, url, params=params)
                    break
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{symbol} via {host}: {exc}")
            else:
                continue
            try:
                result = (payload.get("chart", {}).get("result") or [None])[0]
                if not result:
                    errors.append(f"{symbol}: empty chart response")
                    continue
                timestamps = result.get("timestamp") or []
                quote_data = (result.get("indicators", {}).get("quote") or [{}])[0]
                frame = pd.DataFrame(
                    {
                        "time": pd.to_datetime(timestamps, unit="s", utc=True),
                        "open": quote_data.get("open"),
                        "high": quote_data.get("high"),
                        "low": quote_data.get("low"),
                        "close": quote_data.get("close"),
                        "volume": quote_data.get("volume"),
                    }
                ).dropna(subset=["open", "high", "low", "close"])
                if frame.empty:
                    errors.append(f"{symbol}: no OHLC candles")
                    continue
                frame = frame.set_index("time").sort_index()
                if timeframe == "3m":
                    frame = self._resample_3m(frame)
                    if frame.empty:
                        errors.append(f"{symbol}: no 3m OHLC candles after resampling")
                        continue
                elif timeframe == "4h":
                    frame = self._resample_4h(frame)
                    if frame.empty:
                        errors.append(f"{symbol}: no 4h OHLC candles after resampling")
                        continue
                meta = result.get("meta", {})
                price = float(meta.get("regularMarketPrice") or frame["close"].iloc[-1])
                market_data = MarketData(
                    source=self.name,
                    symbol=symbol,
                    price=price,
                    candles=frame,
                    timestamp=datetime.now(timezone.utc),
                )
                source = SourceResult(
                    name=self.name,
                    ok=True,
                    direction=Direction.NEUTRAL,
                    summary=f"OHLC data OK for {symbol}" + (" (resampled)" if timeframe in {"3m", "4h"} else ""),
                    data={"symbol": symbol, "timeframe": timeframe, "candles": len(frame)},
                    url=url,
                )
                return market_data, source
            except Exception as exc:  # noqa: BLE001 - source adapters must isolate failures
                errors.append(f"{symbol}: {exc}")
        return None, SourceResult.unavailable(self.name, "; ".join(errors) or "No Yahoo symbols configured")

    async def get_live_quote(self, session: aiohttp.ClientSession) -> tuple[MarketData | None, SourceResult]:
        errors: list[str] = []
        for symbol in self._ordered_symbols():
            params = {"interval": "1m", "range": "1d", "includePrePost": "true"}
            for host in YAHOO_CHART_HOSTS:
                url = f"https://{host}/v8/finance/chart/{quote(symbol)}"
                try:
                    payload = await fetch_json(session, url, params=params)
                    break
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{symbol} via {host}: {exc}")
            else:
                continue
            try:
                result = (payload.get("chart", {}).get("result") or [None])[0]
                if not result:
                    errors.append(f"{symbol}: empty chart response")
                    continue
                meta = result.get("meta", {})
                price = meta.get("regularMarketPrice")
                timestamps = result.get("timestamp") or []
                quote_data = (result.get("indicators", {}).get("quote") or [{}])[0]
                closes = [value for value in quote_data.get("close", []) if value is not None]
                if price is None and closes:
                    price = closes[-1]
                if price is None:
                    errors.append(f"{symbol}: no live price in response")
                    continue
                timestamp = datetime.now(timezone.utc)
                if timestamps:
                    timestamp = datetime.fromtimestamp(timestamps[-1], tz=timezone.utc)
                market_data = MarketData(
                    source=self.name,
                    symbol=symbol,
                    price=float(price),
                    candles=None,
                    timestamp=timestamp,
                )
                source = SourceResult(
                    name=self.name,
                    ok=True,
                    direction=Direction.NEUTRAL,
                    summary=f"Live quote OK for {symbol}",
                    data={"symbol": symbol, "price": float(price)},
                    url=url,
                )
                return market_data, source
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{symbol}: {exc}")
        return None, SourceResult.unavailable(self.name, "; ".join(errors) or "No Yahoo symbols configured")

    def _ordered_symbols(self) -> list[str]:
        symbols: list[str] = []
        for symbol in [*YAHOO_GOLD_CANDLE_SYMBOLS, *self.settings.yahoo_symbols]:
            normalized = symbol.strip()
            if normalized and normalized not in symbols:
                symbols.append(normalized)
        return symbols

    @staticmethod
    def _resample_3m(frame: pd.DataFrame) -> pd.DataFrame:
        aggregation = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
        }
        if "volume" in frame.columns:
            aggregation["volume"] = "sum"
        return frame.resample("3min").agg(aggregation).dropna(subset=["open", "high", "low", "close"])

    @staticmethod
    def _resample_4h(frame: pd.DataFrame) -> pd.DataFrame:
        aggregation = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
        }
        if "volume" in frame.columns:
            aggregation["volume"] = "sum"
        return frame.resample("4h").agg(aggregation).dropna(subset=["open", "high", "low", "close"])
