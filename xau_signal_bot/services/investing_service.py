from __future__ import annotations

import aiohttp

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.http import fetch_json
from xau_signal_bot.services.models import CalendarEvent, Direction, SourceResult
from xau_signal_bot.services.parsing import direction_from_text, normalize_impact, parse_datetime


class InvestingService:
    technical_name = "Investing.com Technicals"
    calendar_name = "Investing.com Calendar"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def headers(self) -> dict[str, str]:
        if not self.settings.investing_api_key:
            return {}
        return {"Authorization": f"Bearer {self.settings.investing_api_key}"}

    async def get_technical_summary(self, session: aiohttp.ClientSession, timeframe: str) -> SourceResult:
        url = self.settings.investing_technical_api_url
        if not url:
            return SourceResult.unavailable(
                self.technical_name,
                "INVESTING_TECHNICAL_API_URL is not configured. Use a licensed provider endpoint.",
            )
        try:
            payload = await fetch_json(
                session,
                url,
                headers=self.headers(),
                params={"symbol": "XAU/USD", "timeframe": timeframe},
            )
            recommendation = (
                payload.get("recommendation")
                or payload.get("summary")
                or payload.get("signal")
                or payload.get("technicalSummary")
            )
            direction = direction_from_text(str(recommendation))
            return SourceResult(
                name=self.technical_name,
                ok=True,
                direction=direction,
                confidence=float(payload.get("confidence", 0) or 0) or None,
                summary=str(recommendation or "Technical summary received"),
                data=payload,
                url=url,
            )
        except Exception as exc:  # noqa: BLE001
            return SourceResult.unavailable(self.technical_name, str(exc), url=url)

    async def get_calendar(self, session: aiohttp.ClientSession) -> SourceResult:
        url = self.settings.investing_calendar_api_url
        if not url:
            return SourceResult.unavailable(
                self.calendar_name,
                "INVESTING_CALENDAR_API_URL is not configured. Use a licensed provider endpoint.",
            )
        try:
            payload = await fetch_json(session, url, headers=self.headers(), params={"currency": "USD"})
            raw_events = payload.get("events", payload if isinstance(payload, list) else [])
            events: list[CalendarEvent] = []
            for item in raw_events:
                currency = str(item.get("currency") or item.get("country") or "")
                if currency and "USD" not in currency.upper() and "UNITED STATES" not in currency.upper():
                    continue
                starts_at = parse_datetime(str(item.get("time") or item.get("date") or item.get("datetime") or ""))
                events.append(
                    CalendarEvent(
                        title=str(item.get("title") or item.get("event") or "Economic event"),
                        currency="USD",
                        impact=normalize_impact(str(item.get("impact") or item.get("importance") or "")),
                        starts_at=starts_at,
                        source=self.calendar_name,
                    )
                )
            return SourceResult(
                name=self.calendar_name,
                ok=True,
                direction=Direction.NEUTRAL,
                summary=f"{len(events)} USD events",
                data={"events": [event.to_dict() for event in events]},
                url=url,
            )
        except Exception as exc:  # noqa: BLE001
            return SourceResult.unavailable(self.calendar_name, str(exc), url=url)
