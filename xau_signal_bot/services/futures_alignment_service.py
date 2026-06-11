from __future__ import annotations

import pandas as pd

from xau_signal_bot.services.models import Direction, MarketData, SourceResult


class FuturesAlignmentService:
    name = "Spot/Futures Alignment"

    def analyze(self, market_data: MarketData | None, sources: list[SourceResult]) -> SourceResult:
        if not market_data or market_data.candles is None or market_data.candles.empty:
            return SourceResult.unavailable(self.name, "No futures candle data available")

        swissquote = self._source_by_name("Swissquote XAU/USD", sources)
        yahoo = self._source_by_name("Yahoo Finance", sources)
        if not swissquote or not swissquote.ok or not yahoo or not yahoo.ok:
            return SourceResult.unavailable(self.name, "Spot quote and GC=F futures candles were not both available")

        candles = market_data.candles.copy()
        if "close" not in candles.columns:
            return SourceResult.unavailable(self.name, "Futures candles did not include close prices")
        close = pd.to_numeric(candles["close"], errors="coerce").dropna()
        if len(close) < 8:
            return SourceResult.unavailable(self.name, f"Need at least 8 futures candles, got {len(close)}")

        spot_price = float(swissquote.data.get("mid") or market_data.price)
        futures_price = float(close.iloc[-1])
        basis = spot_price - futures_price
        basis_pct = (basis / spot_price) * 100 if spot_price else 0.0
        momentum_pct = ((float(close.iloc[-1]) / float(close.iloc[-6])) - 1) * 100
        direction = self._direction(momentum_pct)
        basis_quality = abs(basis_pct) <= 0.4
        if not basis_quality:
            direction = Direction.NEUTRAL
            confidence = 30.0
        else:
            confidence = self._confidence(momentum_pct, basis_quality)

        if not basis_quality:
            summary = f"Futures vote skipped: wide spot/futures basis {basis_pct:+.2f}%, GC=F momentum {momentum_pct:+.2f}%"
        elif direction == Direction.NEUTRAL:
            summary = f"Futures momentum flat, basis {basis_pct:+.2f}%"
        else:
            summary = f"{direction.value}: GC=F momentum {momentum_pct:+.2f}%, basis {basis_pct:+.2f}%"

        return SourceResult(
            name=self.name,
            ok=True,
            direction=direction,
            confidence=confidence,
            summary=summary,
            data={
                "spot_price": spot_price,
                "futures_price": futures_price,
                "basis": basis,
                "basis_pct": basis_pct,
                "futures_momentum_pct": momentum_pct,
                "basis_quality": basis_quality,
            },
        )

    @staticmethod
    def _direction(momentum_pct: float) -> Direction:
        if momentum_pct >= 0.04:
            return Direction.BULLISH
        if momentum_pct <= -0.04:
            return Direction.BEARISH
        return Direction.NEUTRAL

    @staticmethod
    def _confidence(momentum_pct: float, basis_quality: bool) -> float:
        momentum_score = min(70.0, abs(momentum_pct) * 500)
        score = 25 + momentum_score
        if basis_quality:
            score += 10
        return round(min(90.0, score), 1)

    @staticmethod
    def _source_by_name(name: str, sources: list[SourceResult]) -> SourceResult | None:
        for source in sources:
            if source.name == name:
                return source
        return None
