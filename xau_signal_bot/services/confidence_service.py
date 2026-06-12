from __future__ import annotations

from xau_signal_bot.services.models import Decision, Direction, IndicatorSnapshot, SourceResult


class ConfidenceService:
    @staticmethod
    def label(score: int) -> str:
        if score < 50:
            return "No trade"
        if score < 65:
            return "Risky"
        if score < 75:
            return "Moderate"
        if score < 85:
            return "Strong"
        if score >= 95:
            return "Elite setup, not guaranteed"
        return "Very strong, not guaranteed"

    def score(
        self,
        decision: Decision,
        indicators: IndicatorSnapshot | None,
        sources: list[SourceResult],
        *,
        dangerous_news: bool,
    ) -> tuple[int, dict[str, int]]:
        if decision == Decision.NO_TRADE or indicators is None:
            candidate_direction = self._leading_direction(indicators, sources)
        else:
            candidate_direction = Direction.BULLISH if decision == Decision.LONG else Direction.BEARISH

        breakdown = {
            "technical_trend": self._technical_trend(candidate_direction, indicators),
            "momentum": self._momentum(candidate_direction, indicators),
            "support_resistance": self._support_resistance(candidate_direction, indicators),
            "candlesticks": self._source_quality("Japanese Candlesticks", candidate_direction, sources, 7),
            "futures_alignment": self._source_quality("Spot/Futures Alignment", candidate_direction, sources, 6),
            "macro_pressure": self._source_quality("USD/Yield Macro Pressure", candidate_direction, sources, 7),
            "regime_alignment": self._source_quality("Regime Alignment", candidate_direction, sources, 14),
            "multi_timeframe": self._source_quality("Multi-Timeframe Trend", candidate_direction, sources, 9),
            "ptj_overlay": self._source_quality("PTJ-Inspired Macro Overlay", candidate_direction, sources, 11),
            "book_playbook": self._source_quality("Book Playbook Score", candidate_direction, sources, 9),
            "proxy_microstructure": self._source_quality("Binance PAXG Proxy", candidate_direction, sources, 4),
            "open_news": self._source_quality("GDELT Open News", candidate_direction, sources, 4),
            "news_safety": 0 if dangerous_news else 3,
            "volatility": self._volatility(indicators),
            "external_agreement": self._external_agreement(candidate_direction, sources),
        }
        return min(100, sum(breakdown.values())), breakdown

    @staticmethod
    def _leading_direction(indicators: IndicatorSnapshot | None, sources: list[SourceResult]) -> Direction:
        if indicators and indicators.trend_direction in {Direction.BULLISH, Direction.BEARISH}:
            return indicators.trend_direction
        bullish = sum(source.direction == Direction.BULLISH for source in sources)
        bearish = sum(source.direction == Direction.BEARISH for source in sources)
        if bullish > bearish:
            return Direction.BULLISH
        if bearish > bullish:
            return Direction.BEARISH
        return Direction.NEUTRAL

    @staticmethod
    def _technical_trend(direction: Direction, indicators: IndicatorSnapshot | None) -> int:
        if not indicators or direction == Direction.NEUTRAL:
            return 0
        return 11 if indicators.trend_direction == direction else 0

    @staticmethod
    def _momentum(direction: Direction, indicators: IndicatorSnapshot | None) -> int:
        if not indicators or direction == Direction.NEUTRAL:
            return 0
        if indicators.momentum_direction == direction:
            return 5
        if indicators.momentum_direction == Direction.NEUTRAL:
            return 3
        return 0

    @staticmethod
    def _support_resistance(direction: Direction, indicators: IndicatorSnapshot | None) -> int:
        if not indicators or direction == Direction.NEUTRAL or indicators.atr14 <= 0:
            return 0
        if direction == Direction.BULLISH:
            room_to_resistance = indicators.resistance - indicators.price
            distance_from_support = indicators.price - indicators.support
            if room_to_resistance >= indicators.atr14 and distance_from_support <= 3 * indicators.atr14:
                return 5
            if room_to_resistance > 0:
                return 3
        if direction == Direction.BEARISH:
            room_to_support = indicators.price - indicators.support
            distance_from_resistance = indicators.resistance - indicators.price
            if room_to_support >= indicators.atr14 and distance_from_resistance <= 3 * indicators.atr14:
                return 5
            if room_to_support > 0:
                return 3
        return 0

    @staticmethod
    def _sentiment(direction: Direction, sources: list[SourceResult]) -> int:
        sentiment_sources = [source for source in sources if "sentiment" in source.name.lower() and source.ok]
        if not sentiment_sources or direction == Direction.NEUTRAL:
            return 0
        if any(source.direction == direction for source in sentiment_sources):
            return 10
        if all(source.direction == Direction.NEUTRAL for source in sentiment_sources):
            return 4
        return 0

    @staticmethod
    def _volatility(indicators: IndicatorSnapshot | None) -> int:
        if not indicators:
            return 0
        return 3 if indicators.volatility_quality == "Good" else 0

    @staticmethod
    def _external_agreement(direction: Direction, sources: list[SourceResult]) -> int:
        if direction == Direction.NEUTRAL:
            return 0
        directional = [
            source
            for source in sources
            if source.ok
            and source.name not in {
                "Internal Indicators",
                "PTJ-Inspired Macro Overlay",
                "Japanese Candlesticks",
                "Spot/Futures Alignment",
                "Book Playbook Score",
                "USD/Yield Macro Pressure",
                "Multi-Timeframe Trend",
                "Regime Alignment",
                "Binance PAXG Proxy",
                "GDELT Open News",
                "Data Quality Gate",
            }
            and source.direction in {Direction.BULLISH, Direction.BEARISH}
        ]
        if not directional:
            return 0
        matching = sum(source.direction == direction for source in directional)
        opposing = len(directional) - matching
        if matching >= 2 and opposing == 0:
            return 2
        if matching >= 1 and opposing == 0:
            return 1
        return 0

    @staticmethod
    def _source_quality(name: str, direction: Direction, sources: list[SourceResult], max_points: int) -> int:
        if direction == Direction.NEUTRAL:
            return 0
        source = next((item for item in sources if item.name == name and item.ok), None)
        if not source:
            return 0
        if source.direction == direction:
            confidence = float(source.confidence or 50)
            if confidence >= 80:
                return max_points
            if confidence >= 65:
                return max(1, round(max_points * 0.8))
            return max(1, round(max_points * 0.55))
        if source.direction == Direction.NEUTRAL:
            return max(0, round(max_points * 0.35))
        return 0
