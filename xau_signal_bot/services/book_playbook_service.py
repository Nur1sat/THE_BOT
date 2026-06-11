from __future__ import annotations

from datetime import datetime, timedelta, timezone

from xau_signal_bot.services.models import CalendarEvent, Direction, IndicatorSnapshot, NewsItem, SourceResult


class BookPlaybookService:
    name = "Book Playbook Score"

    def analyze(
        self,
        indicators: IndicatorSnapshot | None,
        sources: list[SourceResult],
        calendar_events: list[CalendarEvent],
        news_items: list[NewsItem],
    ) -> SourceResult:
        if not indicators:
            return SourceResult.unavailable(self.name, "No indicator snapshot available")

        direction = self._candidate_direction(indicators)
        if direction == Direction.NEUTRAL:
            return SourceResult(
                name=self.name,
                ok=True,
                direction=Direction.NEUTRAL,
                confidence=25,
                summary="No book-quality setup: technical direction is mixed",
                data={"checks": ["Technical Analysis: trend direction is mixed"]},
            )

        checks: list[str] = []
        score = 0

        points, text = self._psychology_check(indicators)
        score += points
        checks.append(f"Trading in the Zone: {text}")

        points, text = self._macro_check(calendar_events, news_items, sources, direction)
        score += points
        checks.append(f"Currency Market Macro: {text}")

        points, text = self._technical_check(indicators, direction)
        score += points
        checks.append(f"Technical Analysis: {text}")

        points, text = self._gold_check(sources, direction)
        score += points
        checks.append(f"Gold Trading Boot Camp: {text}")

        points, text = self._market_wizards_check(indicators, direction)
        score += points
        checks.append(f"Market Wizards: {text}")

        result_direction = direction if score >= 55 else Direction.NEUTRAL
        if score >= 90:
            summary = f"Elite {direction.value} setup; still not guaranteed"
        elif score >= 75:
            summary = f"Professional-quality {direction.value} setup"
        elif score >= 55:
            summary = f"Actionable {direction.value} setup with risk controls"
        else:
            summary = "No book-quality setup"

        return SourceResult(
            name=self.name,
            ok=True,
            direction=result_direction,
            confidence=round(score, 1),
            summary=summary,
            data={
                "score": score,
                "candidate_direction": direction.value,
                "checks": checks,
            },
        )

    @staticmethod
    def _candidate_direction(indicators: IndicatorSnapshot) -> Direction:
        if indicators.trend_direction in {Direction.BULLISH, Direction.BEARISH}:
            return indicators.trend_direction
        return Direction.NEUTRAL

    @staticmethod
    def _psychology_check(indicators: IndicatorSnapshot) -> tuple[int, str]:
        if indicators.atr14 <= 0:
            return 0, "ATR unavailable, so risk cannot be defined before entry"
        distance_from_ema20 = abs(indicators.price - indicators.ema20)
        if indicators.volatility_quality != "Good":
            return 4, f"stand aside because volatility is {indicators.volatility_quality.lower()}"
        if distance_from_ema20 > 1.4 * indicators.atr14:
            return 8, "price is extended from EMA20; no-chase discipline reduces conviction"
        return 20, "entry is not a chase and risk can be defined before entry"

    @staticmethod
    def _macro_check(
        events: list[CalendarEvent],
        news_items: list[NewsItem],
        sources: list[SourceResult],
        direction: Direction,
    ) -> tuple[int, str]:
        now = datetime.now(timezone.utc)
        danger_window = now + timedelta(minutes=90)
        dangerous = [
            event
            for event in events
            if event.starts_at and now <= event.starts_at <= danger_window and event.impact.lower() == "high"
        ]
        if dangerous:
            return 0, f"high-impact USD event is too close: {dangerous[0].title}"

        macro = BookPlaybookService._source_by_name("USD/Yield Macro Pressure", sources)
        if macro and macro.ok:
            if macro.direction == direction:
                return 20, f"USD/yield pressure confirms the setup: {macro.summary}"
            if macro.direction in {Direction.BULLISH, Direction.BEARISH}:
                return 4, f"USD/yield pressure opposes the setup: {macro.summary}"

        directional_news = [item for item in news_items if item.direction in {Direction.BULLISH, Direction.BEARISH}]
        if not directional_news:
            return 14, "no strong macro headline conflict found"
        with_setup = sum(item.direction == direction for item in directional_news)
        against_setup = len(directional_news) - with_setup
        if against_setup > with_setup:
            return 8, "headline tape leans against the setup, so size should stay smaller"
        if with_setup > against_setup:
            return 20, "headline tape leans with the setup"
        return 14, "headline tape is mixed, not a hard veto"

    @staticmethod
    def _technical_check(indicators: IndicatorSnapshot, direction: Direction) -> tuple[int, str]:
        trend_ok = indicators.trend_direction == direction
        momentum_ok = indicators.momentum_direction in {direction, Direction.NEUTRAL}
        if trend_ok and indicators.momentum_direction == direction:
            return 20, "trend and momentum align"
        if trend_ok and momentum_ok:
            return 13, "dominant trend is clear, but momentum is imperfect"
        return 4, "trend and momentum conflict"

    @staticmethod
    def _gold_check(sources: list[SourceResult], direction: Direction) -> tuple[int, str]:
        futures = BookPlaybookService._source_by_name("Spot/Futures Alignment", sources)
        candles = BookPlaybookService._source_by_name("Japanese Candlesticks", sources)
        points = 0
        notes: list[str] = []
        if futures and futures.ok:
            if futures.direction == direction:
                points += 10
                notes.append("GC=F futures agree with spot setup")
            elif futures.direction == Direction.NEUTRAL:
                points += 5
                notes.append("GC=F futures are flat")
            else:
                notes.append("GC=F futures oppose the setup")
        if candles and candles.ok:
            if candles.direction == direction:
                points += 10
                notes.append("Japanese candlesticks confirm the setup")
            elif candles.direction == Direction.NEUTRAL:
                points += 5
                notes.append("Japanese candlesticks are mixed")
            else:
                notes.append("Japanese candlesticks oppose the setup")
        if not notes:
            return 4, "gold-specific confirmation sources are unavailable"
        return points, "; ".join(notes)

    @staticmethod
    def _market_wizards_check(indicators: IndicatorSnapshot, direction: Direction) -> tuple[int, str]:
        if indicators.atr14 <= 0:
            return 0, "cannot measure asymmetry without ATR"
        if direction == Direction.BULLISH:
            room = indicators.resistance - indicators.price
        else:
            room = indicators.price - indicators.support
        if room >= 2 * indicators.atr14:
            return 20, "reward room is at least 2 ATR before the next level"
        if room >= indicators.atr14:
            return 12, "reward room is at least 1 ATR but not ideal"
        return 4, "reward room is tight, so survival/risk control matters more than prediction"

    @staticmethod
    def _source_by_name(name: str, sources: list[SourceResult]) -> SourceResult | None:
        for source in sources:
            if source.name == name:
                return source
        return None
