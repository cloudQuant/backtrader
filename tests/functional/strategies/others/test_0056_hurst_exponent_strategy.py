"""Inlined regression test for others/0056_hurst_exponent_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "GLD_1d.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None):
    """Load MT5 CSV file, parse datetime, and return cleaned OHLCV frame."""
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


def _hurst_from_prices(values, min_lag, max_lag):
    prices = np.asarray(values, dtype=float)
    if len(prices) <= max_lag + 1:
        return np.nan
    log_prices = np.log(prices)
    tau = []
    lags = list(range(min_lag, max_lag + 1))
    for lag in lags:
        diffs = log_prices[lag:] - log_prices[:-lag]
        std = np.std(diffs)
        tau.append(std if std > 0 else np.nan)
    tau = np.asarray(tau, dtype=float)
    valid = np.isfinite(tau) & (tau > 0)
    if valid.sum() < 3:
        return np.nan
    slope, _ = np.polyfit(np.log(np.asarray(lags)[valid]), np.log(tau[valid]), 1)
    return float(np.clip(slope, 0.0, 1.0))


def prepare_hurst_data(frame, params):
    """Compute Hurst, SMA, RSI and return dataset for the Hurst strategy."""
    prepared = frame[["open", "high", "low", "close", "volume", "openinterest"]].copy()
    hurst_window = int(params.get("hurst_window", 150))
    min_lag = int(params.get("min_lag", 2))
    max_lag = int(params.get("max_lag", 20))
    prepared["hurst"] = prepared["close"].rolling(hurst_window).apply(
        lambda arr: _hurst_from_prices(arr, min_lag, max_lag), raw=True
    )
    prepared["sma"] = prepared["close"].rolling(int(params.get("sma_period", 50))).mean()
    delta = prepared["close"].diff()
    gain = delta.clip(lower=0).rolling(int(params.get("rsi_period", 14))).mean()
    loss = (-delta.clip(upper=0)).rolling(int(params.get("rsi_period", 14))).mean()
    rs = gain / loss.replace(0, np.nan)
    prepared["rsi"] = 100 - (100 / (1 + rs))
    prepared = prepared.dropna().copy()
    return prepared


class HurstFeed(bt.feeds.PandasData):
    """Pandas data feed with Hurst, SMA and RSI custom lines."""
    lines = ("hurst", "sma", "rsi")
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("hurst", 6), ("sma", 7), ("rsi", 8),
    )


class HurstExponentStrategy(bt.Strategy):
    """Dual-regime strategy switching between trend and mean reversion by Hurst value."""
    params = dict(
        trend_threshold=0.55,
        mean_reversion_threshold=0.45,
        rsi_oversold=30,
        rsi_overbought=70,
        trend_weight=1.0,
        mean_reversion_weight=0.75,
        rebalance_interval_days=5,
        hurst_window=150,
        min_lag=2,
        max_lag=20,
        sma_period=50,
        rsi_period=14,
        commission_pct=0.0005,
    )

    def __init__(self):
        """Initialize counters and state used for rebalance and classification tracking."""
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.trend_days = 0
        self.mean_reversion_days = 0
        self.neutral_days = 0

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _target_size(self, data, target_pct):
        broker_value = float(self.broker.getvalue())
        price = float(data.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * abs(float(target_pct)) / (price * multiplier)
        size = max(0.01, round(size, 2))
        return size if target_pct >= 0 else -size

    def next(self):
        """Evaluate regime signals and rebalance positions on interval boundaries."""
        self.bar_num += 1
        data = self.datas[0]
        if self.order_refs:
            return
        hurst_value = float(data.hurst[0])
        target_pct = 0.0
        if hurst_value > float(self.p.trend_threshold):
            self.trend_days += 1
            target_pct = float(self.p.trend_weight) if float(data.close[0]) > float(data.sma[0]) else -float(self.p.trend_weight)
        elif hurst_value < float(self.p.mean_reversion_threshold):
            self.mean_reversion_days += 1
            if float(data.rsi[0]) < float(self.p.rsi_oversold):
                target_pct = float(self.p.mean_reversion_weight)
            elif float(data.rsi[0]) > float(self.p.rsi_overbought):
                target_pct = -float(self.p.mean_reversion_weight)
            else:
                target_pct = 0.0
        else:
            self.neutral_days += 1
        if self.bar_num > 1 and (self.bar_num - 1) % max(1, int(self.p.rebalance_interval_days)) != 0:
            return
        current_pos = float(self.getposition(data).size)
        target_size = self._target_size(data, target_pct)
        if abs(target_size - current_pos) < 0.01:
            return
        if target_size > current_pos:
            self.buy_count += 1
        elif target_size < current_pos:
            self.sell_count += 1
        self._submit(self.order_target_size(data=data, target=target_size))

    def notify_order(self, order):
        """Forget submitted order references after order status resolves."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        """Track completed trades and classify by profitability."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_056_hurst_exponent_strategy() -> None:
    """Migrated regression test for others/0056_hurst_exponent_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(
        hurst_window=150, min_lag=2, max_lag=20,
        sma_period=50, rsi_period=14,
    )
    frame = prepare_hurst_data(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(HurstFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="GLD")
    cerebro.addstrategy(HurstExponentStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4370
    assert strat.buy_count == 181
    assert strat.sell_count == 96
    assert strat.win_count == 59
    assert strat.loss_count == 49
    assert strat.trade_count == 108
    assert total_trades == 108
    assert abs(final_value - 669247.0641) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
