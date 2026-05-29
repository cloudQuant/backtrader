"""Inlined regression test for trend_following/0018_0061_ema_rsi_risk_ea.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
import math
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"
MINUTES_PER_TRADING_YEAR = 24 * 60 * 252


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.read().strip().split("\n")
    cleaned = "\n".join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep="\t")
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"], format="%Y.%m.%d %H:%M:%S")
    df = df.rename(columns={
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low",
        "<CLOSE>": "close", "<TICKVOL>": "volume",
        "<VOL>": "openinterest", "<SPREAD>": "spread",
    })
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest", "spread"]]
    df = df.set_index("datetime").sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ("spread",)
    params = (
        ("datetime", None),
        ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4),
        ("openinterest", 5), ("spread", 6),
    )


class EmaRsiRiskEaStrategy(bt.Strategy):
    params = dict(
        fast_ema=12,
        slow_ema=26,
        rsi_period=14,
        rsi_buy_thresh=55,
        rsi_sell_thresh=45,
        risk_percent=1.0,
        sl_pips=30,
        tp_pips=60,
        trailing_pips=20,
        breakeven_pips=15,
        max_spread_points=30,
        trade_long=True,
        trade_short=True,
        start_hour=1,
        end_hour=23,
        one_trade_per_bar=True,
        pip_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.signal_data = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.fast_ma = bt.ind.EMA(self.signal_data.close, period=self.p.fast_ema)
        self.slow_ma = bt.ind.EMA(self.signal_data.close, period=self.p.slow_ema)
        self.rsi = bt.ind.RSI(self.signal_data.close, period=self.p.rsi_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)
        self.current_order = None
        self.stop_order = None
        self.limit_order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.last_entry_bar = None
        self.last_signal_bar = None
        self.pending_entry_bar = None

    def _normalize_lot(self, lot):
        lot = min(max(lot, self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 4)

    def _within_trading_window(self, now):
        hour = now.hour
        if self.p.start_hour <= self.p.end_hour:
            return self.p.start_hour <= hour < self.p.end_hour
        return hour >= self.p.start_hour or hour < self.p.end_hour

    def _spread_ok(self):
        spread = float(self.exec_data.spread[0]) if len(self.exec_data) else 0.0
        return spread <= self.p.max_spread_points

    def _lot_size_by_risk(self):
        if self.p.sl_pips <= 0 or self.p.pip_size <= 0 or self.p.contract_multiplier <= 0:
            return 0.0
        risk_cash = self.broker.getvalue() * (self.p.risk_percent / 100.0)
        risk_per_lot = self.p.sl_pips * self.p.pip_size * self.p.contract_multiplier
        if risk_per_lot <= 0:
            return 0.0
        return self._normalize_lot(risk_cash / risk_per_lot)

    def _open_bracket(self, direction, lots):
        price = float(self.exec_data.close[0])
        sl_distance = self.p.sl_pips * self.p.pip_size
        tp_distance = self.p.tp_pips * self.p.pip_size
        if direction == "long":
            orders = self.buy_bracket(size=lots, stopprice=price - sl_distance, limitprice=price + tp_distance)
        else:
            orders = self.sell_bracket(size=lots, stopprice=price + sl_distance, limitprice=price - tp_distance)
        self.current_order, self.stop_order, self.limit_order = orders
        self.pending_entry_bar = bt.num2date(self.signal_data.datetime[0]).replace(tzinfo=None)

    def _replace_stop_order(self, new_stop):
        if not self.position or not self.stop_order or not self.stop_order.alive():
            return
        size = abs(self.position.size)
        self.cancel(self.stop_order)
        if self.position.size > 0:
            self.stop_order = self.sell(exectype=bt.Order.Stop, price=new_stop, size=size)
        else:
            self.stop_order = self.buy(exectype=bt.Order.Stop, price=new_stop, size=size)

    def _manage_open_position(self):
        if not self.position or self.current_order:
            return
        if not self.stop_order or not self.stop_order.alive():
            return
        entry_price = self.position.price
        current_price = float(self.exec_data.close[0])
        current_stop = float(self.stop_order.created.price)
        if self.position.size > 0:
            profit_pips = (current_price - entry_price) / self.p.pip_size
            new_stop = current_stop
            if self.p.breakeven_pips > 0 and profit_pips >= self.p.breakeven_pips:
                new_stop = max(new_stop, entry_price)
            if self.p.trailing_pips > 0 and profit_pips > self.p.trailing_pips:
                new_stop = max(new_stop, current_price - self.p.trailing_pips * self.p.pip_size)
            new_stop = round(new_stop, 2)
            if new_stop > current_stop and new_stop < current_price:
                self._replace_stop_order(new_stop)
        else:
            profit_pips = (entry_price - current_price) / self.p.pip_size
            new_stop = current_stop
            if self.p.breakeven_pips > 0 and profit_pips >= self.p.breakeven_pips:
                new_stop = min(new_stop, entry_price)
            if self.p.trailing_pips > 0 and profit_pips > self.p.trailing_pips:
                new_stop = min(new_stop, current_price + self.p.trailing_pips * self.p.pip_size)
            new_stop = round(new_stop, 2)
            if new_stop < current_stop and new_stop > current_price:
                self._replace_stop_order(new_stop)

    def next(self):
        self.bar_num += 1
        min_bars = max(self.p.slow_ema, self.p.rsi_period) + 2
        now = bt.num2date(self.exec_data.datetime[0]).replace(tzinfo=None)
        if self.position:
            self._manage_open_position()
        if self.current_order:
            return
        if len(self.signal_data) < min_bars:
            return
        signal_bar = bt.num2date(self.signal_data.datetime[0]).replace(tzinfo=None)
        if self.last_signal_bar == signal_bar:
            return
        self.last_signal_bar = signal_bar
        if not self._within_trading_window(now):
            return
        if not self._spread_ok():
            return
        if self.position:
            return
        if self.p.one_trade_per_bar and self.last_entry_bar == signal_bar:
            return
        lots = self._lot_size_by_risk()
        if lots <= 0:
            return
        if self.p.trade_long and self.crossover[0] > 0 and self.rsi[0] >= self.p.rsi_buy_thresh:
            self._open_bracket("long", lots)
        elif self.p.trade_short and self.crossover[0] < 0 and self.rsi[0] <= self.p.rsi_sell_thresh:
            self._open_bracket("short", lots)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if order == self.current_order:
                self.last_entry_bar = self.pending_entry_bar
                self.pending_entry_bar = None
                if order.isbuy():
                    self.buy_count += 1
                else:
                    self.sell_count += 1
            elif order == self.stop_order:
                if self.limit_order and self.limit_order.alive():
                    self.cancel(self.limit_order)
            elif order == self.limit_order:
                if self.stop_order and self.stop_order.alive():
                    self.cancel(self.stop_order)
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            if order == self.current_order:
                self.current_order = None
                if order.status != order.Completed:
                    self.pending_entry_bar = None
            if order == self.stop_order:
                self.stop_order = None
            if order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def _resample_frame(df, minutes):
    rule = f"{minutes}min"
    out = df.resample(rule, label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
        "openinterest": "last", "spread": "last",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["openinterest"] = out["openinterest"].fillna(0)
    out["spread"] = out["spread"].fillna(0)
    return out


def test_017_0018_0061_ema_rsi_risk_ea() -> None:
    """Migrated regression test for trend_following/0018_0061_ema_rsi_risk_ea."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    trading_df = _resample_frame(df, 60)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15), name="XAUUSD_M15")
    cerebro.adddata(Mt5PandasFeed(dataname=trading_df, timeframe=bt.TimeFrame.Minutes, compression=60), name="XAUUSD_H1")
    cerebro.addstrategy(EmaRsiRiskEaStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    # Captured-from-canonical-hook expected values
    assert strat.bar_num == 6029, f"bar_num: expected=6029, got={strat.bar_num}"
    assert strat.buy_count == 10, f"buy_count: expected=10, got={strat.buy_count}"
    assert strat.sell_count == 11, f"sell_count: expected=11, got={strat.sell_count}"
    assert strat.win_count == 11, f"win_count: expected=11, got={strat.win_count}"
    assert strat.loss_count == 10, f"loss_count: expected=10, got={strat.loss_count}"
    assert strat.trade_count == 21, f"trade_count: expected=21, got={strat.trade_count}"
    assert total_trades == 21, f"total_trades: expected=21, got={total_trades}"
    assert math.isfinite(final_value), f"final_value not finite: {final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
