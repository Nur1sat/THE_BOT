from __future__ import annotations

import pandas as pd

from xau_signal_bot.services.models import Direction, SourceResult


class CandlestickService:
    name = "Japanese Candlesticks"

    def analyze(self, candles: pd.DataFrame | None) -> SourceResult:
        if candles is None or candles.empty:
            return SourceResult.unavailable(self.name, "No OHLC candles available for candlestick analysis")

        frame = candles.copy()
        for column in ("open", "high", "low", "close"):
            if column not in frame.columns:
                return SourceResult.unavailable(self.name, f"Missing {column} column")
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["open", "high", "low", "close"])
        if len(frame) < 5:
            return SourceResult.unavailable(self.name, f"Need at least 5 candles, got {len(frame)}")

        recent = frame.tail(5)
        previous = recent.iloc[-2]
        latest = recent.iloc[-1]
        pattern, direction, score, reason = self._best_pattern(recent, previous, latest)

        return SourceResult(
            name=self.name,
            ok=True,
            direction=direction,
            confidence=score,
            summary=f"{pattern}: {direction.value}",
            data={
                "pattern": pattern,
                "score": score,
                "reason": reason,
                "latest": {
                    "open": float(latest["open"]),
                    "high": float(latest["high"]),
                    "low": float(latest["low"]),
                    "close": float(latest["close"]),
                },
            },
        )

    def _best_pattern(
        self,
        recent: pd.DataFrame,
        previous: pd.Series,
        latest: pd.Series,
    ) -> tuple[str, Direction, float, str]:
        candidates = [
            self._engulfing(previous, latest),
            self._pin_bar(recent, latest),
            self._three_candle_push(recent),
            self._body_pressure(recent),
        ]
        return max(candidates, key=lambda item: item[2])

    def _engulfing(self, previous: pd.Series, latest: pd.Series) -> tuple[str, Direction, float, str]:
        prev_open, prev_close = float(previous["open"]), float(previous["close"])
        open_, close = float(latest["open"]), float(latest["close"])
        if prev_close < prev_open and close > open_ and close >= prev_open and open_ <= prev_close:
            return "Bullish engulfing", Direction.BULLISH, 82, "Latest candle fully reversed the previous bearish body"
        if prev_close > prev_open and close < open_ and close <= prev_open and open_ >= prev_close:
            return "Bearish engulfing", Direction.BEARISH, 82, "Latest candle fully reversed the previous bullish body"
        return "No engulfing pattern", Direction.NEUTRAL, 0, "No engulfing candle on the latest bar"

    def _pin_bar(self, recent: pd.DataFrame, latest: pd.Series) -> tuple[str, Direction, float, str]:
        open_, high, low, close = (float(latest[key]) for key in ("open", "high", "low", "close"))
        body = abs(close - open_)
        candle_range = max(high - low, 0.0001)
        upper_wick = high - max(open_, close)
        lower_wick = min(open_, close) - low
        prior_move = float(recent["close"].iloc[-2] - recent["close"].iloc[0])

        if lower_wick >= max(2.0 * body, 0.45 * candle_range) and upper_wick <= 0.3 * candle_range:
            score = 76 if prior_move < 0 else 62
            return "Bullish hammer / pin bar", Direction.BULLISH, score, "Long lower wick shows rejection of lower prices"
        if upper_wick >= max(2.0 * body, 0.45 * candle_range) and lower_wick <= 0.3 * candle_range:
            score = 76 if prior_move > 0 else 62
            return "Bearish shooting star / pin bar", Direction.BEARISH, score, "Long upper wick shows rejection of higher prices"
        return "No pin bar", Direction.NEUTRAL, 0, "No high-quality wick rejection on the latest candle"

    @staticmethod
    def _three_candle_push(recent: pd.DataFrame) -> tuple[str, Direction, float, str]:
        last3 = recent.tail(3)
        bullish = all(float(row["close"]) > float(row["open"]) for _, row in last3.iterrows())
        bearish = all(float(row["close"]) < float(row["open"]) for _, row in last3.iterrows())
        higher_closes = last3["close"].is_monotonic_increasing
        lower_closes = last3["close"].is_monotonic_decreasing
        if bullish and higher_closes:
            return "Three-candle bullish push", Direction.BULLISH, 68, "Last three candles closed higher with bullish bodies"
        if bearish and lower_closes:
            return "Three-candle bearish push", Direction.BEARISH, 68, "Last three candles closed lower with bearish bodies"
        return "No three-candle push", Direction.NEUTRAL, 0, "No clean three-candle continuation pattern"

    @staticmethod
    def _body_pressure(recent: pd.DataFrame) -> tuple[str, Direction, float, str]:
        closes = recent["close"].astype(float)
        opens = recent["open"].astype(float)
        net_body = float((closes - opens).tail(3).sum())
        average_range = float((recent["high"].astype(float) - recent["low"].astype(float)).tail(3).mean())
        if average_range <= 0:
            return "Flat candles", Direction.NEUTRAL, 0, "Recent candle ranges are too small to classify"
        if net_body > 0.6 * average_range:
            return "Bullish candle pressure", Direction.BULLISH, 54, "Recent candle bodies lean bullish"
        if net_body < -0.6 * average_range:
            return "Bearish candle pressure", Direction.BEARISH, 54, "Recent candle bodies lean bearish"
        return "Mixed candles", Direction.NEUTRAL, 35, "Recent candlesticks are mixed"
