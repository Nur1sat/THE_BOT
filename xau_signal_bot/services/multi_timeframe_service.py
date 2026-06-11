from __future__ import annotations

from xau_signal_bot.services.models import Direction, IndicatorSnapshot, SourceResult


class MultiTimeframeService:
    name = "Multi-Timeframe Trend"

    def analyze(self, snapshots: dict[str, IndicatorSnapshot | None]) -> SourceResult:
        usable = {timeframe: item for timeframe, item in snapshots.items() if item is not None}
        if len(usable) < 2:
            return SourceResult.unavailable(self.name, "Need at least two timeframes for confluence")

        trend_votes = [
            item.trend_direction
            for item in usable.values()
            if item.trend_direction in {Direction.BULLISH, Direction.BEARISH}
        ]
        if not trend_votes:
            return SourceResult(
                name=self.name,
                ok=True,
                direction=Direction.NEUTRAL,
                confidence=25,
                summary="No clear trend across timeframes",
                data=self._payload(usable),
            )

        bullish = trend_votes.count(Direction.BULLISH)
        bearish = trend_votes.count(Direction.BEARISH)
        if bullish > bearish:
            direction = Direction.BULLISH
            aligned = bullish
        elif bearish > bullish:
            direction = Direction.BEARISH
            aligned = bearish
        else:
            direction = Direction.NEUTRAL
            aligned = max(bullish, bearish)

        total = len(usable)
        confidence = round((aligned / total) * 100, 1)
        if direction == Direction.NEUTRAL:
            summary = f"Mixed trend across {total} timeframes"
        else:
            summary = f"{direction.value}: {aligned}/{total} timeframes align"

        return SourceResult(
            name=self.name,
            ok=True,
            direction=direction,
            confidence=confidence,
            summary=summary,
            data=self._payload(usable),
        )

    @staticmethod
    def _payload(snapshots: dict[str, IndicatorSnapshot]) -> dict[str, object]:
        return {
            timeframe: {
                "trend": snapshot.trend_direction.value,
                "momentum": snapshot.momentum_direction.value,
                "price": snapshot.price,
                "ema50": snapshot.ema50,
                "ema200": snapshot.ema200,
            }
            for timeframe, snapshot in snapshots.items()
        }
