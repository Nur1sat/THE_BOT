from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import datetime, timedelta, timezone

import aiohttp

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.binance_proxy_service import BinancePaxgProxyService
from xau_signal_bot.services.book_playbook_service import BookPlaybookService
from xau_signal_bot.services.candlestick_service import CandlestickService
from xau_signal_bot.services.confidence_service import ConfidenceService
from xau_signal_bot.services.data_quality_service import DataQualityService
from xau_signal_bot.services.fed_service import FedService
from xau_signal_bot.services.forexfactory_service import ForexFactoryService
from xau_signal_bot.services.futures_alignment_service import FuturesAlignmentService
from xau_signal_bot.services.fxstreet_service import FXStreetService
from xau_signal_bot.services.gdelt_service import GdeltService
from xau_signal_bot.services.indicator_service import IndicatorService
from xau_signal_bot.services.investing_service import InvestingService
from xau_signal_bot.services.macro_market_service import MacroMarketService
from xau_signal_bot.services.models import (
    CalendarEvent,
    Decision,
    Direction,
    MarketData,
    NewsItem,
    SignalResult,
    SourceResult,
    UserSignalSettings,
)
from xau_signal_bot.services.multi_timeframe_service import MultiTimeframeService
from xau_signal_bot.services.myfxbook_service import MyfxbookService
from xau_signal_bot.services.news_service import NewsService
from xau_signal_bot.services.parsing import parse_datetime
from xau_signal_bot.services.price_service import PriceService
from xau_signal_bot.services.regime_alignment_service import RegimeAlignmentService
from xau_signal_bot.services.risk_service import RiskService
from xau_signal_bot.services.tradingview_service import TradingViewService
from xau_signal_bot.services.tudor_style_service import TudorStyleService


