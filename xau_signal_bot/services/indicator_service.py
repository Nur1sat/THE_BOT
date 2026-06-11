from __future__ import annotations

import numpy as np
import pandas as pd

from xau_signal_bot.services.models import Direction, IndicatorSnapshot, SourceResult


class IndicatorService:
    name = "Internal Indicators"

    def analyze(self, candles: pd.DataFrame) -> tuple[IndicatorSnapshot | None, SourceResult]:
        if candles is None or candles.empty:
            return None, SourceResult.unavailable(self.name, "No candle data available for internal indicators")
        frame = candles.copy()
        for column in ("open", "high", "low", "close"):
            if column not in frame.columns:
                return None, SourceResult.unavailable(self.name, f"Missing {column} column in candle data")
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["open", "high", "low", "close"])
        if len(frame) < 220:
            return None, SourceResult.unavailable(
                self.name,
                f"Need at least 220 candles for EMA 200 and indicators, got {len(frame)}",
            )

        close = frame["close"]
        high = frame["high"]
        low = frame["low"]
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        ema200 = close.ewm(span=200, adjust=False).mean()
        rsi14 = self._rsi(close, 14)
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        macd_signal = macd.ewm(span=9, adjust=False).mean()
        atr14 = self._atr(high, low, close, 14)
        middle = close.rolling(20).mean()
        std = close.rolling(20).std()
        upper = middle + (2 * std)
        lower = middle - (2 * std)
        support = low.tail(50).min()
        resistance = high.tail(50).max()

        latest_values = [
            close.iloc[-1],
            ema20.iloc[-1],
            ema50.iloc[-1],
            ema200.iloc[-1],
            rsi14.iloc[-1],
            macd.iloc[-1],
            macd_signal.iloc[-1],
            atr14.iloc[-1],
            upper.iloc[-1],
            middle.iloc[-1],
            lower.iloc[-1],
            support,
            resistance,
        ]
        if any(np.isnan(value) for value in latest_values):
            return None, SourceResult.unavailable(self.name, "Indicator calculation produced incomplete values")

        price = float(close.iloc[-1])
        snapshot = IndicatorSnapshot(
            price=price,
            ema20=float(ema20.iloc[-1]),
            ema50=float(ema50.iloc[-1]),
            ema200=float(ema200.iloc[-1]),
            rsi14=float(rsi14.iloc[-1]),
            macd=float(macd.iloc[-1]),
            macd_signal=float(macd_signal.iloc[-1]),
            atr14=float(atr14.iloc[-1]),
            bollinger_upper=float(upper.iloc[-1]),
            bollinger_middle=float(middle.iloc[-1]),
            bollinger_lower=float(lower.iloc[-1]),
            support=float(support),
            resistance=float(resistance),
            trend_direction=Direction.NEUTRAL,
            momentum_direction=Direction.NEUTRAL,
            volatility_quality="Unknown",
            atr_percent=0.0,
            reasons=[],
        )
        self._classify(snapshot)
        direction = self._combined_direction(snapshot)
        return (
            snapshot,
            SourceResult(
                name=self.name,
                ok=True,
                direction=direction,
                confidence=None,
                summary=direction.value,
                data=snapshot.to_dict(),
            ),
        )

    def from_tradingview_values(
        self,
        price: float,
        source: SourceResult,
    ) -> tuple[IndicatorSnapshot | None, SourceResult]:
        raw = source.data.get("indicators") or {}
        try:
            ema20 = self._pick_number(raw, "EMA20", "EMA20|15", "EMA20|60")
            ema50 = self._pick_number(raw, "EMA50", "EMA50|15", "EMA50|60")
            ema200 = self._pick_number(raw, "EMA200", "EMA200|15", "EMA200|60")
            rsi14 = self._pick_number(raw, "RSI", "RSI[1]")
            macd = self._pick_number(raw, "MACD.macd", "MACD")
            macd_signal = self._pick_number(raw, "MACD.signal")
        except (TypeError, ValueError):
            return None, SourceResult.unavailable(
                self.name,
                "TradingView did not provide enough indicator values for fallback analysis",
            )

        support = self._pick_optional_number(
            raw,
            float(price) * 0.995,
            "Pivot.M.Classic.S1",
            "Pivot.M.Fibonacci.S1",
            "Pivot.M.Camarilla.S1",
        )
        resistance = self._pick_optional_number(
            raw,
            float(price) * 1.005,
            "Pivot.M.Classic.R1",
            "Pivot.M.Fibonacci.R1",
            "Pivot.M.Camarilla.R1",
        )
        atr14 = self._pick_optional_number(
            raw,
            max((resistance - support) / 4, float(price) * 0.0015),
            "ATR",
            "ATR14",
        )
        bollinger_upper = self._pick_optional_number(raw, price + (2 * atr14), "BB.upper", "BB.upper|15", "BB.upper|60")
        bollinger_middle = self._pick_optional_number(raw, price, "BB.middle", "BB.basis", "BB.lower|15", "BB.lower|60")
        bollinger_lower = self._pick_optional_number(raw, price - (2 * atr14), "BB.lower", "BB.lower|15", "BB.lower|60")
        snapshot = IndicatorSnapshot(
            price=float(price),
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
            rsi14=rsi14,
            macd=macd,
            macd_signal=macd_signal,
            atr14=atr14,
            bollinger_upper=bollinger_upper,
            bollinger_middle=bollinger_middle,
            bollinger_lower=bollinger_lower,
            support=support,
            resistance=resistance,
            trend_direction=Direction.NEUTRAL,
            momentum_direction=Direction.NEUTRAL,
            volatility_quality="Unknown",
            atr_percent=0.0,
            reasons=[
                "TradingView indicator values used because OHLC candle source was unavailable",
                "ATR fallback estimated from TradingView pivot distance when ATR was not provided",
            ],
        )
        self._classify(snapshot)
        direction = self._combined_direction(snapshot)
        return (
            snapshot,
            SourceResult(
                name=self.name,
                ok=True,
                direction=direction,
                confidence=source.confidence,
                summary=f"{direction.value} (TradingView fallback)",
                data={**snapshot.to_dict(), "fallback_source": source.name},
            ),
        )

    @staticmethod
    def _pick_number(raw: dict, *keys: str) -> float:
        for key in keys:
            value = raw.get(key)
            if value is not None:
                return float(value)
        raise ValueError(f"Missing indicator value: {keys[0]}")

    @classmethod
    def _pick_optional_number(cls, raw: dict, default: float, *keys: str) -> float:
        try:
            return cls._pick_number(raw, *keys)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _rsi(close: pd.Series, period: int) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = -delta.clip(upper=0).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        previous_close = close.shift(1)
        true_range = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return true_range.rolling(period).mean()

    @staticmethod
    def _classify(snapshot: IndicatorSnapshot) -> None:
        if snapshot.price > snapshot.ema50 > snapshot.ema200 and snapshot.ema20 > snapshot.ema50:
            snapshot.trend_direction = Direction.BULLISH
            snapshot.reasons.append("Price is above EMA 50 and EMA 200")
        elif snapshot.price < snapshot.ema50 < snapshot.ema200 and snapshot.ema20 < snapshot.ema50:
            snapshot.trend_direction = Direction.BEARISH
            snapshot.reasons.append("Price is below EMA 50 and EMA 200")
        else:
            snapshot.trend_direction = Direction.NEUTRAL
            snapshot.reasons.append("EMA trend is mixed")

        if snapshot.macd > snapshot.macd_signal and snapshot.rsi14 < 72:
            snapshot.momentum_direction = Direction.BULLISH
            snapshot.reasons.append("MACD momentum is bullish and RSI is not extremely overbought")
        elif snapshot.macd < snapshot.macd_signal and snapshot.rsi14 > 28:
            snapshot.momentum_direction = Direction.BEARISH
            snapshot.reasons.append("MACD momentum is bearish and RSI is not extremely oversold")
        else:
            snapshot.momentum_direction = Direction.NEUTRAL
            snapshot.reasons.append("Momentum is unclear or stretched")

        snapshot.atr_percent = (snapshot.atr14 / snapshot.price) * 100
        if snapshot.atr_percent < 0.02:
            snapshot.volatility_quality = "Too quiet"
            snapshot.reasons.append("ATR is very low relative to price")
        elif snapshot.atr_percent > 0.8:
            snapshot.volatility_quality = "Too volatile"
            snapshot.reasons.append("ATR is high relative to price")
        else:
            snapshot.volatility_quality = "Good"
            snapshot.reasons.append("ATR volatility is within the configured quality range")

    @staticmethod
    def _combined_direction(snapshot: IndicatorSnapshot) -> Direction:
        if snapshot.trend_direction == snapshot.momentum_direction:
            return snapshot.trend_direction
        if snapshot.trend_direction in {Direction.BULLISH, Direction.BEARISH} and snapshot.momentum_direction == Direction.NEUTRAL:
            return snapshot.trend_direction
        return Direction.NEUTRAL
