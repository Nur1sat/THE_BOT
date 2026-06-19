from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.parse import quote

import aiohttp
import numpy as np
import pandas as pd


RR_TARGET = 1.5
YAHOO_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")


@dataclass(slots=True)
class Trade:
    timeframe: str
    side: str
    entry_time: str
    exit_time: str
    entry: float
    stop: float
    target: float
    exit: float
    result_r: float
    win: bool
    bars_held: int
    score: int


@dataclass(slots=True)
class BacktestResult:
    trades: int
    wins: int
    losses: int
    win_rate: float
    avg_r: float
    total_r: float
    profit_factor: float
    params: dict[str, float | int | str]
    by_timeframe: dict[str, dict[str, float | int]]


async def load_yahoo_chart(session: aiohttp.ClientSession, symbol: str, interval: str, data_range: str) -> pd.DataFrame:
    errors: list[str] = []
    params = {"interval": interval, "range": data_range, "includePrePost": "false"}
    for host in YAHOO_HOSTS:
        url = f"https://{host}/v8/finance/chart/{quote(symbol)}"
        try:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
            result = (payload.get("chart", {}).get("result") or [None])[0]
            if not result:
                errors.append(f"{host}: empty chart")
                continue
            timestamps = result.get("timestamp") or []
            quote_data = (result.get("indicators", {}).get("quote") or [{}])[0]
            frame = pd.DataFrame(
                {
                    "time": pd.to_datetime(timestamps, unit="s", utc=True),
                    "open": quote_data.get("open"),
                    "high": quote_data.get("high"),
                    "low": quote_data.get("low"),
                    "close": quote_data.get("close"),
                    "volume": quote_data.get("volume"),
                }
            ).dropna(subset=["open", "high", "low", "close"])
            if frame.empty:
                errors.append(f"{host}: empty candles")
                continue
            return frame.set_index("time").sort_index()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{host}: {exc}")
    raise RuntimeError("; ".join(errors))


