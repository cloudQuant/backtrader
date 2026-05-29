"""Inlined regression test for price_patterns/0002_0343_exp_xperiodcandle_x2.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Uses M15 + H1 (fast) + D1 (slow) multi-timeframe.
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


def _resample(df, rule):
    out = df.resample(rule, label="right", closed="right").agg({
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


class ExpXPeriodCandleX2Strategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1, risk_percent=0.0, point_size=0.01,
        stoploss_pips=1000, takeprofit_pips=2000,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close_slow=True, sell_pos_close_slow=True,
        buy_pos_close_fast=False, sell_pos_close_fast=False,
        slow_cperiod=5, slow_ma_length=3, slow_signal_bar=1,
        fast_cperiod=5, fast_ma_length=3, fast_signal_bar=1,
        lot_min=0.01, lot_step=0.01, lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.fast_feed = self.datas[0]
        self.slow_feed = self.datas[1]
        self.fast_indicator = XPeriodCandleColor(self.fast_feed, cperiod=self.p.fast_cperiod, ma_length=self.p.fast_ma_length)
        self.slow_indicator = XPeriodCandleColor(self.slow_feed, cperiod=self.p.slow_cperiod, ma_length=self.p.slow_ma_length)
        self.order = None
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_fast_dt = None
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

    def _trend(self):
        slow_color = self._line_value(self.slow_indicator.color_idx, self.p.slow_signal_bar)
        if slow_color == 0.0:
            return 1
        if slow_color == 2.0:
            return -1
        return 0

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
        low = float(self.fast_feed.low[0])
        high = float(self.fast_feed.high[0])
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
        fast_dt = bt.num2date(self.fast_feed.datetime[0])
        if self.last_fast_dt == fast_dt:
            return
        self.last_fast_dt = fast_dt
        warmup = max(
            self.p.fast_ma_length + self.p.fast_cperiod + self.p.fast_signal_bar + 1,
            self.p.slow_ma_length + self.p.slow_cperiod + self.p.slow_signal_bar,
        )
        if len(self.fast_feed) < warmup or len(self.slow_feed) < warmup:
            return
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        trend = self._trend()
        fast_now = self._line_value(self.fast_indicator.color_idx, self.p.fast_signal_bar)
        fast_prev = self._line_value(self.fast_indicator.color_idx, self.p.fast_signal_bar, previous=True)
        if fast_now is None or fast_prev is None:
            return
        buy_close = (self.p.buy_pos_close_fast and fast_now == 2.0) or (self.p.buy_pos_close_slow and trend < 0)
        sell_close = (self.p.sell_pos_close_fast and fast_now == 0.0) or (self.p.sell_pos_close_slow and trend > 0)
        if self.position.size > 0 and buy_close:
            self.order = self.close()
            return
        if self.position.size < 0 and sell_close:
            self.order = self.close()
            return
        if self.position:
            return
        buy_open = self.p.buy_pos_open and trend > 0 and fast_now > 0.0 and fast_prev == 0.0
        sell_open = self.p.sell_pos_open and trend < 0 and fast_now < 2.0 and fast_prev == 2.0
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


def test_001_0002_0343_exp_xperiodcandle_x2() -> None:
    """Migrated regression test for price_patterns/0002_0343_exp_xperiodcandle_x2."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    h1_df = _resample(df, "60min")
    d1_df = _resample(df, "1D")

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=h1_df, timeframe=bt.TimeFrame.Minutes, compression=60))
    cerebro.adddata(Mt5PandasFeed(dataname=d1_df, timeframe=bt.TimeFrame.Days, compression=1))
    cerebro.addstrategy(ExpXPeriodCandleX2Strategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 1360
    assert strat.buy_count == 57
    assert strat.sell_count == 26
    assert strat.win_count == 36
    assert strat.loss_count == 47
    assert strat.trade_count == 83
    assert total_trades == 83
    assert abs(final_value - 998519.4) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
