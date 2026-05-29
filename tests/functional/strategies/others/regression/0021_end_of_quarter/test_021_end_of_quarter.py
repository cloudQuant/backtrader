"""Inlined regression test for others/0021_end_of_quarter.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Pair trading: long XAGUSD / short XAUUSD on quarter-end days.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[6]
GOLD_FILE = _REPO / "tests" / "datas" / "XAUUSD_1d.csv"
SILVER_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "XAGUSD_1d.csv"


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


def prepare_pair_data(df_a, df_b):
    aligned_index = df_a.index.intersection(df_b.index).sort_values()
    return df_a.loc[aligned_index].copy(), df_b.loc[aligned_index].copy()


def prepare_end_of_quarter_features(gold_df, silver_df, params):
    gold_df, silver_df = prepare_pair_data(gold_df, silver_df)
    out = gold_df[["open", "high", "low", "close", "volume", "openinterest"]].copy()
    quarter_period = pd.Series(out.index.to_period("Q"), index=out.index)
    reverse_rank = pd.Series(range(len(out)), index=out.index).groupby(quarter_period).transform(
        lambda x: x.rank(ascending=False, method="first")
    )
    silver_returns = silver_df["close"].pct_change()
    gold_returns = gold_df["close"].pct_change()
    pair_spread = silver_returns - gold_returns
    pair_vol = pair_spread.rolling(int(params.get("vol_lookback", 20)), min_periods=10).std() * np.sqrt(252)

    out["quarter_trading_days_to_end"] = reverse_rank.astype(float)
    out["quarter"] = out.index.quarter.astype(float)
    out["is_quarter_end"] = (reverse_rank == 1).astype(float)
    out["pair_spread"] = pair_spread
    out["pair_vol"] = pair_vol
    out["entry_signal"] = ((out["is_quarter_end"] > 0.5) & (out["pair_vol"] <= float(params.get("max_pair_vol", 0.40)))).astype(float)
    out["quarter_multiplier"] = 1.0
    out.loc[out["quarter"] == 1, "quarter_multiplier"] = 0.8
    out.loc[out["quarter"] == 3, "quarter_multiplier"] = 1.2
    return out.dropna(), silver_df


class EndOfQuarterFeed(bt.feeds.PandasData):
    lines = ("quarter_trading_days_to_end", "quarter", "is_quarter_end", "pair_spread", "pair_vol", "entry_signal", "quarter_multiplier",)
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("quarter_trading_days_to_end", 6), ("quarter", 7), ("is_quarter_end", 8),
        ("pair_spread", 9), ("pair_vol", 10), ("entry_signal", 11), ("quarter_multiplier", 12),
    )


class EndOfQuarterStrategy(bt.Strategy):
    params = dict(
        pair_position_size=0.90,
        holding_days=1,
        stop_loss_spread=0.01,
        vol_lookback=20,
        max_pair_vol=0.4,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.gold = self.datas[0]
        self.silver = self.datas[1]
        self.signal = self.datas[0]
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.signal_days = 0
        self.pending_orders = []
        self.entry_bar = 0
        self.entry_spread = None

    def _target_size(self, data, target_notional_pct):
        broker_value = float(self.broker.getvalue())
        price = float(data.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        direction = 1.0 if target_notional_pct >= 0 else -1.0
        size = broker_value * abs(float(target_notional_pct)) / (price * multiplier)
        return direction * round(size, 2)

    def _close_pair(self):
        for data in (self.gold, self.silver):
            order = self.close(data=data)
            if order is not None:
                self.pending_orders.append(order)

    def next(self):
        self.bar_num += 1
        if self.pending_orders:
            return

        current_spread = float(self.signal.pair_spread[0]) if self.signal.pair_spread[0] == self.signal.pair_spread[0] else 0.0
        if self.getposition(self.gold).size or self.getposition(self.silver).size:
            if self.entry_spread is not None and current_spread < self.entry_spread - float(self.p.stop_loss_spread):
                self.sell_count += 1
                self._close_pair()
                return
            if self.bar_num - self.entry_bar >= int(self.p.holding_days):
                self.sell_count += 1
                self._close_pair()
                return
            return

        if float(self.signal.entry_signal[0]) > 0.5:
            self.signal_days += 1
            multiplier = float(self.signal.quarter_multiplier[0]) if self.signal.quarter_multiplier[0] == self.signal.quarter_multiplier[0] else 1.0
            pair_size = float(self.p.pair_position_size) * multiplier
            silver_size = self._target_size(self.silver, pair_size)
            gold_size = self._target_size(self.gold, -pair_size)
            silver_order = self.buy(data=self.silver, size=max(0.01, abs(silver_size)))
            gold_order = self.sell(data=self.gold, size=max(0.01, abs(gold_size)))
            self.pending_orders.extend([order for order in (silver_order, gold_order) if order is not None])
            self.buy_count += 1
            self.entry_bar = self.bar_num
            self.entry_spread = current_spread

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_orders = [pending for pending in self.pending_orders if pending is not None and pending.ref != order.ref]
        if not self.getposition(self.gold).size and not self.getposition(self.silver).size:
            self.entry_spread = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_021_end_of_quarter() -> None:
    """Migrated regression test for others/0021_end_of_quarter."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    gold_raw = load_mt5_csv(GOLD_FILE, fromdate=fromdate, todate=todate)
    silver_raw = load_mt5_csv(SILVER_FILE, fromdate=fromdate, todate=todate)
    params = dict(vol_lookback=20, max_pair_vol=0.40)
    gold_frame, silver_frame = prepare_end_of_quarter_features(gold_raw, silver_raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(EndOfQuarterFeed(dataname=gold_frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.adddata(bt.feeds.PandasData(dataname=silver_frame[["open", "high", "low", "close", "volume", "openinterest"]],
                                         timeframe=bt.TimeFrame.Days), name="XAGUSD")
    cerebro.addstrategy(EndOfQuarterStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4401
    assert strat.buy_count == 66
    assert strat.sell_count == 66
    assert strat.win_count == 46
    assert strat.loss_count == 70
    assert strat.trade_count == 116
    assert total_trades == 116
    assert abs(final_value - 972856.0948) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
