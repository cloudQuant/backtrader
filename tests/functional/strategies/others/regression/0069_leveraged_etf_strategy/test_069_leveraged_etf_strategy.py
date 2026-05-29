"""Inlined regression test for others/0069_leveraged_etf_strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[6]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_1d.csv"


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


def _compute_target_exposure(realized_vol, threshold_low, threshold_high, min_exposure, max_exposure):
    if pd.isna(realized_vol):
        return np.nan
    if realized_vol <= threshold_low:
        return float(max_exposure)
    if realized_vol >= threshold_high:
        return float(min_exposure)
    if threshold_high <= threshold_low:
        return float(min_exposure)
    weight = (threshold_high - realized_vol) / (threshold_high - threshold_low)
    return float(min_exposure) + float(weight) * (float(max_exposure) - float(min_exposure))


def prepare_leveraged_etf_features(df, params):
    out = df.copy()
    vol_window = int(params.get("vol_window", 21))
    threshold_low = float(params.get("threshold_low", 0.15))
    threshold_high = float(params.get("threshold_high", 0.25))
    max_exposure = float(params.get("max_exposure", 2.0))
    min_exposure = float(params.get("min_exposure", 0.0))

    out["returns"] = out["close"].pct_change()
    out["realized_vol"] = out["returns"].rolling(vol_window).std() * np.sqrt(252.0)
    out["target_exposure"] = out["realized_vol"].apply(
        lambda x: _compute_target_exposure(
            realized_vol=x,
            threshold_low=threshold_low,
            threshold_high=threshold_high,
            min_exposure=min_exposure,
            max_exposure=max_exposure,
        )
    )
    out["vol_regime"] = 1.0
    out.loc[out["realized_vol"] <= threshold_low, "vol_regime"] = 2.0
    out.loc[out["realized_vol"] >= threshold_high, "vol_regime"] = 0.0
    out["entry_signal"] = (out["target_exposure"] > 0).astype(float)
    out["exit_signal"] = (out["target_exposure"] <= 0).astype(float)
    out = out[[
        "open", "high", "low", "close", "volume", "openinterest",
        "returns", "realized_vol", "target_exposure", "vol_regime", "entry_signal", "exit_signal",
    ]].copy()
    return out.dropna()


class Mt5LeveragedETFFeed(bt.feeds.PandasData):
    lines = ("returns", "realized_vol", "target_exposure", "vol_regime", "entry_signal", "exit_signal",)
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
        ("returns", 6), ("realized_vol", 7), ("target_exposure", 8), ("vol_regime", 9),
        ("entry_signal", 10), ("exit_signal", 11),
    )


class LeveragedETFStrategy(bt.Strategy):
    params = dict(
        vol_window=21,
        threshold_low=0.15,
        threshold_high=0.25,
        max_exposure=2.0,
        min_exposure=0.0,
        rebalance_interval=5,
        rebalance_tolerance=0.05,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.rebalance_count = 0

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
        return max(0.0, round(size, 2))

    def _current_exposure(self):
        broker_value = float(self.broker.getvalue())
        price = float(self.data.close[0])
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if broker_value <= 0 or price <= 0 or multiplier <= 0:
            return 0.0
        return abs(float(self.position.size)) * price * multiplier / broker_value

    def next(self):
        self.bar_num += 1
        if self.pending_order is not None:
            return

        target_exposure = max(float(self.p.min_exposure), min(float(self.p.max_exposure), float(self.data.target_exposure[0])))
        current_exposure = self._current_exposure()
        is_rebalance_bar = self.bar_num == 1 or ((self.bar_num - 1) % max(1, int(self.p.rebalance_interval)) == 0)
        should_flatten = target_exposure <= 0 and self.position.size != 0
        should_open = self.position.size == 0 and target_exposure > 0 and is_rebalance_bar
        should_resize = self.position.size != 0 and is_rebalance_bar and abs(current_exposure - target_exposure) > float(self.p.rebalance_tolerance)

        if not (should_flatten or should_open or should_resize):
            return

        target_size = self._get_position_size(target_notional_pct=target_exposure)
        current_size = float(self.position.size)
        if abs(target_size - current_size) < 0.01:
            return

        if target_size > current_size:
            self.buy_count += 1
        elif target_size < current_size:
            self.sell_count += 1

        self.rebalance_count += 1
        self.pending_order = self.order_target_size(target=target_size)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_069_leveraged_etf_strategy() -> None:
    """Migrated regression test for others/0069_leveraged_etf_strategy."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(
        vol_window=21, threshold_low=0.15, threshold_high=0.25,
        max_exposure=2.0, min_exposure=0.0,
    )
    frame = prepare_leveraged_etf_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0002, margin=0.01, mult=100.0,
                                  commtype=bt.CommInfoBase.COMM_PERC, percabs=True, stocklike=False)
    cerebro.adddata(Mt5LeveragedETFFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(LeveragedETFStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4617
    assert strat.buy_count == 236
    assert strat.sell_count == 196
    assert strat.win_count == 9
    assert strat.loss_count == 6
    assert strat.trade_count == 15
    assert total_trades == 15
    assert abs(final_value - 9569851.0235) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
