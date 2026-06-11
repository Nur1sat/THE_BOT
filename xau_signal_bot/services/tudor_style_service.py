from __future__ import annotations

from datetime import datetime, timedelta, timezone

from xau_signal_bot.services.models import CalendarEvent, Direction, IndicatorSnapshot, NewsItem, SourceResult


class TudorStyleService:
    """Paul Tudor Jones-inspired macro/risk overlay.

    This is not a claim to reproduce a private strategy. It codifies public,
    general principles often associated with discretionary macro trading:
    respect the big trend, look for asymmetric setups, avoid event risk, and
    protect capital when the tape is mixed.
    """

    name = "PTJ-Inspired Macro Overlay"

    def analyze(
        self,
        indicators: IndicatorSnapshot | None,
        sources: list[SourceResult],
        calendar_events: list[CalendarEvent],
        news_items: list[NewsItem],
    ) -> SourceResult:
        if not indicators:
            return SourceResult.unavailable(self.name, "No technical indicator snapshot available")

        candidate = self._candidate_direction(indicators)
        if candidate == Direction.NEUTRAL:
            return SourceResult(
                name=self.name,
                ok=True,
                direction=Direction.NEUTRAL,
                confidence=0,
                summary="Stand aside: macro trend and momentum are not aligned",
                data={"checks": ["Trend and momentum are mixed"]},
            )

        checks: list[str] = []
        score = 0

        trend_score, trend_reason = self._trend_score(candidate, indicators)
        score += trend_score
        checks.append(trend_reason)

        momentum_score, momentum_reason = self._momentum_score(candidate, indicators)
        score += momentum_score
        checks.append(momentum_reason)

        asymmetry_score, asymmetry_reason = self._asymmetry_score(candidate, indicators)
        score += asymmetry_score
        checks.append(asymmetry_reason)

        event_score, event_reason = self._event_risk_score(calendar_events)
        score += event_score
        checks.append(event_reason)

        source_score, source_reason = self._source_alignment_score(candidate, sources)
        score += source_score
        checks.append(source_reason)

        news_score, news_reason = self._news_score(candidate, news_items)
        score += news_score
        checks.append(news_reason)

        if score >= 75:
            direction = candidate
            summary = f"{candidate.value} macro setup, risk-on only with stops"
        elif score >= 55:
            direction = candidate
            summary = f"{candidate.value} bias, but conviction is moderate"
        elif score >= 45:
            direction = candidate
            summary = f"Speculative {candidate.value} bias, reduced-size risk only"
        else:
            direction = Direction.NEUTRAL
            summary = "Stand aside: setup does not meet macro/risk quality threshold"

        return SourceResult(
            name=self.name,
            ok=True,
            direction=direction,
            confidence=round(score, 1),
            summary=summary,
            data={
                "score": score,
                "candidate_direction": candidate.value,
                "checks": checks,
            },
        )

    @staticmethod
    def _candidate_direction(indicators: IndicatorSnapshot) -> Direction:
        if indicators.trend_direction == indicators.momentum_direction:
            return indicators.trend_direction
        if indicators.trend_direction in {Direction.BULLISH, Direction.BEARISH}:
            return indicators.trend_direction
        return Direction.NEUTRAL

    @staticmethod
    def _trend_score(direction: Direction, indicators: IndicatorSnapshot) -> tuple[int, str]:
        if direction == Direction.BULLISH and indicators.price > indicators.ema50 > indicators.ema200:
            return 25, "Major trend supports long: price is above EMA 50 and EMA 200"
        if direction == Direction.BEARISH and indicators.price < indicators.ema50 < indicators.ema200:
            return 25, "Major trend supports short: price is below EMA 50 and EMA 200"
        return 10, "Major trend is not fully aligned, size/conviction should stay low"

    @staticmethod
    def _momentum_score(direction: Direction, indicators: IndicatorSnapshot) -> tuple[int, str]:
        if direction == Direction.BULLISH and indicators.macd > indicators.macd_signal and indicators.rsi14 < 70:
            return 20, "Momentum supports long without extreme overbought RSI"
        if direction == Direction.BEARISH and indicators.macd < indicators.macd_signal and indicators.rsi14 > 30:
            return 20, "Momentum supports short without extreme oversold RSI"
        return 6, "Momentum is stretched or not clean"

    @staticmethod
    def _asymmetry_score(direction: Direction, indicators: IndicatorSnapshot) -> tuple[int, str]:
        if indicators.atr14 <= 0:
            return 0, "Asymmetry cannot be measured because ATR is unavailable"
        if direction == Direction.BULLISH:
            room = indicators.resistance - indicators.price
        else:
            room = indicators.price - indicators.support
        if room >= 2 * indicators.atr14:
            return 20, "Asymmetry is acceptable: nearby target room is at least 2 ATR"
        if room >= indicators.atr14:
            return 10, "Asymmetry is only moderate: target room is at least 1 ATR"
        return 0, "Asymmetry is poor: price is too close to the next barrier"

    @staticmethod
    def _event_risk_score(events: list[CalendarEvent]) -> tuple[int, str]:
        now = datetime.now(timezone.utc)
        danger_window = now + timedelta(minutes=90)
        dangerous = [
            event
            for event in events
            if event.starts_at and now <= event.starts_at <= danger_window and event.impact.lower() == "high"
        ]
        if dangerous:
            names = ", ".join(event.title for event in dangerous[:2])
            return 0, f"Event risk is high soon: {names}"
        return 15, "No high-impact USD event inside the 90-minute macro danger window"

    @staticmethod
    def _source_alignment_score(direction: Direction, sources: list[SourceResult]) -> tuple[int, str]:
        directional = [
            source
            for source in sources
            if source.ok and source.name not in {"Internal Indicators", "PTJ-Inspired Macro Overlay"}
            and source.direction in {Direction.BULLISH, Direction.BEARISH}
        ]
        if not directional:
            return 0, "External source alignment is not directional"
        matching = [source for source in directional if source.direction == direction]
        opposing = [source for source in directional if source.direction != direction]
        if opposing:
            names = ", ".join(source.name for source in opposing[:3])
            return 0, f"External tape conflicts with the setup: {names}"
        if len(matching) >= 2:
            return 10, "External tape confirms the setup across multiple sources"
        return 5, "External tape has one confirming source"

    @staticmethod
    def _news_score(direction: Direction, news_items: list[NewsItem]) -> tuple[int, str]:
        directional = [item for item in news_items if item.direction in {Direction.BULLISH, Direction.BEARISH}]
        if not directional:
            return 5, "News tape is not strongly directional"
        matching = sum(item.direction == direction for item in directional)
        opposing = len(directional) - matching
        if opposing > matching:
            return 0, "News tape leans against the setup"
        if matching > opposing:
            return 10, "News tape leans with the setup"
        return 5, "News tape is mixed"
