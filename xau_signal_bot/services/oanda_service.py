from __future__ import annotations

from datetime import datetime, timezone

import aiohttp
import pandas as pd

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.http import fetch_json
from xau_signal_bot.services.models import Direction, MarketData, SourceResult


GRANULARITIES = {"1m": "M1", "3m": "M1", "5m": "M5"}


class OandaService:
    name = "OANDA"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        host = "api-fxpractice.oanda.com" if settings.oanda_environment == "practice" else "api-fxtrade.oanda.com"
        self.base_url = f"https://{host}/v3"

    def configured(self) -> bool:
        return bool(self.settings.oanda_api_token and self.settings.oanda_account_id)

    async def get_market_data(
        self,
        session: aiohttp.ClientSession,
        timeframe: str,
    ) -> tuple[MarketData | None, SourceResult]:
        if not self.configured():
            return None, SourceResult.unavailable(self.name, "OANDA_API_TOKEN and OANDA_ACCOUNT_ID are not configured")
        url = f"{self.base_url}/instruments/{self.settings.oanda_instrument}/candles"
        headers = {"Authorization": f"Bearer {self.settings.oanda_api_token}"}
        params = {
            "granularity": GRANULARITIES.get(timeframe, "M5"),
            "count": 900 if timeframe == "3m" else 300,
            "price": "M",
        }
        try:
            payload = await fetch_json(session, url, headers=headers, params=params)
            rows = []
            for candle in payload.get("candles", []):
                if not candle.get("complete"):
                    continue
                mid = candle.get("mid", {})
                rows.append(
                    {
                        "time": pd.to_datetime(candle["time"], utc=True),
                        "open": float(mid["o"]),
                        "high": float(mid["h"]),
                        "low": float(mid["l"]),
                        "close": float(mid["c"]),
                        "volume": float(candle.get("volume", 0)),
                    }
                )
            frame = pd.DataFrame(rows)
            if frame.empty:
                return None, SourceResult.unavailable(self.name, "OANDA returned no completed candles", url=url)
            frame = frame.set_index("time").sort_index()
            if timeframe == "3m":
                frame = self._resample_3m(frame)
                if frame.empty:
                    return None, SourceResult.unavailable(self.name, "OANDA returned no 3m candles after resampling", url=url)
            price = float(frame["close"].iloc[-1])
            return (
                MarketData(
                    source=self.name,
                    symbol=self.settings.oanda_instrument,
                    price=price,
                    candles=frame,
                    timestamp=datetime.now(timezone.utc),
                ),
                SourceResult(
                    name=self.name,
                    ok=True,
                    direction=Direction.NEUTRAL,
                    summary=f"OHLC data OK for {self.settings.oanda_instrument}" + (" (3m resampled)" if timeframe == "3m" else ""),
                    data={"instrument": self.settings.oanda_instrument, "timeframe": timeframe, "candles": len(frame)},
                    url=url,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return None, SourceResult.unavailable(self.name, str(exc), url=url)

    @staticmethod
    def _resample_3m(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.resample("3min").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        ).dropna(subset=["open", "high", "low", "close"])
