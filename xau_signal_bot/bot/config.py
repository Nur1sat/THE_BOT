from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_api_ips: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["149.154.166.110"],
        alias="TELEGRAM_API_IPS",
    )
    database_url: str = Field(
        default="sqlite+aiosqlite:///./xau_signal_bot.db",
        alias="DATABASE_URL",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    default_timeframe: str = Field(default="5m", alias="DEFAULT_TIMEFRAME")
    default_minimum_confidence: int = Field(default=65, alias="DEFAULT_MINIMUM_CONFIDENCE")
    default_alerts_enabled: bool = Field(default=True, alias="DEFAULT_ALERTS_ENABLED")
    default_risk_percentage: float = Field(default=1.0, alias="DEFAULT_RISK_PERCENTAGE")
    default_news_filter_enabled: bool = Field(default=True, alias="DEFAULT_NEWS_FILTER_ENABLED")
    show_failed_sources: bool = Field(default=False, alias="SHOW_FAILED_SOURCES")
    tudor_risk_mode: bool = Field(default=True, alias="TUDOR_RISK_MODE")
    tudor_min_overlay_score: int = Field(default=55, alias="TUDOR_MIN_OVERLAY_SCORE")
    min_quality_confirmations: int = Field(default=3, alias="MIN_QUALITY_CONFIRMATIONS")

    http_timeout_seconds: float = Field(default=12.0, alias="HTTP_TIMEOUT_SECONDS")
    source_timeout_seconds: float = Field(default=4.0, alias="SOURCE_TIMEOUT_SECONDS")
    source_concurrency: int = Field(default=8, alias="SOURCE_CONCURRENCY")
    signal_cache_seconds: float = Field(default=20.0, alias="SIGNAL_CACHE_SECONDS")
    primary_quote_max_age_seconds: float = Field(default=90.0, alias="PRIMARY_QUOTE_MAX_AGE_SECONDS")
    dangerous_news_window_minutes: int = Field(default=60, alias="DANGEROUS_NEWS_WINDOW_MINUTES")
    alert_interval_minutes: int = Field(default=5, alias="ALERT_INTERVAL_MINUTES")
    alert_cooldown_minutes: int = Field(default=30, alias="ALERT_COOLDOWN_MINUTES")
    price_live_refresh_seconds: float = Field(default=1.0, alias="PRICE_LIVE_REFRESH_SECONDS")
    proxy_max_basis_pct: float = Field(default=1.5, alias="PROXY_MAX_BASIS_PCT")

    yahoo_symbols: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["GC=F"], alias="YAHOO_SYMBOLS")
    swissquote_xauusd_url: str = Field(
        default="https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD",
        alias="SWISSQUOTE_XAUUSD_URL",
    )
    stooq_enabled: bool = Field(default=False, alias="STOOQ_ENABLED")
    stooq_symbol: str = Field(default="xauusd", alias="STOOQ_SYMBOL")

    tradingview_symbol: str = Field(default="GOLD", alias="TRADINGVIEW_SYMBOL")
    tradingview_screener: str = Field(default="cfd", alias="TRADINGVIEW_SCREENER")
    tradingview_exchange: str = Field(default="TVC", alias="TRADINGVIEW_EXCHANGE")

    investing_technical_api_url: str = Field(default="", alias="INVESTING_TECHNICAL_API_URL")
    investing_calendar_api_url: str = Field(default="", alias="INVESTING_CALENDAR_API_URL")
    investing_api_key: str = Field(default="", alias="INVESTING_API_KEY")

    forexfactory_calendar_url: str = Field(
        default="https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        alias="FOREXFACTORY_CALENDAR_URL",
    )
    forexfactory_timezone: str = Field(default="America/New_York", alias="FOREXFACTORY_TIMEZONE")

    fxstreet_news_rss_url: str = Field(default="https://www.fxstreet.com/rss/news", alias="FXSTREET_NEWS_RSS_URL")
    fxstreet_calendar_api_url: str = Field(default="", alias="FXSTREET_CALENDAR_API_URL")
    fxstreet_api_key: str = Field(default="", alias="FXSTREET_API_KEY")

    myfxbook_email: str = Field(default="", alias="MYFXBOOK_EMAIL")
    myfxbook_password: str = Field(default="", alias="MYFXBOOK_PASSWORD")

    oanda_api_token: str = Field(default="", alias="OANDA_API_TOKEN")
    oanda_account_id: str = Field(default="", alias="OANDA_ACCOUNT_ID")
    oanda_environment: str = Field(default="practice", alias="OANDA_ENVIRONMENT")
    oanda_instrument: str = Field(default="XAU_USD", alias="OANDA_INSTRUMENT")

    fed_calendar_url: str = Field(
        default="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        alias="FED_CALENDAR_URL",
    )
    gdelt_doc_api_url: str = Field(default="https://api.gdeltproject.org/api/v2/doc/doc", alias="GDELT_DOC_API_URL")
    binance_api_base_url: str = Field(default="https://api.binance.com", alias="BINANCE_API_BASE_URL")
    binance_paxg_symbol: str = Field(default="PAXGUSDT", alias="BINANCE_PAXG_SYMBOL")

    news_api_key: str = Field(default="", alias="NEWS_API_KEY")
    reuters_api_url: str = Field(default="", alias="REUTERS_API_URL")
    reuters_api_key: str = Field(default="", alias="REUTERS_API_KEY")
    news_rss_urls: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F&region=US&lang=en-US",
            "https://news.google.com/rss/search?q=XAU%2FUSD%20OR%20gold%20Fed%20dollar&hl=en-US&gl=US&ceid=US:en",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "https://www.cnbc.com/id/15839069/device/rss/rss.html",
            "https://www.investing.com/rss/news_11.rss",
            "https://www.investing.com/rss/news_14.rss",
            "https://www.investing.com/rss/news_25.rss",
            "https://www.investing.com/rss/news_1.rss",
            "https://www.fxstreet.com/rss/analysis",
        ],
        alias="NEWS_RSS_URLS",
    )

    @field_validator("telegram_api_ips", "yahoo_symbols", "news_rss_urls", mode="before")
    @classmethod
    def split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("default_timeframe")
    @classmethod
    def validate_default_timeframe(cls, value: str) -> str:
        allowed = {"1m", "3m", "5m"}
        if value not in allowed:
            raise ValueError(f"DEFAULT_TIMEFRAME must be one of {', '.join(sorted(allowed))}")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
