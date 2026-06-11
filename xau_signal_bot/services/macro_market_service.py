from __future__ import annotations

from urllib.parse import quote

import aiohttp
import pandas as pd

from xau_signal_bot.services.http import fetch_json
from xau_signal_bot.services.models import Direction, SourceResult


class MacroMarketService:
    name = "USD/Yield Macro Pressure"

    async def analyze(self, session: aiohttp.ClientSession) -> SourceResult:
        dxy = await self._load_symbol(session, "DX-Y.NYB")
        yields = await self._load_symbol(session, "^TNX")
        if not dxy and not yields:
            return SourceResult.unavailable(self.name, "DXY and US 10Y yield data were unavailable")

        checks: list[str] = []
        gold_votes: list[Direction] = []
        data: dict[str, object] = {}

        if dxy:
            dxy_change = dxy["change_pct"]
            data["dxy_change_pct"] = dxy_change
            if dxy_change <= -0.03:
                gold_votes.append(Direction.BULLISH)
                checks.append(f"DXY down {dxy_change:+.2f}% supports gold")
            elif dxy_change >= 0.03:
                gold_votes.append(Direction.BEARISH)
                checks.append(f"DXY up {dxy_change:+.2f}% pressures gold")
            else:
                checks.append(f"DXY flat {dxy_change:+.2f}%")

        if yields:
            yield_change = yields["change_pct"]
            data["us10y_change_pct"] = yield_change
            if yield_change <= -0.10:
                gold_votes.append(Direction.BULLISH)
                checks.append(f"US 10Y yield down {yield_change:+.2f}% supports gold")
            elif yield_change >= 0.10:
                gold_votes.append(Direction.BEARISH)
                checks.append(f"US 10Y yield up {yield_change:+.2f}% pressures gold")
            else:
                checks.append(f"US 10Y yield flat {yield_change:+.2f}%")

        bullish = gold_votes.count(Direction.BULLISH)
        bearish = gold_votes.count(Direction.BEARISH)
        if bullish > bearish:
            direction = Direction.BULLISH
        elif bearish > bullish:
            direction = Direction.BEARISH
        else:
            direction = Direction.NEUTRAL

        if len(gold_votes) >= 2 and (bullish == 2 or bearish == 2):
            confidence = 85
        elif gold_votes:
            confidence = 62
        else:
            confidence = 35

        return SourceResult(
            name=self.name,
            ok=True,
            direction=direction,
            confidence=confidence,
            summary="; ".join(checks) or "Macro pressure is neutral",
            data={**data, "checks": checks},
        )

    async def _load_symbol(self, session: aiohttp.ClientSession, symbol: str) -> dict[str, float] | None:
        params = {"interval": "5m", "range": "5d", "includePrePost": "false"}
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{quote(symbol)}"
        try:
            payload = await fetch_json(session, url, params=params)
        except Exception:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}"
            payload = await fetch_json(session, url, params=params)

        result = (payload.get("chart", {}).get("result") or [None])[0]
        if not result:
            return None
        quote_data = (result.get("indicators", {}).get("quote") or [{}])[0]
        closes = pd.Series(quote_data.get("close") or [], dtype="float64").dropna()
        if len(closes) < 8:
            return None
        latest = float(closes.iloc[-1])
        previous = float(closes.iloc[-7])
        if previous == 0:
            return None
        return {"latest": latest, "change_pct": ((latest / previous) - 1) * 100}
