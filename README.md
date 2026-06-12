# THE_BOT

XAU/USD Signal Telegram Bot

Python 3.11+ Telegram bot built with aiogram 3.x. It analyzes XAU/USD using separate source adapters, calculates internal indicators, scores confidence from 0 to 100, and returns only `LONG`, `SHORT`, or `NO TRADE`.

The bot uses a risk-managed signal engine:

- It never claims a guaranteed trade.
- It never invents unavailable source data.
- Broad headline/news disagreement lowers confidence, but does not veto a live technical risk signal by itself.
- If high-impact USD news is within the configured window, it returns `NO TRADE`.
- Every signal stores the source results that were used.
- In the default setup, the only required secret is `TELEGRAM_BOT_TOKEN`.
- By default, `/signal` shows successful source adapters and hides optional failed adapters. Set `SHOW_FAILED_SOURCES=true` if you want the full diagnostic list.

The decision engine includes a Paul Tudor Jones-inspired macro overlay. It does not claim to reproduce his private strategy; it applies general discretionary macro principles: trade with the big trend, demand asymmetric reward/risk, avoid major event risk, and stand aside when the tape conflicts.

`TUDOR_RISK_MODE=true` lets the bot take a controlled LONG/SHORT when the dominant trend and PTJ-style overlay align, even if momentum is imperfect or some news feeds disagree. It still requires stops, take-profit levels, no nearby high-impact USD news, and a minimum confidence score.

The book-inspired layer turns the requested trading books into rules:

- `Trading in the Zone`: no-chase entries, predefined stop distance, and clean volatility.
- `Day Trading and Swing Trading the Currency Market`: USD macro/news and event-risk checks.
- `Technical Analysis of the Financial Markets`: trend, momentum, support/resistance, and indicator structure.
- `Gold Trading Boot Camp`: gold spot/futures alignment and Japanese candlestick confirmation.
- `Market Wizards`: professional risk/reward and survival-first filtering.

A 95+ score means the model found an elite confluence setup. It is still not a guaranteed win rate.

## Commands

- `/start` - explain the bot
- `/signal` - choose 1-minute, 3-minute, or 5-minute trade time, then analyze XAU/USD
- `/price` - show live XAU/USD price and update the same Telegram message every second
- `/price_stop` - stop live price updates
- `/sources` - show status of all data sources
- `/sentiment` - show long/short trader sentiment
- `/calendar` - show upcoming high-impact USD news
- `/settings` - view or update user settings
- `/help` - command list

## Source adapters

Implemented as separate modules under `xau_signal_bot/services/`:

- `tradingview_service.py` - TradingView summary through `tradingview-ta`
- `investing_service.py` - licensed/configured Investing.com-compatible technical and calendar endpoints
- `forexfactory_service.py` - ForexFactory weekly XML calendar
- `fxstreet_service.py` - FXStreet RSS news and optional configured calendar endpoint
- `myfxbook_service.py` - Myfxbook community outlook API when credentials are configured
- `oanda_service.py` - OANDA candles when API credentials are configured
- `yahoo_service.py` - Yahoo Finance chart data
- `price_service.py` - price source orchestration, including Stooq quote fallback
- `fed_service.py` - Federal Reserve FOMC calendar page parser
- `news_service.py` - NewsAPI, Reuters-compatible configured endpoint, and legal RSS feeds
- `indicator_service.py` - EMA 20/50/200, RSI 14, MACD, ATR 14, Bollinger Bands, support/resistance
- `candlestick_service.py` - Japanese candlestick patterns, including engulfing, pin bars, and three-candle pushes
- `futures_alignment_service.py` - Swissquote spot versus Yahoo `GC=F` futures momentum and basis
- `macro_market_service.py` - DXY and US 10Y yield pressure checks for gold
- `multi_timeframe_service.py` - selected timeframe plus 5-minute and 15-minute trend confluence
- `regime_alignment_service.py` - H4/H1/M15 regime alignment using higher-timeframe EMA structure
- `gdelt_service.py` - no-key GDELT open headline metadata for gold/USD macro news
- `binance_proxy_service.py` - Binance `PAXGUSDT` order book and trade-pressure proxy with spot-basis filtering
- `data_quality_service.py` - stale quote, spread, and proxy-basis gate
- `book_playbook_service.py` - book-inspired psychology, macro, technical, gold, and risk confluence score
- `confidence_service.py`, `risk_service.py`, `signal_service.py` - scoring, risk, and final decision logic

Default no-token sources include Swissquote XAU/USD live spot quotes, Yahoo Finance price data, TradingView `TVC:GOLD` technicals, ForexFactory calendar data, FXStreet news/analysis RSS, Federal Reserve FOMC calendar parsing, GDELT open news metadata, Google News RSS, Yahoo Finance gold news RSS, CNBC RSS, Investing.com RSS feeds, and Binance `PAXGUSDT` as a tokenized-gold microstructure proxy.

