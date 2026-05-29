"""Inlined regression test for pivot_fibonacci_system/0003_pivotheiken_3.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Uses M15 + D1 multi-timeframe.
"""
from __future__ import annotations

import datetime
import io
from collections import deque
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
    keep_cols = ["datetime", "open", "high", "low", "close", "volume", "openinterest"]
    if "spread" in df.columns:
        keep_cols.append("spread")
    df = df[keep_cols]
    if "spread" not in df.columns:
        df["spread"] = 0
    df = df.set_index("datetime").sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def _resample_d(df):
    out = df.resample("1D", label="right", closed="right").agg({
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


class StatefulMovingAverage:
    def __init__(self, mode, period):
        self.mode = str(mode).lower()
        self.period = max(int(period), 1)
        self.values = deque(maxlen=self.period)
        self.last = None

    def update(self, value):
        value = float(value)
        self.values.append(value)
        if self.mode == "sma":
            self.last = sum(self.values) / len(self.values)
        elif self.mode == "ema":
            if self.last is None:
                self.last = value
            else:
                alpha = 2.0 / (1.0 + self.period)
                self.last = self.last + alpha * (value - self.last)
        elif self.mode == "smma":
            if self.last is None:
                self.last = value
            else:
                self.last = self.last + (value - self.last) / self.period
        elif self.mode == "lwma":
            weights = list(range(1, len(self.values) + 1))
            weighted_values = [v * w for v, w in zip(self.values, weights)]
            self.last = sum(weighted_values) / sum(weights)
        else:
            self.last = value
        return self.last


class PivotHeiken3Strategy(bt.Strategy):
    params = dict(
        lot=0.10,
        stop_loss_pips=50, take_profit_pips=350,
        trailing_type=2, trailing_stop_pips=50,
        first_move_pips=30, first_stop_loss_pips=50,
        second_move_pips=40, second_stop_loss_pips=50,
        third_move_pips=50, trailing_stop3_pips=50,
        pre_smooth_period=7, pre_smooth_method="lwma",
        post_smooth_period=7, post_smooth_method="lwma",
        signal_period=2, signal_method="smma",
        point=0.01, price_digits=2,
    )

    def __init__(self):
        self.base_feed = self.datas[0]
        self.daily_feed = self.datas[1] if len(self.datas) > 1 else None
        self.order = None
        self.pending_action = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.position_side = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.last_base_dt = None
        self._ha_open = None
        self._ha_close = None
        self._last_mid_value = None
        self._line_value = None
        self._avg_value = None
        self._pivot_value = None
        self.pre_open_ma = StatefulMovingAverage(self.p.pre_smooth_method, self.p.pre_smooth_period)
        self.pre_high_ma = StatefulMovingAverage(self.p.pre_smooth_method, self.p.pre_smooth_period)
        self.pre_low_ma = StatefulMovingAverage(self.p.pre_smooth_method, self.p.pre_smooth_period)
        self.pre_close_ma = StatefulMovingAverage(self.p.pre_smooth_method, self.p.pre_smooth_period)
        self.post_mid_ma = StatefulMovingAverage(self.p.post_smooth_method, self.p.post_smooth_period)
        self.signal_ma = StatefulMovingAverage(self.p.signal_method, self.p.signal_period)

    def _distance(self, pips):
        digits_adjust = 10 if int(self.p.price_digits) in (3, 5) else 1
        return float(pips) * float(self.p.point) * digits_adjust

    def _update_indicator_state(self):
        ma_open = self.pre_open_ma.update(float(self.base_feed.open[0]))
        ma_high = self.pre_high_ma.update(float(self.base_feed.high[0]))
        ma_low = self.pre_low_ma.update(float(self.base_feed.low[0]))
        ma_close = self.pre_close_ma.update(float(self.base_feed.close[0]))
        if self._ha_open is None or self._ha_close is None:
            ha_open = (float(self.base_feed.open[0]) + float(self.base_feed.close[0])) / 2.0
        else:
            ha_open = (self._ha_open + self._ha_close) / 2.0
        ha_close = (ma_open + ma_high + ma_low + ma_close) / 4.0
        ha_mid = self.post_mid_ma.update((ha_open + ha_close) / 2.0)
        previous_mid = self._last_mid_value if self._last_mid_value is not None else ha_mid
        line_value = ha_mid - previous_mid
        avg_value = self.signal_ma.update(line_value)
        self._ha_open = ha_open
        self._ha_close = ha_close
        self._last_mid_value = ha_mid
        self._line_value = line_value
        self._avg_value = avg_value

    def _update_pivot_state(self):
        if self.daily_feed is None or len(self.daily_feed) < 2:
            self._pivot_value = None
            return
        self._pivot_value = (
            float(self.daily_feed.high[-1])
            + float(self.daily_feed.low[-1])
            + float(self.daily_feed.close[-1])
        ) / 3.0

    def _check_entry_condition(self, direction):
        price = float(self.base_feed.close[0])
        if direction == "buy":
            return self._line_value > self._avg_value and price < self._pivot_value
        return self._line_value < self._avg_value and price > self._pivot_value

    def _check_exit_condition(self):
        price = float(self.base_feed.close[0])
        high_0 = float(self.base_feed.high[0])
        low_0 = float(self.base_feed.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low_0 <= self.stop_price:
                return True
            if self.take_profit_price is not None and high_0 >= self.take_profit_price:
                return True
            return self._line_value < self._avg_value and price > self._pivot_value
        if self.stop_price is not None and high_0 >= self.stop_price:
            return True
        if self.take_profit_price is not None and low_0 <= self.take_profit_price:
            return True
        return self._line_value > self._avg_value and price < self._pivot_value

    def _update_trailing_stop(self, price):
        if self.entry_price is None or self.p.trailing_type == 0:
            return
        if self.position.size > 0:
            if self.p.trailing_type == 2:
                distance = self._distance(self.p.trailing_stop_pips)
                if price - self.entry_price > distance:
                    candidate = price - distance
                    if self.stop_price is None or self.stop_price < candidate:
                        self.stop_price = candidate
        else:
            if self.p.trailing_type == 2:
                distance = self._distance(self.p.trailing_stop_pips)
                if self.entry_price - price > distance:
                    candidate = price + distance
                    if self.stop_price is None or self.stop_price > candidate:
                        self.stop_price = candidate

    def _clear_trade_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.position_side = None

    def next(self):
        dt = bt.num2date(self.base_feed.datetime[0])
        if self.last_base_dt == dt:
            return
        self.last_base_dt = dt
        self.bar_num += 1
        self._update_indicator_state()
        self._update_pivot_state()
        if self._line_value is None or self._avg_value is None or self._pivot_value is None:
            return
        if self.order is not None:
            return
        if self.position:
            if self._check_exit_condition():
                self.pending_action = "close"
                self.order = self.close()
                return
            self._update_trailing_stop(float(self.base_feed.close[0]))
            return
        if self._check_entry_condition("buy"):
            self.pending_action = "open_long"
            self.order = self.buy(size=float(self.p.lot))
            return
        if self._check_entry_condition("sell"):
            self.pending_action = "open_short"
            self.order = self.sell(size=float(self.p.lot))

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.pending_action == "open_long" and order.isbuy() and self.position.size > 0:
                self.buy_count += 1
                self.position_side = "buy"
                self.entry_price = float(order.executed.price)
                self.stop_price = self.entry_price - self._distance(self.p.stop_loss_pips) if self.p.stop_loss_pips else None
                self.take_profit_price = self.entry_price + self._distance(self.p.take_profit_pips) if self.p.take_profit_pips else None
            elif self.pending_action == "open_short" and order.issell() and self.position.size < 0:
                self.sell_count += 1
                self.position_side = "sell"
                self.entry_price = float(order.executed.price)
                self.stop_price = self.entry_price + self._distance(self.p.stop_loss_pips) if self.p.stop_loss_pips else None
                self.take_profit_price = self.entry_price - self._distance(self.p.take_profit_pips) if self.p.take_profit_pips else None
            elif self.pending_action == "close" and not self.position:
                self._clear_trade_levels()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None
            self.pending_action = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self._clear_trade_levels()


def test_002_0003_pivotheiken_3() -> None:
    """Migrated regression test for pivot_fibonacci_system/0003_pivotheiken_3."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    d_df = _resample_d(df)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.adddata(Mt5PandasFeed(dataname=d_df, timeframe=bt.TimeFrame.Days, compression=1))
    cerebro.addstrategy(PivotHeiken3Strategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 6038
    assert strat.buy_count == 487
    assert strat.sell_count == 1097
    assert strat.win_count == 735
    assert strat.loss_count == 849
    assert strat.trade_count == 1584
    assert total_trades == 1584
    assert abs(final_value - 995916.3) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
