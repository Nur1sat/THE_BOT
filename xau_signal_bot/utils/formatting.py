from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from xau_signal_bot.services.models import (
    CalendarEvent,
    Decision,
    MarketData,
    SignalResult,
    SourceResult,
    UserSignalSettings,
)


def format_signal(result: SignalResult) -> str:
    lines = ["<b>XAU/USD Signal</b>", ""]
    lines.append(f"<b>Decision:</b> {escape(result.decision.value)}")
    lines.append(f"<b>Trade time:</b> {escape(_timeframe_label(result.timeframe))}")
    lines.append(f"<b>Estimated success confidence:</b> {result.confidence}% - {escape(result.confidence_label)}")
    lines.append("")
    lines.append("<b>Trade plan:</b>")
    if result.risk:
        lines.extend(
            [
                f"Entry: {result.risk.entry:.2f}",
                f"Leave if wrong / Stop Loss: {result.risk.stop_loss:.2f}",
                f"Take Profit 1: {result.risk.take_profit_1:.2f}",
                f"Take Profit 2: {result.risk.take_profit_2:.2f}",
                f"Take Profit 3: {result.risk.take_profit_3:.2f}" if result.risk.take_profit_3 else "",
                f"Risk/Reward: {escape(result.risk.risk_reward)}",
            ]
        )
    else:
        lines.extend(
            [
                "Entry: no valid entry",
                "Leave / Exit: no trade recommended",
                "Stop Loss: not set because there is no valid trade",
                "Take Profit: not set because there is no valid trade",
            ]
        )
    lines.append("")
    lines.append("<b>Source agreement:</b>")
    for source in result.source_results:
        status = _source_status(source)
        lines.append(f"{escape(source.name)}: {escape(status)}")
    lines.append("")
    lines.append("<b>Reason:</b>")
    for reason in result.reasons[:10]:
        lines.append(f"- {escape(reason)}")
    if result.decision == Decision.NO_TRADE and not result.reasons:
        lines.append("- Market conditions are unclear")
    lines.append("")
    lines.append("<b>Warning:</b>")
    lines.append("The success percentage is a confidence score, not a guaranteed win rate, even above 95%.")
    for warning in result.warnings:
        lines.append(escape(warning))
    return "\n".join(lines)


def format_signal_alert(result: SignalResult) -> str:
    lines = ["<b>Auto XAU/USD Signal Alert</b>", ""]
    lines.append(f"<b>Decision:</b> {escape(result.decision.value)}")
    lines.append(f"<b>Trade time:</b> {escape(_timeframe_label(result.timeframe))}")
    lines.append(f"<b>Estimated success confidence:</b> {result.confidence}% - {escape(result.confidence_label)}")
    lines.append("")
    lines.append("<b>Where to enter and leave:</b>")
    if result.risk:
        lines.extend(
            [
                f"Entry: {result.risk.entry:.2f}",
                f"Stop Loss / leave if wrong: {result.risk.stop_loss:.2f}",
                f"Take Profit 1: {result.risk.take_profit_1:.2f}",
                f"Take Profit 2: {result.risk.take_profit_2:.2f}",
                f"Take Profit 3: {result.risk.take_profit_3:.2f}" if result.risk.take_profit_3 else "",
                f"Risk/Reward: {escape(result.risk.risk_reward)}",
            ]
        )
    else:
        lines.append("No actionable trade plan was produced.")
    lines.append("")
    lines.append("<b>Reason:</b>")
    for reason in result.reasons[:5]:
        lines.append(f"- {escape(reason)}")
    lines.append("")
    lines.append("The success percentage is a confidence score, not a guaranteed win rate, even above 95%.")
    lines.append("This is not financial advice. Trading is risky.")
    return "\n".join(line for line in lines if line != "")


def format_price(market_data: MarketData | None, sources: list[SourceResult]) -> str:
    lines = ["<b>XAU/USD Price</b>", ""]
    if market_data:
        lines.append(f"<b>Price:</b> {market_data.price:.2f}")
        lines.append(f"<b>Source:</b> {escape(market_data.source)} ({escape(market_data.symbol)})")
        lines.append(f"<b>Time:</b> {escape(market_data.timestamp.isoformat())}")
    else:
        lines.append("No current price source was available.")
    lines.append("")
    lines.append("<b>Source status:</b>")
    for source in sources:
        status = _source_status(source)
        lines.append(f"{escape(source.name)}: {escape(status)}")
    return "\n".join(lines)