The bot labels price identity explicitly. Swissquote is treated as the live spot quote, Yahoo `GC=F` as futures-candle context, and Binance `PAXGUSDT` as a proxy only. If the proxy basis is too wide, it is ignored.

Short signal timeframes are supported:

- `1m` uses 1-minute candles.
- `3m` uses 1-minute candles resampled into 3-minute candles.
- `5m` uses native 5-minute candles.

TradingView is used as a supporting technical source. For `3m`, TradingView uses its closest available 5-minute interval while internal indicators use the exact resampled 3-minute candles.

Higher-timeframe context is also checked:

- H4 regime uses resampled hourly candles and EMA 50/EMA 200 structure.
- H1 trend checks intermediate alignment.
- M15 timing checks lower-timeframe confirmation.
- Stale live spot quotes or wide spreads block signals before scoring.

Some providers do not publish a stable free official API. OANDA, Myfxbook trader positioning, NewsAPI, Reuters-compatible APIs, and Investing.com/FxStreet calendar API adapters are optional. They are skipped unless configured, so the normal setup does not ask you for those keys.

## Confidence scoring

The score uses a 100-point system:

- Technical trend: 11
- Momentum indicators: 5
- Support/resistance confirmation: 5
- Japanese candlestick confirmation: 7
- Spot/futures alignment: 6
- USD/yield macro pressure: 7
- H4/H1/M15 regime alignment: 14
- Multi-timeframe trend: 9
- PTJ-style macro/risk overlay: 11
- Book playbook score: 9
- Binance PAXG proxy microstructure: 4
- GDELT open news: 4
- News safety: 3
- Volatility quality: 3
- Agreement between external sources: 2

By default, the bot also requires at least 3 quality confirmations and a minimum confidence of 65 before sending a trade alert.

Levels:

- 0-49: no trade
- 50-64: risky
- 65-74: moderate
- 75-84: strong
- 85-94: very strong, still not guaranteed
- 95-100: elite setup, still not guaranteed

## Risk management

For valid `LONG` or `SHORT` signals, the bot calculates:

- Entry price
- Stop loss
- Take profit 1
- Take profit 2
- Optional take profit 3
- Risk/reward ratio

Stop loss uses ATR:

- LONG: `SL = entry - 1.5 * ATR`
- SHORT: `SL = entry + 1.5 * ATR`

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set at least:

```bash
TELEGRAM_BOT_TOKEN=123456:your-token
```

If your router DNS refuses `api.telegram.org`, keep `TELEGRAM_API_IPS=149.154.166.110` in `.env`. The bot will use normal DNS first and only use that IP as a Telegram API fallback.

Optional source credentials, only if you later want those extra adapters:

- `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`
- `MYFXBOOK_EMAIL`, `MYFXBOOK_PASSWORD`
- `NEWS_API_KEY`
- `REUTERS_API_URL`, `REUTERS_API_KEY`
- `INVESTING_TECHNICAL_API_URL`, `INVESTING_CALENDAR_API_URL`
- `FXSTREET_CALENDAR_API_URL`

Run:

```bash
python -m xau_signal_bot.bot.main
```

## Speed Controls

The default setup is tuned for faster responses:

- `SOURCE_CONCURRENCY=8` fetches independent sources in parallel.
- `SOURCE_TIMEOUT_SECONDS=4` prevents one slow site from delaying `/signal`.
- `SIGNAL_CACHE_SECONDS=20` makes repeated `/signal` and `/sources` calls return immediately for a short period.

Increase `SOURCE_TIMEOUT_SECONDS` if you prefer waiting longer for more sources.

## Docker

```bash
cp .env.example .env
docker compose up --build -d
```

The compose file stores local data in `./data`. For SQLite inside Docker, set:

```bash
DATABASE_URL=sqlite+aiosqlite:////app/data/xau_signal_bot.db
```

## systemd deployment

Create `/etc/systemd/system/the-bot.service`:

```ini
[Unit]
Description=THE_BOT XAU/USD Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/root/THE_BOT
EnvironmentFile=/root/THE_BOT/.env
ExecStart=/root/THE_BOT/.venv/bin/python -m xau_signal_bot.bot.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
systemctl daemon-reload
systemctl enable --now the-bot
journalctl -u the-bot -f
```

## User settings

Examples:

```text
/settings timeframe 5m
/settings timeframe 3m
/settings timeframe 1m
/settings min_confidence 65
/settings alerts on
/settings risk 1.0
/settings news_filter off
```

Alerts are enabled by default for users who start the bot. They run every `ALERT_INTERVAL_MINUTES` and only send when:

- confidence is at or above the user's minimum confidence
- the final decision is not `NO TRADE`
- an entry, stop loss, and take-profit plan exists
- no dangerous news is nearby
- the signal is not a duplicate
- cooldown has passed

## Database

SQLAlchemy stores:

- users
- user settings
- every generated signal
- source results used for each signal
- confidence score
- final decision

The schema also includes alert state for duplicate/cooldown handling. Later result tracking can be added by extending `signals` with close/settlement fields.
