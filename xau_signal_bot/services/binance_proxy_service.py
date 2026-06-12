from __future__ import annotations

import asyncio

import aiohttp

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.http import fetch_json
from xau_signal_bot.services.models import Direction, SourceResult


class BinancePaxgProxyService:
    name = "Binance PAXG Proxy"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def analyze(self, session: aiohttp.ClientSession, spot_price: float | None) -> SourceResult:
        if not spot_price or spot_price <= 0:
            return SourceResult.unavailable(self.name, "No spot XAU/USD price for proxy basis normalization")

        symbol = self.settings.binance_paxg_symbol
        base_url = self.settings.binance_api_base_url.rstrip("/")
        try:
            ticker_task = asyncio.create_task(
                fetch_json(session, f"{base_url}/api/v3/ticker/price", params={"symbol": symbol})
            )
            depth_task = asyncio.create_task(
                fetch_json(session, f"{base_url}/api/v3/depth", params={"symbol": symbol, "limit": "20"})
            )
            trades_task = asyncio.create_task(
                fetch_json(session, f"{base_url}/api/v3/aggTrades", params={"symbol": symbol, "limit": "100"})
            )
            ticker, depth, trades = await asyncio.gather(ticker_task, depth_task, trades_task)
        except Exception as exc:  # noqa: BLE001
            return SourceResult.unavailable(self.name, str(exc), url=base_url)

        try:
            proxy_price = float(ticker["price"])
            basis_pct = ((proxy_price - float(spot_price)) / float(spot_price)) * 100
            basis_quality = abs(basis_pct) <= self.settings.proxy_max_basis_pct
            imbalance = self._book_imbalance(depth)
            trade_pressure = self._trade_pressure(trades)
        except Exception as exc:  # noqa: BLE001
            return SourceResult.unavailable(self.name, f"Malformed Binance proxy payload: {exc}", url=base_url)

        if not basis_quality:
            direction = Direction.NEUTRAL
            confidence = 25.0
            summary = (
                f"Proxy ignored: PAXG/USDT basis {basis_pct:+.2f}% exceeds "
                f"{self.settings.proxy_max_basis_pct:.2f}% tolerance"
            )
        else:
            direction = self._direction(imbalance, trade_pressure)
            confidence = self._confidence(direction, imbalance, trade_pressure)
            summary = (
                f"{direction.value}: book imbalance {imbalance:+.2f}, "
                f"trade pressure {trade_pressure:+.2f}, basis {basis_pct:+.2f}%"
            )

        return SourceResult(
            name=self.name,
            ok=True,
            direction=direction,
            confidence=confidence,
            summary=summary,
            data={
                "symbol": symbol,
                "proxy_price": proxy_price,
                "spot_price": float(spot_price),
                "basis_pct": basis_pct,
                "basis_quality": basis_quality,
                "orderbook_imbalance": imbalance,
                "trade_pressure": trade_pressure,
                "note": "PAXG/USDT is tokenized-gold microstructure proxy only, not true OTC XAU/USD spot.",
            },
            url=f"{base_url}/api/v3/depth?symbol={symbol}&limit=20",
        )

    @staticmethod
    def _book_imbalance(depth: dict) -> float:
        bid_notional = sum(float(price) * float(size) for price, size in depth.get("bids", [])[:20])
        ask_notional = sum(float(price) * float(size) for price, size in depth.get("asks", [])[:20])
        total = bid_notional + ask_notional
        if total <= 0:
            return 0.0
        return round((bid_notional - ask_notional) / total, 4)

    @staticmethod
    def _trade_pressure(trades: list[dict]) -> float:
        buy_notional = 0.0
        sell_notional = 0.0
        for trade in trades:
            notional = float(trade.get("p") or 0) * float(trade.get("q") or 0)
            if trade.get("m"):
                sell_notional += notional
            else:
                buy_notional += notional
        total = buy_notional + sell_notional
        if total <= 0:
            return 0.0
        return round((buy_notional - sell_notional) / total, 4)

    @staticmethod
    def _direction(imbalance: float, trade_pressure: float) -> Direction:
        if imbalance >= 0.08 and trade_pressure >= -0.05:
            return Direction.BULLISH
        if imbalance <= -0.08 and trade_pressure <= 0.05:
            return Direction.BEARISH
        return Direction.NEUTRAL

    @staticmethod
    def _confidence(direction: Direction, imbalance: float, trade_pressure: float) -> float:
        if direction == Direction.NEUTRAL:
            return 40.0
        score = 48 + min(14, abs(imbalance) * 100) + min(8, abs(trade_pressure) * 60)
        return round(min(70.0, score), 1)
