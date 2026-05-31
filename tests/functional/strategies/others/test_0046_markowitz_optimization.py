"""Inlined regression test for others/0046_markowitz_optimization.

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
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_1d.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None):
    """Load and normalize MT5 CSV data into a datetime-indexed OHLCV DataFrame."""
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


def prepare_markowitz_optimization_features(df, params):
    """Generate rolling Sharpe proxy and rebalance flags for Markowitz-style timing."""
    lookback = int(params.get("lookback", 120))
    rebalance_days = int(params.get("rebalance_days", 63))
    rf = float(params.get("risk_free_rate", 0.0))

    out = df.copy()
    ret = out["close"].pct_change()
    mu = ret.rolling(lookback).mean() * 252
    sigma = ret.rolling(lookback).std() * np.sqrt(252)
    out["sharpe_proxy"] = (mu - rf) / sigma.replace(0, np.inf)

    out["rebalance_flag"] = 0.0
    cnt = 0
    for i in range(len(out)):
        cnt += 1
        if cnt >= rebalance_days:
            out.iloc[i, out.columns.get_loc("rebalance_flag")] = 1.0
            cnt = 0

    out = out[["open", "high", "low", "close", "volume", "openinterest",
               "sharpe_proxy", "rebalance_flag"]].copy()
    return out.dropna()


class Mt5MarkowitzOptimizationFeed(bt.feeds.PandasData):
    """Pandas feed including sharpe proxy and rebalance indicator columns."""
    lines = ("sharpe_proxy", "rebalance_flag",)
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
        ("sharpe_proxy", 6),
        ("rebalance_flag", 7),
    )


class MarkowitzOptimizationStrategy(bt.Strategy):
    """Rebalance based on rolling Sharpe proxy and month-like re-entry signals."""
    params = dict(
        lookback=120,
        rebalance_days=63,
        risk_free_rate=0.0,
        lot_size=1.0,
    )

    def __init__(self):
        """Initialize counters and pending order state for lifecycle tracking."""
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
        """Evaluate rebalance condition and place buy/close orders."""
        self.bar_num += 1
        if self.pending_order is not None:
            return
        rebalance = float(self.data.rebalance_flag[0]) > 0.5
        if not rebalance:
            return
        sharpe = float(self.data.sharpe_proxy[0])
        if not self.position:
            if sharpe > 0:
                self.buy_count += 1
                self.pending_order = self.buy(size=self._get_position_size())
        else:
            if sharpe < 0:
                self.sell_count += 1
                self.pending_order = self.close()

    def notify_order(self, order):
        """Clear pending-order reference when order reaches terminal status."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        """Update trade, win, and loss counters when a position closes."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_046_markowitz_optimization() -> None:
    """Migrated regression test for others/0046_markowitz_optimization."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(lookback=120, rebalance_days=63, risk_free_rate=0.0)
    frame = prepare_markowitz_optimization_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0002, margin=0.01, mult=100.0,
                                  commtype=bt.CommInfoBase.COMM_PERC, percabs=True, stocklike=False)
    cerebro.adddata(Mt5MarkowitzOptimizationFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(MarkowitzOptimizationStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4518
    assert strat.buy_count == 9
    assert strat.sell_count == 8
    assert strat.win_count == 4
    assert strat.loss_count == 4
    assert strat.trade_count == 8
    assert total_trades == 8
    assert abs(final_value - 5203300.4590) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