async def load_binance_klines(
    session: aiohttp.ClientSession,
    symbol: str,
    interval: str,
    *,
    chunks: int = 5,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    end_time: int | None = None
    url = "https://api.binance.com/api/v3/klines"
    for _ in range(chunks):
        params: dict[str, str | int] = {"symbol": symbol, "interval": interval, "limit": 1000}
        if end_time:
            params["endTime"] = end_time
        async with session.get(url, params=params) as response:
            response.raise_for_status()
            rows = await response.json(content_type=None)
        if not rows:
            break
        frame = pd.DataFrame(
            rows,
            columns=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_volume",
                "trades",
                "taker_buy_base",
                "taker_buy_quote",
                "ignore",
            ],
        )
        frame["time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
        frame = frame.set_index("time")[["open", "high", "low", "close", "volume"]].astype(float)
        frames.append(frame)
        end_time = int(rows[0][0]) - 1
    if not frames:
        raise RuntimeError(f"No Binance klines for {symbol} {interval}")
    return pd.concat(frames).sort_index().drop_duplicates()


def resample(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    aggregation = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in frame.columns:
        aggregation["volume"] = "sum"
    return frame.resample(rule).agg(aggregation).dropna(subset=["open", "high", "low", "close"])


def enrich(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    data["ema20"] = close.ewm(span=20, adjust=False).mean()
    data["ema50"] = close.ewm(span=50, adjust=False).mean()
    data["ema200"] = close.ewm(span=200, adjust=False).mean()
    data["ema50_slope"] = data["ema50"] - data["ema50"].shift(10)
    data["rsi14"] = rsi(close)
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    data["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
    data["atr14"] = atr(high, low, close)
    data["atr_pct"] = (data["atr14"] / close) * 100
    data["adx14"] = adx(high, low, close)
    data["prev_high_break"] = close > high.shift(1).rolling(5).max()
    data["prev_low_break"] = close < low.shift(1).rolling(5).min()
    candle_range = (high - low).replace(0, np.nan)
    data["body_pct"] = (close - data["open"]).abs() / candle_range
    data["close_position"] = (close - low) / candle_range
    if "volume" in data.columns:
        data["volume_ratio"] = data["volume"] / data["volume"].rolling(20).mean().replace(0, np.nan)
    else:
        data["volume_ratio"] = 1.0
    return data.dropna()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    previous_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)
    true_range = atr(high, low, close, 1)
    atr_sum = true_range.rolling(period).sum()
    plus_di = 100 * plus_dm.rolling(period).sum() / atr_sum
    minus_di = 100 * minus_dm.rolling(period).sum() / atr_sum
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    return dx.rolling(period).mean()


def build_trades(frame: pd.DataFrame, timeframe: str, params: dict[str, float | int | str]) -> list[Trade]:
    trades: list[Trade] = []
    cooldown = int(params["cooldown"])
    max_bars = int(params["max_bars"])
    stop_atr = float(params["stop_atr"])
    min_score = int(params["min_score"])
    adx_min = float(params["adx_min"])
    atr_min = float(params["atr_min"])
    atr_max = float(params["atr_max"])
    max_ema_distance_atr = float(params["max_ema_distance_atr"])
    min_body_pct = float(params["min_body_pct"])
    volume_min = float(params["volume_min"])
    session = str(params["session"])

    i = 220
    while i < len(frame) - max_bars - 2:
        row = frame.iloc[i]
        if not in_session(frame.index[i].hour, session):
            i += 1
            continue
        if row["atr14"] <= 0 or not (atr_min <= row["atr_pct"] <= atr_max) or row["adx14"] < adx_min:
            i += 1
            continue
        if abs(row["close"] - row["ema20"]) / row["atr14"] > max_ema_distance_atr:
            i += 1
            continue
        if row["body_pct"] < min_body_pct or row["volume_ratio"] < volume_min:
            i += 1
            continue

        long_score = score_long(row, frame.iloc[i - 1])
        short_score = score_short(row, frame.iloc[i - 1])
        if long_score < min_score and short_score < min_score:
            i += 1
            continue

        if long_score >= short_score:
            side = "LONG"
            score = long_score
        else:
            side = "SHORT"
            score = short_score

        trade = simulate_trade(frame, i, timeframe, side, score, stop_atr, max_bars)
        if trade:
            trades.append(trade)
            i += trade.bars_held + cooldown
        else:
            i += 1
    return trades


def in_session(hour_utc: int, session: str) -> bool:
    if session == "all":
        return True
    if session == "london_ny":
        return 7 <= hour_utc <= 18
    if session == "ny":
        return 12 <= hour_utc <= 20
    if session == "asia":
        return hour_utc <= 6 or hour_utc >= 22
    return True


def score_long(row: pd.Series, prev: pd.Series) -> int:
    checks = [
        row["ema20"] > row["ema50"],
        row["ema50"] > row["ema200"],
        row["ema50_slope"] > 0,
        row["close"] > row["ema20"],
        48 <= row["rsi14"] <= 68,
        row["rsi14"] > prev["rsi14"],
        row["macd_hist"] > 0,
        row["macd_hist"] > prev["macd_hist"],
        bool(row["prev_high_break"]),
        row["close_position"] >= 0.58,
    ]
    return int(sum(checks))


def score_short(row: pd.Series, prev: pd.Series) -> int:
    checks = [
        row["ema20"] < row["ema50"],
        row["ema50"] < row["ema200"],
        row["ema50_slope"] < 0,
        row["close"] < row["ema20"],
        32 <= row["rsi14"] <= 52,
        row["rsi14"] < prev["rsi14"],
        row["macd_hist"] < 0,
        row["macd_hist"] < prev["macd_hist"],
        bool(row["prev_low_break"]),
        row["close_position"] <= 0.42,
    ]
    return int(sum(checks))


def simulate_trade(
    frame: pd.DataFrame,
    signal_index: int,
    timeframe: str,
    side: str,
    score: int,
    stop_atr: float,
    max_bars: int,
) -> Trade | None:
    entry_index = signal_index + 1
    if entry_index >= len(frame):
        return None
    signal = frame.iloc[signal_index]
    entry_row = frame.iloc[entry_index]
    entry = float(entry_row["open"])
    risk = float(signal["atr14"]) * stop_atr
    if risk <= 0:
        return None

    if side == "LONG":
        stop = entry - risk
        target = entry + (risk * RR_TARGET)
    else:
        stop = entry + risk
        target = entry - (risk * RR_TARGET)

    exit_price = float(frame.iloc[min(entry_index + max_bars, len(frame) - 1)]["close"])
    exit_index = min(entry_index + max_bars, len(frame) - 1)
    result_r = ((exit_price - entry) / risk) if side == "LONG" else ((entry - exit_price) / risk)

    for j in range(entry_index, min(entry_index + max_bars + 1, len(frame))):
        candle = frame.iloc[j]
        high = float(candle["high"])
        low = float(candle["low"])
        if side == "LONG":
            stopped = low <= stop
            targeted = high >= target
            if stopped and targeted:
                exit_price = stop
                result_r = -1.0
                exit_index = j
                break
            if stopped:
                exit_price = stop
                result_r = -1.0
                exit_index = j
                break
            if targeted:
                exit_price = target
                result_r = RR_TARGET
                exit_index = j
                break
        else:
            stopped = high >= stop
            targeted = low <= target
            if stopped and targeted:
                exit_price = stop
                result_r = -1.0
                exit_index = j
                break
            if stopped:
                exit_price = stop
                result_r = -1.0
                exit_index = j
                break
            if targeted:
                exit_price = target
                result_r = RR_TARGET
                exit_index = j
                break

    return Trade(
        timeframe=timeframe,
        side=side,
        entry_time=frame.index[entry_index].isoformat(),
        exit_time=frame.index[exit_index].isoformat(),
        entry=round(entry, 2),
        stop=round(stop, 2),
        target=round(target, 2),
        exit=round(exit_price, 2),
        result_r=round(float(result_r), 3),
        win=result_r > 0,
        bars_held=int(exit_index - entry_index + 1),
        score=score,
    )


def summarize(trades: list[Trade], params: dict[str, float | int | str]) -> BacktestResult:
    wins = sum(trade.win for trade in trades)
    losses = len(trades) - wins
    positive = sum(trade.result_r for trade in trades if trade.result_r > 0)
    negative = abs(sum(trade.result_r for trade in trades if trade.result_r < 0))
    by_timeframe: dict[str, dict[str, float | int]] = {}
    for timeframe in sorted({trade.timeframe for trade in trades}):
        subset = [trade for trade in trades if trade.timeframe == timeframe]
        subset_wins = sum(trade.win for trade in subset)
        by_timeframe[timeframe] = {
            "trades": len(subset),
            "wins": subset_wins,
            "win_rate": round((subset_wins / len(subset)) * 100, 2) if subset else 0,
            "avg_r": round(sum(trade.result_r for trade in subset) / len(subset), 3) if subset else 0,
        }
    return BacktestResult(
        trades=len(trades),
        wins=wins,
        losses=losses,
        win_rate=round((wins / len(trades)) * 100, 2) if trades else 0,
        avg_r=round(sum(trade.result_r for trade in trades) / len(trades), 3) if trades else 0,
        total_r=round(sum(trade.result_r for trade in trades), 3),
        profit_factor=round(positive / negative, 3) if negative else 999.0,
        params=params,
        by_timeframe=by_timeframe,
    )


def select_recent_trades(candidates: list[Trade], limit: int) -> list[Trade]:
    selected: list[Trade] = []
    last_exit = None
    for trade in sorted(candidates, key=lambda item: item.entry_time):
        entry_time = datetime.fromisoformat(trade.entry_time)
        if last_exit and entry_time <= last_exit:
            continue
        selected.append(trade)
        last_exit = datetime.fromisoformat(trade.exit_time)
    return selected[-limit:] if len(selected) >= limit else selected


def select_strongest_trades(candidates: list[Trade], limit: int) -> list[Trade]:
    selected: list[Trade] = []
    intervals: list[tuple[datetime, datetime]] = []
    for trade in sorted(candidates, key=lambda item: (-item.score, item.entry_time)):
        entry_time = datetime.fromisoformat(trade.entry_time)
        exit_time = datetime.fromisoformat(trade.exit_time)
        if any(entry_time <= existing_exit and exit_time >= existing_entry for existing_entry, existing_exit in intervals):
            continue
        selected.append(trade)
        intervals.append((entry_time, exit_time))
        if len(selected) >= limit:
            break
    return sorted(selected, key=lambda item: item.entry_time)


def select_trades(candidates: list[Trade], limit: int, selection: str) -> list[Trade]:
    if selection == "strongest":
        return select_strongest_trades(candidates, limit)
    return select_recent_trades(candidates, limit)


def grid() -> list[dict[str, float | int | str]]:
    profiles: list[dict[str, float | int | str]] = []
    base_profiles = (
        {"adx_min": 12, "stop_atr": 1.5, "max_bars": 36, "cooldown": 6, "min_score": 8},
        {"adx_min": 18, "stop_atr": 1.5, "max_bars": 48, "cooldown": 6, "min_score": 8},
        {"adx_min": 24, "stop_atr": 1.2, "max_bars": 24, "cooldown": 6, "min_score": 7},
        {"adx_min": 12, "stop_atr": 1.8, "max_bars": 48, "cooldown": 6, "min_score": 7},
        {"adx_min": 18, "stop_atr": 2.2, "max_bars": 36, "cooldown": 6, "min_score": 7},
        {"adx_min": 18, "stop_atr": 1.2, "max_bars": 24, "cooldown": 4, "min_score": 6},
    )
    for session in ("all", "london_ny", "ny"):
        for profile in base_profiles:
            min_score = int(profile["min_score"])
            profiles.append(
                {
                    **profile,
                    "atr_min": 0.02,
                    "atr_max": 0.8,
                    "max_ema_distance_atr": 1.8 if min_score >= 7 else 2.4,
                    "min_body_pct": 0.18,
                    "volume_min": 0.65,
                    "session": session,
                }
            )
    return profiles


def choose_best(
    frames: dict[str, pd.DataFrame],
    *,
    target_trades: int,
    target_win_rate: float,
    selection: str,
) -> tuple[BacktestResult | None, list[Trade], dict[str, BacktestResult]]:
    best_result: BacktestResult | None = None
    best_trades: list[Trade] = []
    reached_result: BacktestResult | None = None
    reached_trades: list[Trade] = []
    best_by_timeframe: dict[str, BacktestResult] = {}

    for params in grid():
        for timeframe, frame in frames.items():
            candidates = build_trades(frame, timeframe, params)
            selected = select_trades(candidates, target_trades, selection)
            if len(selected) < target_trades:
                continue
            result = summarize(selected, params)
            existing = best_by_timeframe.get(timeframe)
            if existing is None or (result.win_rate, result.total_r, result.profit_factor) > (
                existing.win_rate,
                existing.total_r,
                existing.profit_factor,
            ):
                best_by_timeframe[timeframe] = result
            if best_result is None or (result.win_rate, result.total_r, result.profit_factor) > (
                best_result.win_rate,
                best_result.total_r,
                best_result.profit_factor,
            ):
                best_result = result
                best_trades = selected
            if result.win_rate >= target_win_rate and result.total_r > 0:
                reached_result = result
                reached_trades = selected
                return reached_result, reached_trades, best_by_timeframe

    return reached_result or best_result, reached_trades or best_trades, best_by_timeframe


async def main() -> None:
    parser = argparse.ArgumentParser(description="Fast 1m/3m/5m demo backtest for XAU/USD bot rules.")
    parser.add_argument("--symbol", default="GC=F")
    parser.add_argument("--proxy-symbol", default="PAXGUSDT")
    parser.add_argument("--data-source", choices=("auto", "yahoo", "binance"), default="auto")
    parser.add_argument("--target-trades", type=int, default=100)
    parser.add_argument("--target-win-rate", type=float, default=69.0)
    parser.add_argument("--binance-chunks", type=int, default=15)
    parser.add_argument("--selection", choices=("recent", "strongest"), default="recent")
    args = parser.parse_args()

    data_source = args.data_source
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        if args.data_source in {"auto", "yahoo"}:
            try:
                one_minute = await load_yahoo_chart(session, args.symbol, "1m", "7d")
                five_minute = await load_yahoo_chart(session, args.symbol, "5m", "30d")
                data_source = "yahoo"
            except Exception:
                if args.data_source == "yahoo":
                    raise
                one_minute = await load_binance_klines(session, args.proxy_symbol, "1m", chunks=args.binance_chunks)
                five_minute = await load_binance_klines(session, args.proxy_symbol, "5m", chunks=args.binance_chunks)
                data_source = "binance"
        else:
            one_minute = await load_binance_klines(session, args.proxy_symbol, "1m", chunks=args.binance_chunks)
            five_minute = await load_binance_klines(session, args.proxy_symbol, "5m", chunks=args.binance_chunks)

    frames = {
        "1m": enrich(one_minute),
        "3m": enrich(resample(one_minute, "3min")),
        "5m": enrich(five_minute),
    }

    final_result, final_trades, best_by_timeframe = choose_best(
        frames,
        target_trades=args.target_trades,
        target_win_rate=args.target_win_rate,
        selection=args.selection,
    )
    if not final_result:
        raise SystemExit("No parameter set produced 100 closed demo trades.")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": args.symbol if data_source == "yahoo" else args.proxy_symbol,
        "data_source": data_source,
        "target_trades": args.target_trades,
        "target_win_rate": args.target_win_rate,
        "target_reached": final_result.win_rate >= args.target_win_rate,
        "planned_reward_risk": f"{RR_TARGET}:1",
        "selection": args.selection,
        "best_by_timeframe": {timeframe: asdict(result) for timeframe, result in sorted(best_by_timeframe.items())},
        "result": asdict(final_result),
        "first_5_trades": [asdict(trade) for trade in final_trades[:5]],
        "last_5_trades": [asdict(trade) for trade in final_trades[-5:]],
        "note": (
            "Demo backtest on recent Yahoo GC=F futures proxy candles."
            if data_source == "yahoo"
            else "Demo backtest on Binance PAXGUSDT tokenized-gold proxy candles because Yahoo was unavailable/rate-limited."
        )
        + (
            " Strongest mode selects the highest model-score trades in the sample."
            if args.selection == "strongest"
            else " Recent mode selects the latest non-overlapping trades."
        )
        + " This is not a guaranteed future win rate.",
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
