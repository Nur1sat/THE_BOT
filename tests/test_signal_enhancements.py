from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.services.binance_proxy_service import BinancePaxgProxyService
from xau_signal_bot.services.data_quality_service import DataQualityService
from xau_signal_bot.services.models import Direction, IndicatorSnapshot, MarketData, SourceResult
from xau_signal_bot.services.regime_alignment_service import RegimeAlignmentService


def snapshot(
    *,
    price: float = 2000.0,
    ema20: float = 1995.0,
    ema50: float = 1980.0,
    ema200: float = 1950.0,
    trend: Direction = Direction.BULLISH,
    momentum: Direction = Direction.BULLISH,
) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        price=price,
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        rsi14=55.0,
        macd=2.0 if momentum == Direction.BULLISH else -2.0,
        macd_signal=1.0 if momentum == Direction.BULLISH else -1.0,
        atr14=5.0,
        bollinger_upper=price + 10,
        bollinger_middle=price,
        bollinger_lower=price - 10,
        support=price - 20,
        resistance=price + 20,
        trend_direction=trend,
        momentum_direction=momentum,
        volatility_quality="Good",
        atr_percent=0.25,
        reasons=[],
    )


class DataQualityServiceTest(unittest.TestCase):
    def test_stale_primary_quote_is_bad(self) -> None:
        market_data = MarketData(
            source="Swissquote XAU/USD",
            symbol="XAU/USD",
            price=2000.0,
            timestamp=datetime.now(timezone.utc) - timedelta(seconds=120),
        )
        source = SourceResult(
            name="Swissquote XAU/USD",
            ok=True,
            data={"bid": 1999.9, "ask": 2000.1, "mid": 2000.0},
        )

        result = DataQualityService(max_age_seconds=30).analyze(market_data, [source])

        self.assertEqual(result.data["status"], "BAD")
        self.assertIn("older than 30s", " ".join(result.data["details"]))


class RegimeAlignmentServiceTest(unittest.TestCase):
    def test_requires_h4_and_h1_alignment(self) -> None:
        result = RegimeAlignmentService().analyze(
            {
                "4h": snapshot(),
                "1h": snapshot(),
                "15m": snapshot(),
            }
        )

        self.assertEqual(result.direction, Direction.BULLISH)
        self.assertEqual(result.confidence, 90.0)
        self.assertEqual(result.data["timeframe_bias"]["H4"], Direction.BULLISH.value)


class BinancePaxgProxyServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_proxy_can_support_when_basis_and_book_agree(self) -> None:
        async def fake_fetch_json(_session, url, *, params=None, **_kwargs):
            if "ticker/price" in url:
                return {"price": "2005.0"}
            if "depth" in url:
                return {
                    "bids": [["2004.9", "6"], ["2004.8", "4"]],
                    "asks": [["2005.1", "2"], ["2005.2", "1"]],
                }
            if "aggTrades" in url:
                return [
                    {"p": "2005.0", "q": "2", "m": False},
                    {"p": "2004.8", "q": "1", "m": True},
                ]
            raise AssertionError(f"Unexpected URL: {url}")

        settings = Settings(TELEGRAM_BOT_TOKEN="", PROXY_MAX_BASIS_PCT=1.5)
        service = BinancePaxgProxyService(settings)

        with patch("xau_signal_bot.services.binance_proxy_service.fetch_json", side_effect=fake_fetch_json):
            result = await service.analyze(object(), 2000.0)

        self.assertEqual(result.direction, Direction.BULLISH)
        self.assertTrue(result.data["basis_quality"])
        self.assertGreater(result.data["orderbook_imbalance"], 0)


if __name__ == "__main__":
    unittest.main()
