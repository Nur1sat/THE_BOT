from __future__ import annotations

from datetime import datetime, timezone

from xau_signal_bot.services.models import Direction, MarketData, SourceResult


class DataQualityService:
    name = "Data Quality Gate"

    def __init__(self, max_age_seconds: float) -> None:
        self.max_age_seconds = max_age_seconds

    def analyze(self, market_data: MarketData | None, sources: list[SourceResult]) -> SourceResult:
        if not market_data:
            return SourceResult(
                name=self.name,
                ok=True,
                direction=Direction.NEUTRAL,
                confidence=0,
                summary="BAD: no primary XAU/USD price",
                data={"status": "BAD", "details": ["No primary XAU/USD price was available"]},
            )

        now = datetime.now(timezone.utc)
        age_seconds = max(0.0, (now - market_data.timestamp).total_seconds())
        details = [f"Primary quote age {age_seconds:.1f}s"]
        status = "GOOD"
        confidence = 90

        if age_seconds > self.max_age_seconds:
            status = "BAD"
            confidence = 0
            details.append(f"Primary quote is older than {self.max_age_seconds:g}s")

        swissquote = self._source_by_name("Swissquote XAU/USD", sources)
        if swissquote and swissquote.ok:
            bid = float(swissquote.data.get("bid") or 0)
            ask = float(swissquote.data.get("ask") or 0)
            mid = float(swissquote.data.get("mid") or market_data.price)
            if bid > 0 and ask > 0 and mid > 0:
                spread_pct = ((ask - bid) / mid) * 100
                details.append(f"Swissquote spread {spread_pct:.3f}%")
                if spread_pct > 0.08:
                    status = "BAD"
                    confidence = 0
                    details.append("Spread is too wide for a short-term signal")
                elif spread_pct > 0.04 and status == "GOOD":
                    status = "CAUTION"
                    confidence = 65
                    details.append("Spread is elevated")
        else:
            status = "CAUTION" if status == "GOOD" else status
            confidence = min(confidence, 60)
            details.append("Swissquote spot quote is unavailable")

        proxy = self._source_by_name("Binance PAXG Proxy", sources)
        if proxy and proxy.ok and not proxy.data.get("basis_quality", True):
            details.append("PAXG proxy basis is outside tolerance and is ignored")

        summary = f"{status}: " + "; ".join(details[:3])
        return SourceResult(
            name=self.name,
            ok=True,
            direction=Direction.NEUTRAL,
            confidence=confidence,
            summary=summary,
            data={"status": status, "age_seconds": age_seconds, "details": details},
        )

    @staticmethod
    def _source_by_name(name: str, sources: list[SourceResult]) -> SourceResult | None:
        for source in sources:
            if source.name == name:
                return source
        return None