def format_live_price(
    market_data: MarketData | None,
    sources: list[SourceResult],
    refresh_seconds: float,
) -> str:
    now = datetime.now(timezone.utc)
    lines = ["<b>Live XAU/USD Price</b>", ""]
    if market_data:
        lines.append(f"<b>Price:</b> {market_data.price:.2f}")
        lines.append(f"<b>Source:</b> {escape(market_data.source)} ({escape(market_data.symbol)})")
        lines.append(f"<b>Provider time:</b> {escape(market_data.timestamp.isoformat())}")
    else:
        lines.append("No current price source was available.")
        for source in sources:
            lines.append(f"{escape(source.name)}: {escape(_source_status(source))}")
    lines.append(f"<b>Updated:</b> {escape(now.isoformat())}")
    lines.append(f"<b>Refresh:</b> every {refresh_seconds:g}s")
    lines.append("")
    lines.append("Stop: /price_stop")
    return "\n".join(lines)


def format_sources(sources: list[SourceResult]) -> str:
    lines = ["<b>Source Status</b>", ""]
    for source in sources:
        lines.append(f"{escape(source.name)}: {escape(_source_status(source))}")
    return "\n".join(lines)


def format_sentiment(source: SourceResult) -> str:
    if source.ok:
        return "\n".join(
            [
                "<b>XAU/USD Sentiment</b>",
                "",
                f"{escape(source.name)}: {escape(source.status_text())}",
                escape(source.summary),
            ]
        )
    return "\n".join(
        [
            "<b>XAU/USD Sentiment</b>",
            "",
            f"{escape(source.name)}: unavailable",
            escape(source.error or "No sentiment source configured."),
        ]
    )


def format_calendar(events: list[CalendarEvent], sources: list[SourceResult]) -> str:
    now = datetime.now(timezone.utc)
    upcoming = [
        event
        for event in events
        if event.starts_at and event.starts_at >= now
    ][:12]
    lines = ["<b>Upcoming High-Impact USD News</b>", ""]
    high_impact = [event for event in upcoming if event.impact.lower() == "high"]
    if high_impact:
        for event in high_impact:
            lines.append(
                f"{escape(event.starts_at.isoformat())} - {escape(event.title)} "
                f"({escape(event.source)}, {escape(event.impact)})"
            )
    else:
        lines.append("No high-impact USD events were found from available sources.")
    lines.append("")
    lines.append("<b>Calendar source status:</b>")
    for source in sources:
        lines.append(f"{escape(source.name)}: {escape(_source_status(source))}")
    return "\n".join(lines)


def format_settings(settings: UserSignalSettings) -> str:
    return "\n".join(
        [
            "<b>Settings</b>",
            "",
            f"Timeframe: {escape(settings.timeframe)}",
            f"Minimum confidence: {settings.minimum_confidence}",
            f"Alerts: {'on' if settings.alerts_enabled else 'off'}",
            f"Risk percentage: {settings.risk_percentage:.2f}%",
            f"News filter: {'on' if settings.news_filter_enabled else 'off'}",
            "",
            "<b>Update examples:</b>",
            "/settings timeframe 1m",
            "/settings timeframe 3m",
            "/settings timeframe 5m",
            "/settings min_confidence 65",
            "/settings alerts on",
            "/settings risk 1.0",
            "/settings news_filter off",
        ]
    )


def format_help() -> str:
    return "\n".join(
        [
            "<b>Commands</b>",
            "",
            "/start - explain the bot",
            "/signal - choose 1m, 3m, or 5m and produce LONG, SHORT, or NO TRADE",
            "/price - show live XAU/USD price and update every second",
            "/price_stop - stop live price updates",
            "/sources - show source status",
            "/sentiment - show trader sentiment",
            "/calendar - show upcoming high-impact USD news",
            "/settings - view or update settings",
            "/help - commands list",
        ]
    )


def _source_status(source: SourceResult) -> str:
    if source.ok:
        if source.name in {
            "Japanese Candlesticks",
            "Spot/Futures Alignment",
            "USD/Yield Macro Pressure",
            "Multi-Timeframe Trend",
            "Book Playbook Score",
        }:
            return _truncate(source.summary or source.status_text(), 180)
        return _truncate(source.status_text(), 180)
    return _truncate(f"unavailable ({source.error or 'no data'})", 180)


def _truncate(value: str, limit: int) -> str:
    value = " ".join(str(value).split())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _timeframe_label(timeframe: str) -> str:
    return {
        "1m": "1 minute",
        "3m": "3 minutes",
        "5m": "5 minutes",
    }.get(timeframe, timeframe)
