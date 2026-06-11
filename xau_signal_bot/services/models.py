from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import pandas as pd


class Direction(str, Enum):
    BULLISH = "Bullish"
    BEARISH = "Bearish"
    NEUTRAL = "Neutral"
    UNKNOWN = "Unknown"


class Decision(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO TRADE"


@dataclass(slots=True)
class SourceResult:
    name: str
    ok: bool
    direction: Direction = Direction.UNKNOWN
    confidence: float | None = None
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    url: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def unavailable(cls, name: str, reason: str, url: str | None = None) -> "SourceResult":
        return cls(name=name, ok=False, summary="Unavailable", error=reason, url=url)

    def status_text(self) -> str:
        if not self.ok:
            return "unavailable"
        if self.direction in {Direction.BULLISH, Direction.BEARISH}:
            return self.direction.value
        return self.summary or "OK"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "direction": self.direction.value,
            "confidence": self.confidence,
            "summary": self.summary,
            "data": self.data,
            "error": self.error,
            "url": self.url,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(slots=True)
class CalendarEvent:
    title: str
    currency: str
    impact: str
    starts_at: datetime | None
    source: str
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "currency": self.currency,
            "impact": self.impact,
            "starts_at": self.starts_at.isoformat() if self.starts_at else None,
            "source": self.source,
            "url": self.url,
        }


@dataclass(slots=True)
class NewsItem:
    title: str
    source: str
    published_at: datetime | None = None
    url: str | None = None
    direction: Direction = Direction.NEUTRAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "source": self.source,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "url": self.url,
            "direction": self.direction.value,
        }


@dataclass(slots=True)
class MarketData:
    source: str
    symbol: str
    price: float
    candles: pd.DataFrame | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class IndicatorSnapshot:
    price: float
    ema20: float
    ema50: float
    ema200: float
    rsi14: float
    macd: float
    macd_signal: float
    atr14: float
    bollinger_upper: float
    bollinger_middle: float
    bollinger_lower: float
    support: float
    resistance: float
    trend_direction: Direction
    momentum_direction: Direction
    volatility_quality: str
    atr_percent: float
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": self.price,
            "ema20": self.ema20,
            "ema50": self.ema50,
            "ema200": self.ema200,
            "rsi14": self.rsi14,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "atr14": self.atr14,
            "bollinger_upper": self.bollinger_upper,
            "bollinger_middle": self.bollinger_middle,
            "bollinger_lower": self.bollinger_lower,
            "support": self.support,
            "resistance": self.resistance,
            "trend_direction": self.trend_direction.value,
            "momentum_direction": self.momentum_direction.value,
            "volatility_quality": self.volatility_quality,
            "atr_percent": self.atr_percent,
            "reasons": self.reasons,
        }


@dataclass(slots=True)
class UserSignalSettings:
    timeframe: str = "5m"
    minimum_confidence: int = 65
    alerts_enabled: bool = True
    risk_percentage: float = 1.0
    news_filter_enabled: bool = True


@dataclass(slots=True)
class RiskPlan:
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    take_profit_3: float | None
    risk_reward: str
    risk_per_unit: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit_1": self.take_profit_1,
            "take_profit_2": self.take_profit_2,
            "take_profit_3": self.take_profit_3,
            "risk_reward": self.risk_reward,
            "risk_per_unit": self.risk_per_unit,
        }


@dataclass(slots=True)
class SignalResult:
    decision: Decision
    confidence: int
    confidence_label: str
    reasons: list[str]
    warnings: list[str]
    source_results: list[SourceResult]
    timeframe: str = "5m"
    indicators: IndicatorSnapshot | None = None
    risk: RiskPlan | None = None
    calendar_events: list[CalendarEvent] = field(default_factory=list)
    news_items: list[NewsItem] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def source_statuses(self) -> dict[str, str]:
        return {source.name: source.status_text() for source in self.source_results}

    def to_record(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "confidence": self.confidence,
            "confidence_label": self.confidence_label,
            "timeframe": self.timeframe,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "indicators": self.indicators.to_dict() if self.indicators else None,
            "risk": self.risk.to_dict() if self.risk else None,
            "calendar_events": [event.to_dict() for event in self.calendar_events],
            "news_items": [item.to_dict() for item in self.news_items],
            "created_at": self.created_at.isoformat(),
        }
