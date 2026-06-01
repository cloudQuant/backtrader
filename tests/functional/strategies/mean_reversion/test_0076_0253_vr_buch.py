"""Inlined regression test for mean_reversion/0076_0253_vr_buch.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
    XAUUSD M5 bars from ``tests/datas/XAUUSD_M5.csv`` within
    ``2025-10-01 00:00:00`` to ``2025-12-31 23:59:59``.

Strategy Principle:
    This strategy compares fast and slow moving averages from configurable price
    sources, then trades directional breaks using fixed-size entries with optional
    reversals.

Strategy Logic:
    It loads MT5 data, builds a Backtrader feed with spread, runs the strategy
    with moving-average crossover-style signals, captures buy/sell/trade counts,
    and validates final PnL and trade statistics.
"""
from __future__ import annotations
import backtrader as bt

import datetime
from pathlib import Path

from backtrader.utils.load_data import augment_mt5_csv_columns as _augment_mt5_csv_columns, load_mt5_csv as _load_mt5_csv


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Load MT5 data and preserve fixture-specific raw columns."""
    frame = _load_mt5_csv(
        filepath,
        fromdate=fromdate,
        todate=todate,
        bar_shift_minutes=bar_shift_minutes,
    )
    return _augment_mt5_csv_columns(
        frame,
        filepath,
        ("spread",),
        bar_shift_minutes=bar_shift_minutes,
    )

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M5.csv"


class Mt5PandasFeed(bt.feeds.PandasData):
    """Backtrader feed extension that exposes spread as an additional line."""
    lines = ("spread",)
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4),
        ("openinterest", 5), ("spread", 6),
    )


class VRBuchStrategy(bt.Strategy):
    """Dual moving-average strategy with optional reverse-on-close flow."""
    params = dict(
        fixed_lot=0.1,
        price_source="close",
        fast_period=33, fast_shift=3, fast_method="SMA", fast_price="weighted",
        slow_period=90, slow_shift=1, slow_method="SMA", slow_price="weighted",
    )

    def __init__(self):
        """Bind data sources, indicators, and execution state counters."""
        self.data0_feed = self.datas[0]
        self.fast_source = self._select_price_line(self.p.fast_price)
        self.slow_source = self._select_price_line(self.p.slow_price)
        self.filter_price = self._select_price_line(self.p.price_source)
        fast_cls = self._ma_cls(self.p.fast_method)
        slow_cls = self._ma_cls(self.p.slow_method)
        self.fast_ma = fast_cls(self.fast_source, period=self.p.fast_period)
        self.slow_ma = slow_cls(self.slow_source, period=self.p.slow_period)
        self.entry_order = None
        self.close_order = None
        self.pending_reverse = None
        self.active_side = None
        self.closing_side = None
        self.last_bar_dt = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def prenext(self):
        """Reuse main logic during the bootstrap phase."""
        self.next()

    def _ma_cls(self, method):
        mapping = {
            "SMA": bt.indicators.SimpleMovingAverage,
            "EMA": bt.indicators.ExponentialMovingAverage,
            "SMMA": bt.indicators.SmoothedMovingAverage,
            "WMA": bt.indicators.WeightedMovingAverage,
        }
        return mapping.get(str(method).upper(), bt.indicators.SimpleMovingAverage)

    def _select_price_line(self, source):
        source = str(source).lower()
        if source == "open":
            return self.data0_feed.open
        if source == "high":
            return self.data0_feed.high
        if source == "low":
            return self.data0_feed.low
        if source == "median":
            return (self.data0_feed.high + self.data0_feed.low) / 2.0
        if source == "typical":
            return (self.data0_feed.high + self.data0_feed.low + self.data0_feed.close) / 3.0
        if source == "weighted":
            return (self.data0_feed.high + self.data0_feed.low + self.data0_feed.close * 2.0) / 4.0
        return self.data0_feed.close

    def _shifted(self, line, shift):
        idx = -int(shift) if shift > 0 else 0
        return float(line[idx])

    def _new_bar(self):
        current = bt.num2date(self.data0_feed.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _submit_entry(self, side, reason):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        if side == "long":
            self.entry_order = self.buy(size=size)
        else:
            self.entry_order = self.sell(size=size)

    def _submit_close(self, reason, reverse=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_reverse = reverse
        self.closing_side = self.active_side
        self.close_order = self.close()

    def next(self):
        """Process bar progression, detect trend condition changes, and submit orders."""
        self.bar_num += 1
        if len(self.data0_feed) < self.p.slow_period + max(self.p.fast_shift, self.p.slow_shift) + 3:
            return
        if not self._new_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        fast = self._shifted(self.fast_ma, self.p.fast_shift)
        slow = self._shifted(self.slow_ma, self.p.slow_shift)
        price = float(self.filter_price[0])
        buy = fast > slow and price > fast
        sell = fast < slow and price < fast
        if self.position.size > 0 and sell:
            self._submit_close("sell filter signal", reverse="short")
            return
        if self.position.size < 0 and buy:
            self._submit_close("buy filter signal", reverse="long")
            return
        if not self.position and self.pending_reverse and self.entry_order is None and self.close_order is None:
            side = self.pending_reverse
            self.pending_reverse = None
            self._submit_entry(side, "reverse after close")
            return
        if self.position:
            return
        if buy:
            self._submit_entry("long", "fast>slow and price>fast")
        elif sell:
            self._submit_entry("short", "fast<slow and price<fast")

    def notify_order(self, order):
        """Handle filled or aborted entries/closes and execute pending reversals.

        Args:
            order: Completed or canceled order object.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = "long" if order.executed.size > 0 else "short"
                if self.active_side == "long":
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
                reverse = self.pending_reverse
                self.pending_reverse = None
                if reverse is not None and not self.position:
                    self._submit_entry(reverse, "reverse after close")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
                self.pending_reverse = None

    def notify_trade(self, trade):
        """Track trade result counters and clear active-side state when flat."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self.active_side = None
            self.closing_side = None


def test_075_0076_0253_vr_buch() -> None:
    """Migrated regression test for mean_reversion/0076_0253_vr_buch."""
    fromdate = datetime.datetime(2025, 10, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 23, 59, 59)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=5)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=5))
    cerebro.addstrategy(VRBuchStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 17754
    assert strat.buy_count == 94
    assert strat.sell_count == 95
    assert strat.win_count == 68
    assert strat.loss_count == 120
    assert strat.trade_count == 188
    assert total_trades == 188
    assert abs(final_value - 1005139.2) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
