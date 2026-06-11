from __future__ import annotations

import json
from xml.etree import ElementTree

import aiohttp

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.http import fetch_text
from xau_signal_bot.services.models import CalendarEvent, Direction, SourceResult
from xau_signal_bot.services.parsing import normalize_impact, parse_datetime


class ForexFactoryService:
    name = "ForexFactory Calendar"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_calendar(self, session: aiohttp.ClientSession) -> SourceResult:
        url = self.settings.forexfactory_calendar_url
        try:
            text = await fetch_text(session, url)
            if url.lower().endswith(".json"):
                return self._parse_json(text, url)
            root = ElementTree.fromstring(text)
            events: list[CalendarEvent] = []
            for node in root.findall(".//event"):
                country = (node.findtext("country") or node.findtext("currency") or "").strip()
                if country.upper() not in {"USD", "US", "UNITED STATES"}:
                    continue
                title = (node.findtext("title") or node.findtext("name") or "Economic event").strip()
                date_value = (node.findtext("date") or "").strip()
                time_value = (node.findtext("time") or "").strip()
                starts_at = None if "day" in time_value.lower() else parse_datetime(
                    f"{date_value} {time_value}",
                    default_tz=self.settings.forexfactory_timezone,
                )
                events.append(
                    CalendarEvent(
                        title=title,
                        currency="USD",
                        impact=normalize_impact(node.findtext("impact")),
                        starts_at=starts_at,
                        source=self.name,
                        url=url,
                    )
                )
            return SourceResult(
                name=self.name,
                ok=True,
                direction=Direction.NEUTRAL,
                summary=f"{len(events)} USD events",
                data={"events": [event.to_dict() for event in events]},
                url=url,
            )
        except Exception as exc:  # noqa: BLE001
            return SourceResult.unavailable(self.name, str(exc), url=url)

    def _parse_json(self, text: str, url: str) -> SourceResult:
        payload = json.loads(text)
        events: list[CalendarEvent] = []
        for item in payload:
            country = str(item.get("country") or "").strip().upper()
            if country != "USD":
                continue
            events.append(
                CalendarEvent(
                    title=str(item.get("title") or "Economic event"),
                    currency="USD",
                    impact=normalize_impact(str(item.get("impact") or "")),
                    starts_at=parse_datetime(str(item.get("date") or "")),
                    source=self.name,
                    url=url,
                )
            )
        return SourceResult(
            name=self.name,
            ok=True,
            direction=Direction.NEUTRAL,
            summary=f"{len(events)} USD events",
            data={"events": [event.to_dict() for event in events]},
            url=url,
        )
