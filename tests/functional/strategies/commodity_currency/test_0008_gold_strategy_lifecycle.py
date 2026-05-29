"""Inlined regression test for commodity_currency/0008_gold_strategy_lifecycle.

Self-contained pandas-based test (no Cerebro). Implements the SMA-200 trend baseline,
a Sharpe-decay monitor, and a drawdown-based circuit breaker for XAUUSD daily data.
"""
from __future__ import annotations

import datetime
import io
import math
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "XAUUSD_1d.csv"

TRADING_DAYS = 252


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = "\n".join(lines)
    sep = "\t" if "\t" in lines[0] else ","
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df["<DATE>"].astype(str) + " " + df["<TIME>"].astype(str)
    parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M", errors="coerce")
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M:%S", errors="coerce")
    df["datetime"] = parsed
    df = df.rename(columns={"<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low", "<CLOSE>": "close",
                             "<TICKVOL>": "tick_volume", "<VOL>": "real_volume"})
    df["openinterest"] = 0
    df["volume"] = df["tick_volume"] if "tick_volume" in df.columns else 0
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest"]]
    df = df.dropna(subset=["datetime"]).set_index("datetime").sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_baseline_returns(df, params):
    out = df.copy()
    sma_window = int(params.get("sma_window", 200))
    commission_pct = float(params.get("commission_pct", 0.0002))
    out["daily_return"] = out["close"].pct_change().fillna(0.0)
    out["sma_long"] = out["close"].rolling(sma_window).mean()
    out["signal"] = (out["close"] > out["sma_long"]).astype(float)
    out["signal"] = out["signal"].shift(1).fillna(0.0)
    out["turnover"] = out["signal"].diff().abs().fillna(0.0)
    out["strategy_return"] = out["signal"] * out["daily_return"] - out["turnover"] * commission_pct
    out["equity_curve"] = (1.0 + out["strategy_return"]).cumprod()
    return out.dropna(subset=["sma_long"]).copy()


def calculate_sharpe(returns, risk_free=0.0):
    series = pd.Series(returns).dropna()
    if len(series) < 2:
        return 0.0
    excess_returns = series - risk_free / TRADING_DAYS
    std = excess_returns.std(ddof=0)
    if std <= 0:
        return 0.0
    return math.sqrt(TRADING_DAYS) * excess_returns.mean() / std


def expected_sharpe(initial_sharpe, annual_decay_rate, years_since_inception):
    return initial_sharpe * (1.0 - annual_decay_rate) ** max(years_since_inception, 0.0)


def calculate_drawdown_stats(returns):
    cumulative = (1.0 + pd.Series(returns).fillna(0.0)).cumprod()
    peak = cumulative.cummax()
    drawdown = cumulative / peak - 1.0
    current_dd = float(drawdown.iloc[-1]) if len(drawdown) else 0.0
    max_dd = float(drawdown.min()) if len(drawdown) else 0.0
    in_drawdown = drawdown < 0
    duration = 0
    current = 0
    for flag in in_drawdown:
        if flag:
            current += 1
            duration = max(duration, current)
        else:
            current = 0
    return current_dd, max_dd, duration


def test_008_gold_strategy_lifecycle() -> None:
    """Migrated regression test for commodity_currency/0008_gold_strategy_lifecycle."""
    fromdate = datetime.datetime(2010, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    frame = prepare_baseline_returns(raw, dict(sma_window=200, commission_pct=0.0002))

    returns = frame["strategy_return"]
    equity_curve = frame["equity_curve"]
    bars = len(frame)
    years_since_inception = bars / TRADING_DAYS

    realized_sharpe = calculate_sharpe(returns)
    exp_sharpe = expected_sharpe(initial_sharpe=1.2, annual_decay_rate=0.05,
                                  years_since_inception=years_since_inception)
    decay_ratio = realized_sharpe / exp_sharpe if abs(exp_sharpe) > 1e-12 else 0.0
    abnormal_decay = bool(decay_ratio < 0.7)

    current_dd, max_dd, dd_duration = calculate_drawdown_stats(returns)
    expected_max_dd = -1.0 / 1.2
    expected_max_duration = int(TRADING_DAYS / (1.2 ** 2))
    drawdown_too_deep = current_dd < expected_max_dd * 1.5
    drawdown_too_long = dd_duration > expected_max_duration * 1.5
    max_dd_exceeded = max_dd < expected_max_dd * 2.0
    should_stop = bool(drawdown_too_deep or drawdown_too_long or max_dd_exceeded)
    recommendation = "STOP" if should_stop else ("WARNING" if abnormal_decay else "CONTINUE")

    final_value = 1_000_000.0 * float(equity_curve.iloc[-1])
    won = int((returns > 0).sum())
    lost = int((returns < 0).sum())
    total_trades = int(frame["signal"].diff().abs().fillna(0.0).sum() / 2)

    print(f"CAPTURED: bars={bars} years={years_since_inception:.4f} sharpe={realized_sharpe:.4f} "
          f"exp_sharpe={exp_sharpe:.4f} decay={decay_ratio:.4f} abnormal={abnormal_decay} "
          f"current_dd={current_dd:.6f} max_dd={max_dd:.6f} dd_dur={dd_duration} "
          f"should_stop={should_stop} rec={recommendation} won={won} lost={lost} "
          f"trades={total_trades} fv={final_value:.4f}")

    assert bars == 3924
    assert won == 1301
    assert lost == 1211
    assert total_trades == 60
    assert dd_duration == 2288
    assert recommendation == "STOP"
    assert abs(realized_sharpe - 0.5532) < 1e-3
    assert abs(decay_ratio - 1.0246) < 1e-3
    assert abs(final_value - 2574735.9633) < 1.0
