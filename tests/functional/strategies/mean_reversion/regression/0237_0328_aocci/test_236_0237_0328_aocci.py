"""Inlined regression test for mean_reversion/0237_0328_aocci.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
import math
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[6]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.read().strip().split("\n")
    cleaned = "\n".join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep="\t")
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"], format="%Y.%m.%d %H:%M:%S")
    df = df.rename(columns={
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low", "<CLOSE>": "close",
        "<TICKVOL>": "volume", "<VOL>": "openinterest", "<SPREAD>": "spread",
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


def resample_h1(df):
    out = df.resample("60min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum", "openinterest": "last", "spread": "last",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["openinterest"] = out["openinterest"].fillna(0)
    out["spread"] = out["spread"].fillna(0)
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ("spread",)
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5), ("spread", 6),
    )


class AOCCIStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        stop_loss_pips=50.0, take_profit_pips=50.0,
        trailing_stop_pips=5.0, trailing_step_pips=5.0,
        cci_period=55, cci_applied_price="typical",
        big_jump_pips=1000.0, double_jump_pips=1000.0,
        signal_candle=0, pip_size=0.01,
        h1_compression_minutes=60,
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.h1_data = self.datas[1]
        self.order = None
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.cci = bt.indicators.CommodityChannelIndex(self.exec_data, period=self.p.cci_period)
        self.ao = bt.indicators.AwesomeOscillator(self.exec_data)

    def prenext(self):
        self.next()

    def _set_entry_risk(self, price, direction):
        stop_distance = self.p.stop_loss_pips * self.p.pip_size
        take_distance = self.p.take_profit_pips * self.p.pip_size
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stop_loss_pips > 0 else None
            self.take_profit_price = price + take_distance if self.p.take_profit_pips > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stop_loss_pips > 0 else None
            self.take_profit_price = price - take_distance if self.p.take_profit_pips > 0 else None

    def _signal_ready(self):
        min_bars = max(6, self.p.signal_candle + 2, self.p.cci_period + self.p.signal_candle + 2)
        return len(self.exec_data) > min_bars and len(self.h1_data) > 1

    def _past(self, line, shift):
        return float(line[-shift]) if shift > 0 else float(line[0])

    def _pivot(self):
        shift = self.p.signal_candle + 1
        high = self._past(self.exec_data.high, shift)
        low = self._past(self.exec_data.low, shift)
        close = self._past(self.exec_data.close, shift)
        return (high + low + close) / 3.0

    def _big_jump_blocked(self):
        opens = [float(self.exec_data.open[-i]) if i > 0 else float(self.exec_data.open[0]) for i in range(6)]
        big_jump = self.p.big_jump_pips * self.p.pip_size
        double_jump = self.p.double_jump_pips * self.p.pip_size
        for idx in range(5):
            if abs(opens[idx + 1] - opens[idx]) >= big_jump:
                return True
        for idx in range(4):
            if abs(opens[idx + 2] - opens[idx]) >= double_jump:
                return True
        return False

    def _literal_signal_condition(self):
        ao_0 = self._past(self.ao, 0)
        ao_1 = self._past(self.ao, 1)
        cci_0 = self._past(self.cci, self.p.signal_candle)
        cci_1 = self._past(self.cci, self.p.signal_candle + 1)
        if not all(math.isfinite(v) for v in [ao_0, ao_1, cci_0, cci_1]):
            return False, False
        pivot = self._pivot()
        h1_close_1 = float(self.h1_data.close[-1])
        ask_proxy = float(self.exec_data.close[0])
        base_ok = ao_0 > 0 and cci_0 >= 0 and ask_proxy > pivot
        final_ok = base_ok and (ao_1 < 0 or cci_1 <= 0 or h1_close_1 < pivot)
        return base_ok, final_ok

    def _update_trailing_stop(self):
        if not self.position or self.p.trailing_stop_pips <= 0:
            return
        trailing_stop = self.p.trailing_stop_pips * self.p.pip_size
        trailing_step = self.p.trailing_step_pips * self.p.pip_size
        if self.position.size > 0:
            current_price = float(self.exec_data.high[0])
            if current_price - self.position.price > trailing_stop + trailing_step:
                threshold = current_price - (trailing_stop + trailing_step)
                candidate = current_price - trailing_stop
                if self.stop_price is None or self.stop_price < threshold:
                    self.stop_price = candidate
        else:
            current_price = float(self.exec_data.low[0])
            if self.position.price - current_price > trailing_stop + trailing_step:
                threshold = current_price + trailing_stop + trailing_step
                candidate = current_price + trailing_stop
                if self.stop_price is None or self.stop_price > threshold:
                    self.stop_price = candidate

    def _check_exit_levels(self):
        if not self.position:
            return False
        low = float(self.exec_data.low[0])
        high = float(self.exec_data.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
            return False
        if self.stop_price is not None and high >= self.stop_price:
            self.order = self.close()
            return True
        if self.take_profit_price is not None and low <= self.take_profit_price:
            self.order = self.close()
            return True
        return False

    def next(self):
        self.bar_num += 1
        if not self._signal_ready():
            return
        if self.order is not None:
            return
        if self.position:
            self._update_trailing_stop()
            if self._check_exit_levels():
                return
            return
        if self._big_jump_blocked():
            return
        base_ok, literal_condition = self._literal_signal_condition()
        buy_condition = literal_condition
        sell_condition = False
        if not literal_condition:
            ao_0 = self._past(self.ao, 0)
            ao_1 = self._past(self.ao, 1)
            cci_0 = self._past(self.cci, self.p.signal_candle)
            if all(math.isfinite(v) for v in (ao_0, ao_1, cci_0)):
                buy_condition = ao_0 > ao_1 and cci_0 >= 0
                sell_condition = ao_0 < ao_1 and cci_0 <= 0
        if buy_condition:
            self.entry_side = "long"
            self.order = self.buy(size=self.p.fixed_lot)
        elif sell_condition:
            self.entry_side = "short"
            self.order = self.sell(size=self.p.fixed_lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if order == self.order and self.entry_side == "long" and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self._set_entry_risk(order.executed.price, 1)
            elif order == self.order and self.entry_side == "short" and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self._set_entry_risk(order.executed.price, -1)
            elif not self.position:
                self.stop_price = None
                self.take_profit_price = None
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None
            if not self.position:
                self.entry_side = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        elif trade.pnlcomm < 0:
            self.loss_count += 1


def test_236_0237_0328_aocci() -> None:
    """Migrated regression test for mean_reversion/0237_0328_aocci."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    h1_df = resample_h1(df)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.adddata(Mt5PandasFeed(dataname=h1_df, timeframe=bt.TimeFrame.Minutes, compression=60))
    cerebro.addstrategy(AOCCIStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 6136
    assert strat.buy_count == 492
    assert strat.sell_count == 296
    assert strat.win_count == 398
    assert strat.loss_count == 389
    assert strat.trade_count == 788
    assert total_trades == 788
    assert abs(final_value - 999357.9) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
