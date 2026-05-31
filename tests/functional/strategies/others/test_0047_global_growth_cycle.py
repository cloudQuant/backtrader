"""Inlined regression test for others/0047_global_growth_cycle.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
    Symbol XAUUSD (spot gold) on the D1 (daily) timeframe loaded from
    ``tests/datas/XAUUSD_1d.csv`` in MetaTrader 5 export format, clipped to
    2008-01-01 through 2025-12-31. A single daily feed, augmented with
    precomputed growth-cycle and rebalance-timing columns, drives the backtest.

Strategy Principle:
    A long-term growth-cycle timing model. The differential between a fast and a
    slow moving average, normalized by the slow average, measures whether the
    market is in an expansion (fast above slow) or contraction phase. The
    strategy only acts on a fixed rebalance cadence (every N bars), holding a
    long position while the growth cycle is positive and standing aside when it
    turns negative, capturing the bullish portion of the cycle.

Strategy Logic:
    load_mt5_csv loads the daily frame and prepare_global_growth_cycle_features
    precomputes the growth-cycle differential, a positive-signal flag, and a
    rebalance flag stamped every ``rebalance_days`` bars. On each rebalance bar
    the strategy opens a notional-sized long when the signal is positive and
    flat, or closes when the signal turns non-positive while holding.
    notify_order clears the pending-order reference and notify_trade tallies
    win/loss. The test builds cerebro, forces runonce=True, and asserts the
    strategy counters and final portfolio value against migration-time values.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_1d.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None):
    """Load MT5 CSV and convert to standardized OHLCV DataFrame."""
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


def prepare_global_growth_cycle_features(df, params):
    """Compute growth-cycle differential and rebalance timing flags."""
    fast = int(params.get("fast_period", 50))
    slow = int(params.get("slow_period", 200))
    rebalance_days = int(params.get("rebalance_days", 42))

    out = df.copy()
    fast_ma = out["close"].rolling(fast).mean()
    slow_ma = out["close"].rolling(slow).mean()
    out["growth_cycle"] = (fast_ma - slow_ma) / slow_ma.replace(0, np.inf)
    out["signal"] = (out["growth_cycle"] > 0).astype(float)

    out["rebalance_flag"] = 0.0
    cnt = 0
    for i in range(len(out)):
        cnt += 1
        if cnt >= rebalance_days:
            out.iloc[i, out.columns.get_loc("rebalance_flag")] = 1.0
            cnt = 0

    out = out[["open", "high", "low", "close", "volume", "openinterest",
               "growth_cycle", "signal", "rebalance_flag"]].copy()
    return out.dropna()


class Mt5GlobalGrowthCycleFeed(bt.feeds.PandasData):
    """Pandas data feed with growth-cycle and rebalance signal columns."""
    lines = ("growth_cycle", "signal", "rebalance_flag",)
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
        ("growth_cycle", 6),
        ("signal", 7),
        ("rebalance_flag", 8),
    )


class GlobalGrowthCycleStrategy(bt.Strategy):
    """Simple MA-cycle strategy entering when signal is positive on rebalance days."""
    params = dict(
        fast_period=50,
        slow_period=200,
        rebalance_days=42,
        lot_size=1.0,
    )

    def __init__(self):
        """Initialize strategy counters and pending order state."""
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * float(target_notional_pct) / (execution_price * multiplier)
        return max(0.01, round(size, 2))

    def next(self):
        """Handle rebalance days by opening on positive signal and closing otherwise."""
        self.bar_num += 1
        if self.pending_order is not None:
            return
        rebalance = float(self.data.rebalance_flag[0]) > 0.5
        if not rebalance:
            return
        signal = float(self.data.signal[0]) > 0.5
        if not self.position:
            if signal:
                self.buy_count += 1
                self.pending_order = self.buy(size=self._get_position_size())
        else:
            if not signal:
                self.sell_count += 1
                self.pending_order = self.close()

    def notify_order(self, order):
        """Reset pending order state when order lifecycle ends."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        """Update trade count and win/loss statistics for closed trades."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_047_global_growth_cycle() -> None:
    """Migrated regression test for others/0047_global_growth_cycle."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(fast_period=50, slow_period=200, rebalance_days=42)
    frame = prepare_global_growth_cycle_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0002, margin=0.01, mult=100.0,
                                  commtype=bt.CommInfoBase.COMM_PERC, percabs=True, stocklike=False)
    cerebro.adddata(Mt5GlobalGrowthCycleFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(GlobalGrowthCycleStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4439
    assert strat.buy_count == 10
    assert strat.sell_count == 9
    assert strat.win_count == 3
    assert strat.loss_count == 6
    assert strat.trade_count == 9
    assert total_trades == 9
    assert abs(final_value - 3330054.6192) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
