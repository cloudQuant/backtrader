"""Inlined regression test for trend_following/0096_0976_laguerre_adx.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations
import backtrader as bt

import datetime
import math
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
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


class Mt5PandasFeed(bt.feeds.PandasData):
    """Pandas feed exposing OHLCV fields and spread for laguerre ADX signal."""
    lines = ("spread",)
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5), ("spread", 6),
    )


class LaguerreAdxStrategy(bt.Strategy):
    """Laguerre ADX cross strategy with risk controls and trade accounting."""
    params = dict(
        fixed_lot=0.1, risk_percent=0.0, point=0.01,
        stop_loss_points=1000, take_profit_points=2000,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
        adx_period=14, gamma=0.764, signal_bar=1,
        lot_min=0.01, lot_step=0.01, lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        """Bind execution/signal feeds and initialize counters and risk state."""
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[-1]
        self.indicator = bt.indicators.LaguerreAdxIndicator(
            self.signal_feed, adx_period=self.p.adx_period, gamma=self.p.gamma
        )
        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.entry_side = None
        self.pending_entry_direction = 0
        self.pending_reverse_direction = 0
        self.last_signal_dt = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.warmup = int(self.p.adx_period) + int(self.p.signal_bar) + 8
        self._position_was_open = False

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
        stop_distance = self.p.stop_loss_points * self.p.point
        take_distance = self.p.take_profit_points * self.p.point
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price + take_distance if self.p.take_profit_points > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price - take_distance if self.p.take_profit_points > 0 else None

    def _clear_risk(self):
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    def _submit_entry(self, direction, reason):
        size = self._position_size()
        if size <= 0:
            return False
        self.pending_entry_direction = direction
        if direction > 0:
            self.entry_side = "long"
            self.order = self.buy(size=size)
        else:
            self.entry_side = "short"
            self.order = self.sell(size=size)
        return True

    def _check_exit_levels(self):
        if not self.position:
            return False
        low = float(self.data0_feed.low[0])
        high = float(self.data0_feed.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.pending_reverse_direction = 0
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.pending_reverse_direction = 0
                self.order = self.close()
                return True
            return False
        if self.stop_price is not None and high >= self.stop_price:
            self.pending_reverse_direction = 0
            self.order = self.close()
            return True
        if self.take_profit_price is not None and low <= self.take_profit_price:
            self.pending_reverse_direction = 0
            self.order = self.close()
            return True
        return False

    def next(self):
        """Process signal crossover on each new signal bar and manage exits/entries."""
        self.bar_num += 1
        signal_dt = bt.num2date(self.signal_feed.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        if len(self.signal_feed) < self.warmup:
            return
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        up_now = self._line_value(self.indicator.up, self.p.signal_bar)
        up_prev = self._line_value(self.indicator.up, self.p.signal_bar, previous=True)
        down_now = self._line_value(self.indicator.down, self.p.signal_bar)
        down_prev = self._line_value(self.indicator.down, self.p.signal_bar, previous=True)
        if None in (up_now, up_prev, down_now, down_prev):
            return
        buy_open = self.p.buy_pos_open and up_prev > down_prev and up_now < down_now
        sell_open = self.p.sell_pos_open and up_prev < down_prev and up_now > down_now
        buy_close = self.p.buy_pos_close and sell_open
        sell_close = self.p.sell_pos_close and buy_open
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position.size > 0:
            if buy_close:
                self.pending_reverse_direction = -1 if sell_open else 0
                self.order = self.close()
            return
        if self.position.size < 0:
            if sell_close:
                self.pending_reverse_direction = 1 if buy_open else 0
                self.order = self.close()
            return
        if buy_open:
            self._submit_entry(1, "")
            return
        if sell_open:
            self._submit_entry(-1, "")
            return

    def notify_order(self, order):
        """Track completed/cancelled orders and perform reverse-entry follow-up."""
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.order = None
            self.pending_entry_direction = 0
            self.pending_reverse_direction = 0
            if not self.position:
                self.entry_side = None
            return
        if order.status != order.Completed:
            return
        self.completed_order_count += 1
        if self.pending_entry_direction == 1 and order.isbuy() and self.position.size > 0:
            self.buy_count += 1
            self.entry_price = order.executed.price
            self._set_entry_risk(self.entry_price, 1)
            self.pending_entry_direction = 0
            self.order = None
            return
        if self.pending_entry_direction == -1 and order.issell() and self.position.size < 0:
            self.sell_count += 1
            self.entry_price = order.executed.price
            self._set_entry_risk(self.entry_price, -1)
            self.pending_entry_direction = 0
            self.order = None
            return
        if not self.position:
            self._clear_risk()
            self.order = None
            self.entry_side = None
            reverse_direction = self.pending_reverse_direction
            self.pending_reverse_direction = 0
            if reverse_direction != 0:
                self._submit_entry(reverse_direction, "reverse")
            return
        self.order = None

    def notify_trade(self, trade):
        """Record trade outcome and clear risk state on flat exits."""
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


def _build_signal_frame(df, minutes):
    out = df.resample(
        f"{int(minutes)}min", label="right", closed="right",
    ).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum", "openinterest": "sum",
        "spread": "last",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["openinterest"] = out["openinterest"].fillna(0)
    out["spread"] = out["spread"].fillna(0)
    return out


def test_095_0096_0976_laguerre_adx() -> None:
    """Migrated regression test for trend_following/0096_0976_laguerre_adx."""
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
    cerebro.addstrategy(LaguerreAdxStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 5848
    assert strat.buy_count == 14
    assert strat.sell_count == 10
    assert strat.win_count == 12
    assert strat.loss_count == 12
    assert strat.trade_count == 24
    assert total_trades == 24
    assert abs(final_value - 998885.2) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
