from __future__ import annotations

import aiohttp

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.http import fetch_json
from xau_signal_bot.services.models import Direction, SourceResult


class MyfxbookService:
    name = "Myfxbook Sentiment"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_sentiment(self, session: aiohttp.ClientSession) -> SourceResult:
        if not self.settings.myfxbook_email or not self.settings.myfxbook_password:
            return SourceResult.unavailable(self.name, "MYFXBOOK_EMAIL and MYFXBOOK_PASSWORD are not configured")
        try:
            login = await fetch_json(
                session,
                "https://www.myfxbook.com/api/login.json",
                params={"email": self.settings.myfxbook_email, "password": self.settings.myfxbook_password},
            )
            if login.get("error"):
                return SourceResult.unavailable(self.name, str(login.get("message") or "Myfxbook login failed"))
            session_id = login.get("session")
            payload = await fetch_json(
                session,
                "https://www.myfxbook.com/api/get-community-outlook.json",
                params={"session": session_id},
            )
            symbols = payload.get("symbols", [])
            selected = None
            for symbol in symbols:
                name = str(symbol.get("name") or symbol.get("symbol") or "").upper()
                if name in {"XAUUSD", "XAU/USD", "GOLD"} or "XAU" in name or "GOLD" in name:
                    selected = symbol
                    break
            if not selected:
                return SourceResult.unavailable(self.name, "XAU/USD sentiment was not present in Myfxbook response")
            long_pct = float(selected.get("longPercentage") or selected.get("long") or 0)
            short_pct = float(selected.get("shortPercentage") or selected.get("short") or 0)
            if long_pct > short_pct + 5:
                direction = Direction.BULLISH
            elif short_pct > long_pct + 5:
                direction = Direction.BEARISH
            else:
                direction = Direction.NEUTRAL
            return SourceResult(
                name=self.name,
                ok=True,
                direction=direction,
                confidence=round(abs(long_pct - short_pct), 1),
                summary=f"Long {long_pct:.1f}% / Short {short_pct:.1f}%",
                data={"symbol": selected, "long_percent": long_pct, "short_percent": short_pct},
            )
        except Exception as exc:  # noqa: BLE001
            return SourceResult.unavailable(self.name, str(exc))