class SignalService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.price_service = PriceService(settings)
        self.indicator_service = IndicatorService()
        self.confidence_service = ConfidenceService()
        self.risk_service = RiskService()
        self.tudor_style_service = TudorStyleService()
        self.candlestick_service = CandlestickService()
        self.futures_alignment_service = FuturesAlignmentService()
        self.book_playbook_service = BookPlaybookService()
        self.macro_market_service = MacroMarketService()
        self.multi_timeframe_service = MultiTimeframeService()
        self.regime_alignment_service = RegimeAlignmentService()
        self.binance_proxy_service = BinancePaxgProxyService(settings)
        self.data_quality_service = DataQualityService(settings.primary_quote_max_age_seconds)
        self._signal_cache: dict[str, tuple[datetime, SignalResult]] = {}

    async def analyze(self, user_settings: UserSignalSettings | None = None) -> SignalResult:
        prefs = user_settings or UserSignalSettings(
            timeframe=self.settings.default_timeframe,
            minimum_confidence=self.settings.default_minimum_confidence,
            risk_percentage=self.settings.default_risk_percentage,
            news_filter_enabled=self.settings.default_news_filter_enabled,
        )
        cache_key = self._cache_key(prefs)
        cached = self._get_cached_signal(cache_key)
        if cached:
            return cached

        timeout = aiohttp.ClientTimeout(total=self.settings.http_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            price_task = asyncio.create_task(self.price_service.collect_market_data(session, prefs.timeframe))
            external_tasks = [
                TradingViewService(self.settings).get_technical_summary(session, prefs.timeframe),
                self.macro_market_service.analyze(session),
                GdeltService(self.settings).get_gold_news(session),
                ForexFactoryService(self.settings).get_calendar(session),
                FXStreetService(self.settings).get_gold_news(session),
                FedService(self.settings).get_calendar(session),
            ]
            if self.settings.investing_technical_api_url:
                external_tasks.append(InvestingService(self.settings).get_technical_summary(session, prefs.timeframe))
            if self.settings.investing_calendar_api_url:
                external_tasks.append(InvestingService(self.settings).get_calendar(session))
            if self.settings.fxstreet_calendar_api_url:
                external_tasks.append(FXStreetService(self.settings).get_calendar(session))
            if self.settings.myfxbook_email and self.settings.myfxbook_password:
                external_tasks.append(MyfxbookService(self.settings).get_sentiment(session))
            if self.settings.news_api_key or self.settings.reuters_api_url:
                external_tasks.append(NewsService(self.settings).get_recent_news(session))
            external_tasks.extend(
                NewsService(self.settings).get_rss_source(session, url)
                for url in self.settings.news_rss_urls
            )
            external_task = asyncio.create_task(self._collect_sources(external_tasks))
            market_data, price_sources = await price_task
            source_results = list(price_sources)
            source_results.extend(await external_task)

            indicators = None
            if market_data and market_data.candles is not None:
                indicators, internal_source = self.indicator_service.analyze(market_data.candles)
                if indicators:
                    self._align_indicators_to_live_price(indicators, market_data.price)
                    internal_source.data = indicators.to_dict()
                source_results.append(internal_source)
            elif market_data:
                tradingview_source = self._source_by_name("TradingView", source_results)
                if tradingview_source and tradingview_source.ok:
                    indicators, internal_source = self.indicator_service.from_tradingview_values(
                        market_data.price,
                        tradingview_source,
                    )
                    if indicators:
                        self._align_indicators_to_live_price(indicators, market_data.price)
                        internal_source.data = indicators.to_dict()
                    source_results.append(internal_source)
                else:
                    source_results.append(SourceResult.unavailable("Internal Indicators", "No OHLC candle source was available"))
            else:
                source_results.append(SourceResult.unavailable("Internal Indicators", "No OHLC candle source was available"))

            if market_data and market_data.candles is not None:
                source_results.append(self.candlestick_service.analyze(market_data.candles))
            else:
                source_results.append(SourceResult.unavailable("Japanese Candlesticks", "No OHLC candle source was available"))
            source_results.append(self.futures_alignment_service.analyze(market_data, source_results))
            source_results.append(await self._multi_timeframe_source(session, prefs.timeframe, indicators))
            source_results.append(await self._regime_alignment_source(session))
            source_results.append(await self.binance_proxy_service.analyze(session, market_data.price if market_data else None))
            source_results.append(self.data_quality_service.analyze(market_data, source_results))

            calendar_events = self._calendar_events(source_results)
            news_items = self._news_items(source_results)
            tudor_overlay = self.tudor_style_service.analyze(
                indicators,
                source_results,
                calendar_events,
                news_items,
            )
            source_results.append(tudor_overlay)
            source_results.append(
                self.book_playbook_service.analyze(
                    indicators,
                    source_results,
                    calendar_events,
                    news_items,
                )
            )
            dangerous_events = self._dangerous_events(calendar_events)
            dangerous_news = bool(dangerous_events) and prefs.news_filter_enabled

            raw_decision, reasons = self._candidate_decision(indicators, source_results, market_data)
            if dangerous_news:
                raw_decision = Decision.NO_TRADE
                reasons.append("High-impact USD news is within the configured danger window")

            confidence, breakdown = self.confidence_service.score(
                raw_decision,
                indicators,
                source_results,
                dangerous_news=dangerous_news,
            )
            if raw_decision != Decision.NO_TRADE and confidence < prefs.minimum_confidence:
                reasons.append(
                    f"Confidence {confidence}/100 is below user minimum {prefs.minimum_confidence}/100"
                )
                raw_decision = Decision.NO_TRADE
            if raw_decision == Decision.NO_TRADE and confidence >= 65:
                confidence = 64

            risk = None
            if raw_decision != Decision.NO_TRADE and indicators and market_data:
                risk = self.risk_service.calculate(raw_decision, market_data.price, indicators.atr14)

            warnings = [
                "This is not financial advice. Trading is risky. Use your own analysis and risk management.",
                "No signal is guaranteed, even at high confidence.",
            ]
            if any(not source.ok for source in source_results):
                warnings.append("Some sources were unavailable and are shown in the source list.")
            visible_sources = self._visible_sources(source_results, market_data, indicators)
            if not any(not source.ok for source in visible_sources):
                warnings = [warning for warning in warnings if not warning.startswith("Some sources were unavailable")]

            reasons.extend(self._breakdown_reasons(breakdown))
            result = SignalResult(
                decision=raw_decision,
                confidence=confidence,
                confidence_label=self.confidence_service.label(confidence),
                reasons=self._dedupe(reasons),
                warnings=warnings,
                source_results=visible_sources,
                timeframe=prefs.timeframe,
                indicators=indicators,
                risk=risk,
                calendar_events=calendar_events,
                news_items=news_items,
            )
            self._signal_cache[cache_key] = (datetime.now(timezone.utc), result)
            return result

    async def current_price(self, timeframe: str = "5m") -> tuple[MarketData | None, list[SourceResult]]:
        timeout = aiohttp.ClientTimeout(total=self.settings.http_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            return await self.price_service.collect_market_data(session, timeframe)

    async def live_price(self) -> tuple[MarketData | None, list[SourceResult]]:
        timeout = aiohttp.ClientTimeout(total=self.settings.http_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            return await self.price_service.get_live_quote(session)

    async def calendar(self) -> tuple[list[CalendarEvent], list[SourceResult]]:
        timeout = aiohttp.ClientTimeout(total=self.settings.http_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = [
                ForexFactoryService(self.settings).get_calendar(session),
                FedService(self.settings).get_calendar(session),
            ]
            if self.settings.investing_calendar_api_url:
                tasks.append(InvestingService(self.settings).get_calendar(session))
            if self.settings.fxstreet_calendar_api_url:
                tasks.append(FXStreetService(self.settings).get_calendar(session))
            results = await self._collect_sources(tasks)
        return self._calendar_events(list(results)), list(results)

    async def sentiment(self) -> SourceResult:
        if not (self.settings.myfxbook_email and self.settings.myfxbook_password):
            return SourceResult.unavailable(
                "Trader Sentiment",
                "No no-token trader positioning source is configured; sentiment is skipped in Telegram-token-only mode.",
            )
        timeout = aiohttp.ClientTimeout(total=self.settings.http_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            return await MyfxbookService(self.settings).get_sentiment(session)

    async def sources(self, user_settings: UserSignalSettings | None = None) -> list[SourceResult]:
        return (await self.analyze(user_settings)).source_results

    async def _multi_timeframe_source(
        self,
        session: aiohttp.ClientSession,
        selected_timeframe: str,
        selected_indicators,
    ) -> SourceResult:
        context_timeframes = [selected_timeframe, "5m", "15m"]
        snapshots = {selected_timeframe: selected_indicators}
        tasks = {
            timeframe: asyncio.create_task(self._indicator_snapshot_for_timeframe(session, timeframe))
            for timeframe in context_timeframes
            if timeframe != selected_timeframe
        }
        for timeframe, task in tasks.items():
            try:
                snapshots[timeframe] = await asyncio.wait_for(task, timeout=self.settings.source_timeout_seconds)
            except Exception:
                snapshots[timeframe] = None
        return self.multi_timeframe_service.analyze(snapshots)

    async def _indicator_snapshot_for_timeframe(self, session: aiohttp.ClientSession, timeframe: str):
        market_data, _source = await self.price_service.yahoo.get_market_data(session, timeframe)
        if not market_data or market_data.candles is None:
            return None
        snapshot, _internal_source = self.indicator_service.analyze(market_data.candles)
        return snapshot

    async def _regime_alignment_source(self, session: aiohttp.ClientSession) -> SourceResult:
        timeframes = ("4h", "1h", "15m")
        tasks = {
            timeframe: asyncio.create_task(self._indicator_snapshot_for_timeframe(session, timeframe))
            for timeframe in timeframes
        }
        snapshots = {}
        for timeframe, task in tasks.items():
            try:
                snapshots[timeframe] = await asyncio.wait_for(task, timeout=self.settings.source_timeout_seconds)
            except Exception:
                snapshots[timeframe] = None
        return self.regime_alignment_service.analyze(snapshots)

    def _candidate_decision(
        self,
        indicators,
        sources: list[SourceResult],
        market_data: MarketData | None,
    ) -> tuple[Decision, list[str]]:
        reasons: list[str] = []
        if not market_data:
            return Decision.NO_TRADE, ["No current XAU/USD price source was available"]
        data_quality = self._source_by_name("Data Quality Gate", sources)
        if data_quality and data_quality.data.get("status") == "BAD":
            return Decision.NO_TRADE, [f"Data-quality gate blocked the setup: {data_quality.summary}"]
        if not indicators:
            return Decision.NO_TRADE, ["Internal indicators are unavailable, so the bot cannot validate a trade"]
        if indicators.volatility_quality != "Good":
            return Decision.NO_TRADE, [f"Volatility filter is {indicators.volatility_quality.lower()}"]

        internal_direction = self._source_direction("Internal Indicators", sources)
        trend_led_risk = False
        if internal_direction == Direction.BULLISH:
            candidate = Decision.LONG
            candidate_direction = Direction.BULLISH
        elif internal_direction == Direction.BEARISH:
            candidate = Decision.SHORT
            candidate_direction = Direction.BEARISH
        elif self.settings.tudor_risk_mode and indicators.trend_direction == Direction.BULLISH:
            candidate = Decision.LONG
            candidate_direction = Direction.BULLISH
            trend_led_risk = True
            reasons.append("PTJ risk mode: taking trend-led LONG even though momentum does not fully confirm")
        elif self.settings.tudor_risk_mode and indicators.trend_direction == Direction.BEARISH:
            candidate = Decision.SHORT
            candidate_direction = Direction.BEARISH
            trend_led_risk = True
            reasons.append("PTJ risk mode: taking trend-led SHORT even though momentum does not fully confirm")
        else:
            return Decision.NO_TRADE, ["Internal trend and momentum do not agree"]

        directional_sources = [
            source
            for source in sources
            if source.ok
            and source.name not in {"Internal Indicators", "PTJ-Inspired Macro Overlay"}
            and source.direction in {Direction.BULLISH, Direction.BEARISH}
        ]
        tudor_overlay = self._source_by_name("PTJ-Inspired Macro Overlay", sources)
        if not tudor_overlay or not tudor_overlay.ok or tudor_overlay.direction != candidate_direction:
            return Decision.NO_TRADE, ["PTJ-inspired macro overlay does not confirm the setup"]
        overlay_score = float(tudor_overlay.confidence or 0)
        if overlay_score < self.settings.tudor_min_overlay_score:
            return Decision.NO_TRADE, [
                f"PTJ-inspired macro/risk overlay score {overlay_score:.0f} is below required {self.settings.tudor_min_overlay_score}"
            ]
        tudor_checks = [
            f"PTJ overlay: {check}"
            for check in (tudor_overlay.data.get("checks", []) if tudor_overlay else [])[:4]
        ]
        support = [source for source in directional_sources if source.direction == candidate_direction]
        opposition = [source for source in directional_sources if source.direction != candidate_direction]
        hard_opposition = [source for source in opposition if not self._is_soft_directional_source(source)]
        soft_opposition = [source for source in opposition if self._is_soft_directional_source(source)]
        quality_conflicts = self._blocking_quality_conflicts(candidate_direction, sources)
        if quality_conflicts:
            names = ", ".join(f"{source.name} ({source.summary})" for source in quality_conflicts)
            return Decision.NO_TRADE, [
                f"Book-quality short-term filter: stand aside because strong confirmation conflicts with the setup: {names}",
                *tudor_checks,
            ]
        quality_support = self._quality_supporting_sources(candidate_direction, sources)
        if len(quality_support) < self.settings.min_quality_confirmations:
            names = ", ".join(source.name for source in quality_support) or "none"
            return Decision.NO_TRADE, [
                f"Confluence rule: only {len(quality_support)} quality confirmation(s) support {candidate.value}; "
                f"need {self.settings.min_quality_confirmations}. Supporting: {names}",
                *tudor_checks,
            ]

        if hard_opposition:
            names = ", ".join(source.name for source in hard_opposition)
            can_take_controlled_risk = (
                self.settings.tudor_risk_mode
                and overlay_score >= self.settings.tudor_min_overlay_score
                and (len(support) >= len(hard_opposition) or len(hard_opposition) <= 1)
            )
            if not can_take_controlled_risk:
                return Decision.NO_TRADE, [
                    f"PTJ-inspired capital preservation rule: stand aside because sources conflict with the setup: {names}",
                    *tudor_checks,
                ]
            reasons.append(
                f"PTJ risk mode: taking controlled {candidate.value} despite hard conflicting sources ({len(support)} support vs {len(hard_opposition)} oppose): {names}"
            )
        if soft_opposition:
            names = ", ".join(source.name for source in soft_opposition[:3])
            reasons.append(
                f"PTJ risk mode: treating headline/news conflict as soft risk, not a veto: {names}"
            )
        if not support:
            if self.settings.tudor_risk_mode and overlay_score >= self.settings.tudor_min_overlay_score:
                reasons.append(
                    f"PTJ risk mode: taking controlled {candidate.value} from internal trend + macro overlay even without a separate external directional confirmation"
                )
            else:
                return Decision.NO_TRADE, [
                    "PTJ-inspired conviction rule: no external directional source confirms the internal signal",
                    *tudor_checks,
                ]

        ok_count = sum(source.ok for source in sources)
        if ok_count < 5:
            return Decision.NO_TRADE, [
                f"PTJ-inspired confirmation rule: only {ok_count} source adapters returned data",
                *tudor_checks,
            ]

        if trend_led_risk:
            reasons.append(f"Dominant trend and PTJ overlay support {candidate.value}; momentum conflict is priced into confidence")
        else:
            reasons.append(f"Internal indicators and {len(support)} external source(s) support {candidate.value}")
        reasons.extend(tudor_checks)
        reasons.extend(indicators.reasons)
        return candidate, reasons

    async def _collect_sources(self, tasks: list[Awaitable[SourceResult]]) -> list[SourceResult]:
        semaphore = asyncio.Semaphore(max(1, self.settings.source_concurrency))

        async def run(task: Awaitable[SourceResult]) -> SourceResult:
            source_name = self._awaitable_source_name(task)
            async with semaphore:
                try:
                    return await asyncio.wait_for(task, timeout=self.settings.source_timeout_seconds)
                except Exception as exc:  # noqa: BLE001
                    return SourceResult.unavailable(source_name, str(exc) or "Source timed out")

        if not tasks:
            return []
        return list(await asyncio.gather(*(run(task) for task in tasks)))

    @staticmethod
    def _awaitable_source_name(task: Awaitable[SourceResult]) -> str:
        frame = getattr(task, "cr_frame", None)
        if frame:
            owner = frame.f_locals.get("self")
            name = getattr(owner, "name", None)
            if isinstance(name, str) and name:
                return name
        return "Timed out source"

    def _get_cached_signal(self, cache_key: str) -> SignalResult | None:
        cached = self._signal_cache.get(cache_key)
        if not cached:
            return None
        created_at, result = cached
        age = (datetime.now(timezone.utc) - created_at).total_seconds()
        if age <= self.settings.signal_cache_seconds:
            return result
        self._signal_cache.pop(cache_key, None)
        return None

    @staticmethod
    def _cache_key(settings: UserSignalSettings) -> str:
        return "|".join(
            [
                settings.timeframe,
                str(settings.minimum_confidence),
                str(settings.risk_percentage),
                str(settings.news_filter_enabled),
            ]
        )

    def _visible_sources(
        self,
        sources: list[SourceResult],
        market_data: MarketData | None,
        indicators,
    ) -> list[SourceResult]:
        if self.settings.show_failed_sources:
            return sources
        visible: list[SourceResult] = []
        for source in sources:
            if source.ok:
                visible.append(source)
            elif source.name in {"Yahoo Finance", "Stooq", "OANDA"} and market_data is None:
                visible.append(source)
            elif source.name == "Internal Indicators" and indicators is None:
                visible.append(source)
        return visible

    @staticmethod
    def _source_direction(name: str, sources: list[SourceResult]) -> Direction:
        for source in sources:
            if source.name == name:
                return source.direction
        return Direction.UNKNOWN

    @staticmethod
    def _source_by_name(name: str, sources: list[SourceResult]) -> SourceResult | None:
        for source in sources:
            if source.name == name:
                return source
        return None

    @staticmethod
    def _align_indicators_to_live_price(indicators, live_price: float) -> None:
        if live_price <= 0 or indicators.price <= 0:
            return
        offset = float(live_price) - float(indicators.price)
        if abs(offset / live_price) < 0.0001:
            return
        for field_name in (
            "price",
            "ema20",
            "ema50",
            "ema200",
            "bollinger_upper",
            "bollinger_middle",
            "bollinger_lower",
            "support",
            "resistance",
        ):
            setattr(indicators, field_name, float(getattr(indicators, field_name)) + offset)
        indicators.atr_percent = (indicators.atr14 / indicators.price) * 100
        indicators.reasons.append(
            f"Price levels aligned to live XAU/USD spot quote by {offset:+.2f}"
        )

    @staticmethod
    def _is_soft_directional_source(source: SourceResult) -> bool:
        name = source.name.lower()
        return bool(source.data.get("items")) or "news" in name or "analysis" in name or "proxy" in name or "paxg" in name

    @staticmethod
    def _blocking_quality_conflicts(direction: Direction, sources: list[SourceResult]) -> list[SourceResult]:
        thresholds = {
            "Japanese Candlesticks": 70,
            "Spot/Futures Alignment": 65,
            "USD/Yield Macro Pressure": 65,
            "Multi-Timeframe Trend": 67,
            "Regime Alignment": 70,
            "Book Playbook Score": 70,
        }
        return [
            source
            for source in sources
            if source.ok
            and source.name in thresholds
            and source.direction in {Direction.BULLISH, Direction.BEARISH}
            and source.direction != direction
            and float(source.confidence or 0) >= thresholds[source.name]
        ]

    @staticmethod
    def _quality_supporting_sources(direction: Direction, sources: list[SourceResult]) -> list[SourceResult]:
        thresholds = {
            "TradingView": 50,
            "Japanese Candlesticks": 55,
            "Spot/Futures Alignment": 55,
            "USD/Yield Macro Pressure": 55,
            "Multi-Timeframe Trend": 67,
            "Regime Alignment": 65,
            "PTJ-Inspired Macro Overlay": 55,
            "Book Playbook Score": 55,
            "GDELT Open News": 60,
            "Binance PAXG Proxy": 60,
        }
        return [
            source
            for source in sources
            if source.ok
            and source.name in thresholds
            and source.direction == direction
            and float(source.confidence or 0) >= thresholds[source.name]
        ]

    def _dangerous_events(self, events: list[CalendarEvent]) -> list[CalendarEvent]:
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(minutes=self.settings.dangerous_news_window_minutes)
        return [
            event
            for event in events
            if event.starts_at and now <= event.starts_at <= cutoff and event.impact.lower() == "high"
        ]

    @staticmethod
    def _calendar_events(sources: list[SourceResult]) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for source in sources:
            for raw in source.data.get("events", []):
                starts_at = parse_datetime(raw.get("starts_at"))
                events.append(
                    CalendarEvent(
                        title=str(raw.get("title") or "Economic event"),
                        currency=str(raw.get("currency") or "USD"),
                        impact=str(raw.get("impact") or "Unknown"),
                        starts_at=starts_at,
                        source=str(raw.get("source") or source.name),
                        url=raw.get("url"),
                    )
                )
        return sorted(events, key=lambda event: event.starts_at or datetime.max.replace(tzinfo=timezone.utc))

    @staticmethod
    def _news_items(sources: list[SourceResult]) -> list[NewsItem]:
        items: list[NewsItem] = []
        for source in sources:
            for raw in source.data.get("items", []):
                direction_value = raw.get("direction", Direction.NEUTRAL.value)
                try:
                    direction = Direction(direction_value)
                except ValueError:
                    direction = Direction.NEUTRAL
                items.append(
                    NewsItem(
                        title=str(raw.get("title") or ""),
                        source=str(raw.get("source") or source.name),
                        published_at=parse_datetime(raw.get("published_at")),
                        url=raw.get("url"),
                        direction=direction,
                    )
                )
        return items

    @staticmethod
    def _breakdown_reasons(breakdown: dict[str, int]) -> list[str]:
        return [
            f"Confidence breakdown: trend {breakdown['technical_trend']}/11, "
            f"momentum {breakdown['momentum']}/5, support/resistance {breakdown['support_resistance']}/5, "
            f"candlesticks {breakdown['candlesticks']}/7, futures {breakdown['futures_alignment']}/6, "
            f"USD/yields {breakdown['macro_pressure']}/7, regime {breakdown['regime_alignment']}/14, "
            f"multi-timeframe {breakdown['multi_timeframe']}/9, PTJ overlay {breakdown['ptj_overlay']}/11, "
            f"book playbook {breakdown['book_playbook']}/9, PAXG proxy {breakdown['proxy_microstructure']}/4, "
            f"GDELT news {breakdown['open_news']}/4, news safety {breakdown['news_safety']}/3, "
            f"volatility {breakdown['volatility']}/3, source agreement {breakdown['external_agreement']}/2"
        ]

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result
