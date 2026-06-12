from __future__ import annotations

from xau_signal_bot.services.models import Direction, IndicatorSnapshot, SourceResult


class RegimeAlignmentService:
    name = "Regime Alignment"

    def analyze(self, snapshots: dict[str, IndicatorSnapshot | None]) -> SourceResult:
        h4 = snapshots.get("4h")
        h1 = snapshots.get("1h")
        m15 = snapshots.get("15m")
        if not h4 or not h1:
            return SourceResult.unavailable(self.name, "Need H4 and H1 indicator snapshots for regime alignment")

        biases = {
            "H4": self._higher_timeframe_bias(h4),
            "H1": self._trend_bias(h1),
            "M15": self._timing_bias(m15) if m15 else Direction.NEUTRAL,
        }
        direction = self._direction(biases)
        confidence = self._confidence(direction, biases)
        summary = (
            f"H4 {biases['H4'].value}, H1 {biases['H1'].value}, "
            f"M15 {biases['M15'].value}"
        )
        if direction in {Direction.BULLISH, Direction.BEARISH}:
            summary = f"{direction.value} regime: {summary}"
        else:
            summary = f"No clean regime: {summary}"

        return SourceResult(
            name=self.name,
            ok=True,
            direction=direction,
            confidence=confidence,
            summary=summary,
            data={
                "timeframe_bias": {key: value.value for key, value in biases.items()},
                "rule": "H4 EMA50/EMA200 regime, H1 trend alignment, M15 timing confirmation",
            },
        )

    @staticmethod
    def _higher_timeframe_bias(snapshot: IndicatorSnapshot) -> Direction:
        if snapshot.ema50 > snapshot.ema200 and snapshot.price > snapshot.ema50:
            return Direction.BULLISH
        if snapshot.ema50 < snapshot.ema200 and snapshot.price < snapshot.ema50:
            return Direction.BEARISH
        return Direction.NEUTRAL

    @staticmethod
    def _trend_bias(snapshot: IndicatorSnapshot) -> Direction:
        if snapshot.price > snapshot.ema50 and snapshot.ema20 > snapshot.ema50:
            return Direction.BULLISH
        if snapshot.price < snapshot.ema50 and snapshot.ema20 < snapshot.ema50:
            return Direction.BEARISH
        return Direction.NEUTRAL

    @staticmethod
    def _timing_bias(snapshot: IndicatorSnapshot) -> Direction:
        if snapshot.trend_direction == snapshot.momentum_direction:
            return snapshot.trend_direction
        if snapshot.momentum_direction in {Direction.BULLISH, Direction.BEARISH}:
            return snapshot.momentum_direction
        return snapshot.trend_direction

    @staticmethod
    def _direction(biases: dict[str, Direction]) -> Direction:
        h4 = biases["H4"]
        h1 = biases["H1"]
        if h4 in {Direction.BULLISH, Direction.BEARISH} and h1 == h4:
            return h4
        return Direction.NEUTRAL

    @staticmethod
    def _confidence(direction: Direction, biases: dict[str, Direction]) -> float:
        if direction == Direction.NEUTRAL:
            if biases["H4"] in {Direction.BULLISH, Direction.BEARISH} and biases["H1"] == Direction.NEUTRAL:
                return 45.0
            return 25.0
        aligned = sum(value == direction for value in biases.values())
        if aligned == 3:
            return 90.0
        if aligned == 2:
            return 74.0
        return 55.0
