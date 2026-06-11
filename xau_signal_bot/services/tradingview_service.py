from __future__ import annotations

import asyncio
import time

import aiohttp

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.models import Direction, SourceResult
from xau_signal_bot.services.parsing import direction_from_text


class TradingViewService:
    name = "TradingView"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_technical_summary(self, session: aiohttp.ClientSession, timeframe: str) -> SourceResult:
        del session
        try:
            from tradingview_ta import Interval, TA_Handler
        except ImportError:
            return SourceResult.unavailable(
                self.name,
                "tradingview-ta is not installed. Install optional dependency or disable this source.",
            )

        interval_map = {
            "1m": Interval.INTERVAL_1_MINUTE,
            "3m": Interval.INTERVAL_5_MINUTES,
            "5m": Interval.INTERVAL_5_MINUTES,
        }
        used_interval = interval_map.get(timeframe, Interval.INTERVAL_5_MINUTES)

        def load_summary() -> SourceResult:
            last_error: Exception | None = None
            for _ in range(3):
                try:
                    handler = TA_Handler(
                        symbol=self.settings.tradingview_symbol,
                        screener=self.settings.tradingview_screener,
                        exchange=self.settings.tradingview_exchange,
                        interval=used_interval,
                    )
                    analysis = handler.get_analysis()
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    time.sleep(0.4)
            else:
                raise last_error or RuntimeError("TradingView request failed")
            summary = analysis.summary or {}
            recommendation = str(summary.get("RECOMMENDATION", "UNKNOWN"))
            direction = direction_from_text(recommendation)
            total = sum(int(summary.get(key, 0)) for key in ("BUY", "SELL", "NEUTRAL")) or 1
            confidence = round(max(int(summary.get("BUY", 0)), int(summary.get("SELL", 0))) / total * 100, 1)
            return SourceResult(
                name=self.name,
                ok=True,
                direction=direction,
                confidence=confidence,
                summary=recommendation.replace("_", " ").title()
                + (" (5m proxy for 3m)" if timeframe == "3m" else ""),
                data={
                    "summary": summary,
                    "timeframe": timeframe,
                    "used_timeframe": str(used_interval),
                    "indicators": analysis.indicators or {},
                },
            )

        try:
            return await asyncio.to_thread(load_summary)
        except Exception as exc:  # noqa: BLE001
            return SourceResult.unavailable(self.name, str(exc))
