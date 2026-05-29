"""Inlined regression test for price_patterns/0003_0344_exp_xperiodcandle.

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


def _build_signal_frame(df, minutes):
    out = df.resample(f"{int(minutes)}min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum", "openinterest": "sum",
        "spread": "last",
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


class XPeriodCandleColor(bt.Indicator):
    lines = ("color_idx", "xopen", "xclose", "xhigh", "xlow")
    params = dict(cperiod=5, ma_length=3)

    def __init__(self):
        self.smooth_open = bt.indicators.SimpleMovingAverage(self.data.open, period=self.p.ma_length)
        self.smooth_high = bt.indicators.SimpleMovingAverage(self.data.high, period=self.p.ma_length)
        self.smooth_low = bt.indicators.SimpleMovingAverage(self.data.low, period=self.p.ma_length)
        self.smooth_close = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.ma_length)
        self.addminperiod(self.p.ma_length + self.p.cperiod)

    def next(self):
        lookback = max(1, int(self.p.cperiod))
        start = -(lookback - 1)
        xopen = float(self.smooth_open[start])
        xclose = float(self.smooth_close[0])
        highs = [float(self.smooth_high[-i]) for i in range(lookback)]
        lows = [float(self.smooth_low[-i]) for i in range(lookback)]
        self.lines.xopen[0] = xopen
        self.lines.xclose[0] = xclose
        self.lines.xhigh[0] = max(highs)
        self.lines.xlow[0] = min(lows)
        self.lines.color_idx[0] = 0.0 if xopen <= xclose else 2.0


class ExpXPeriodCandleStrategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1, risk_percent=0.0, point_size=0.01,
        stoploss_pips=1000, takeprofit_pips=2000,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
        cperiod=5, ma_length=3, signal_bar=1,
        lot_min=0.01, lot_step=0.01, lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[1]
        self.channel = XPeriodCandleColor(self.signal_feed, cperiod=self.p.cperiod, ma_length=self.p.ma_length)
        self.order = None
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def _round_size(self, size):
        bounded = min(max(size, self.p.lot_min), self.p.lot_max)
        steps = round(bounded / self.p.lot_step)
        return min(max(steps * self.p.lot_step, self.p.lot_min), self.p.lot_max)

    def _position_size(self):
        if self.p.fixed_lot > 0:
            return self._round_size(self.p.fixed_lot)
        return self._round_size(self.p.lot_min)

    def _line_value(self, line, signal_bar, previous=False):
        shift = (int(signal_bar) - 1) + (1 if previous else 0)
        if len(line.array) <= shift:
            return None
        value = float(line[-shift] if shift else line[0])
        if not math.isfinite(value):
            return None
        return value

    def _set_entry_risk(self, price, direction):
        stop_distance = self.p.stoploss_pips * self.p.point_size
        take_distance = self.p.takeprofit_pips * self.p.point_size
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stoploss_pips > 0 else None
            self.take_profit_price = price + take_distance if self.p.takeprofit_pips > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stoploss_pips > 0 else None
            self.take_profit_price = price - take_distance if self.p.takeprofit_pips > 0 else None

    def _clear_risk(self):
        self.stop_price = None
        self.take_profit_price = None

    def _check_exit_levels(self):
        if not self.position:
            return False
        low = float(self.data0_feed.low[0])
        high = float(self.data0_feed.high[0])
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
        signal_dt = bt.num2date(self.signal_feed.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        warmup = self.p.ma_length + self.p.cperiod + self.p.signal_bar + 2
        if len(self.signal_feed) < warmup:
            return
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        color_now = self._line_value(self.channel.color_idx, self.p.signal_bar)
        color_prev = self._line_value(self.channel.color_idx, self.p.signal_bar, previous=True)
        if color_now is None or color_prev is None:
            return
        buy_open = self.p.buy_pos_open and color_prev < 1.0 and color_now > 0.0
        sell_close = self.p.sell_pos_close and color_prev < 1.0
        sell_open = self.p.sell_pos_open and color_prev > 1.0 and color_now < 2.0
        buy_close = self.p.buy_pos_close and color_prev > 1.0
        if self.position.size > 0 and buy_close:
            self.order = self.close()
            return
        if self.position.size < 0 and sell_close:
            self.order = self.close()
            return
        if self.position:
            return
        size = self._position_size()
        if buy_open:
            self.entry_side = "long"
            self.order = self.buy(size=size)
        elif sell_open:
            self.entry_side = "short"
            self.order = self.sell(size=size)

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
                self._clear_risk()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None
            if not self.position:
                self.entry_side = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self._clear_risk()
            self.entry_side = None


def test_002_0003_0344_exp_xperiodcandle() -> None:
    """Migrated regression test for price_patterns/0003_0344_exp_xperiodcandle."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    signal_df = _build_signal_frame(df, 240)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.adddata(Mt5PandasFeed(dataname=signal_df, timeframe=bt.TimeFrame.Minutes, compression=240))
    cerebro.addstrategy(ExpXPeriodCandleStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 6016
    assert strat.buy_count == 23
    assert strat.sell_count == 23
    assert strat.win_count == 21
    assert strat.loss_count == 25
    assert strat.trade_count == 46
    assert total_trades == 46
    assert abs(final_value - 998414.7) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
