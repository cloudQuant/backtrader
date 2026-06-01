"""Inlined regression test for pivot_fibonacci_system/0001_mostashar15_pivot.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Uses M15 + H1 multi-timeframe.
"""
from __future__ import annotations
import backtrader as bt

import datetime
from datetime import timedelta
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
    """PandasData feed that exposes an extra ``spread`` line for MT5 data."""
    lines = ("spread",)
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5), ("spread", 6),
    )


class MostasHaR15PivotStrategy(bt.Strategy):
    """Pivot/Fibonacci strategy operating on H1 session levels and M15 execution."""
    params = dict(
        fixed_lot=0.1, point_size=0.01,
        stoploss_pips=20, trailing_stop_pips=5, trailing_step_pips=5,
        time_zone=2,
    )

    def __init__(self):
        """Initialize indicators, session state, and counters."""
        self.data0_feed = self.datas[0]
        self.h1_feed = self.datas[1]
        self.order = None
        self.close_order = None
        self.active_side = None
        self.entry_price = None
        self.stop_price = None
        self.limit_price = None
        self.current_session_key = None
        self.current_session_high = None
        self.current_session_low = None
        self.current_session_close = None
        self.prev_session_ohlc = None
        self.adx = bt.indicators.ADX(self.h1_feed, period=14)
        self.di = bt.indicators.DI(self.h1_feed, period=14)
        self.plus_di = self.di.lines.plusDI
        self.minus_di = self.di.lines.minusDI
        self.ma_close = bt.indicators.EMA(self.h1_feed.close, period=5)
        self.ma_open = bt.indicators.EMA(self.h1_feed.open, period=8)
        self.osma = bt.indicators.MACDHisto(self.h1_feed.close, period_me1=12, period_me2=26, period_signal=9).histo
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def _session_key(self, dt):
        return (dt - timedelta(hours=self.p.time_zone)).date()

    def _update_session_ohlc(self):
        dt = bt.num2date(self.data0_feed.datetime[0])
        key = self._session_key(dt)
        high = float(self.data0_feed.high[0])
        low = float(self.data0_feed.low[0])
        close = float(self.data0_feed.close[0])
        if self.current_session_key is None:
            self.current_session_key = key
            self.current_session_high = high
            self.current_session_low = low
            self.current_session_close = close
            return
        if key != self.current_session_key:
            self.prev_session_ohlc = dict(
                high=self.current_session_high,
                low=self.current_session_low,
                close=self.current_session_close,
            )
            self.current_session_key = key
            self.current_session_high = high
            self.current_session_low = low
            self.current_session_close = close
            return
        self.current_session_high = max(self.current_session_high, high)
        self.current_session_low = min(self.current_session_low, low)
        self.current_session_close = close

    def _pivot_levels(self):
        if self.prev_session_ohlc is None:
            return None
        yh = self.prev_session_ohlc["high"]
        yl = self.prev_session_ohlc["low"]
        yc = self.prev_session_ohlc["close"]
        p = (yh + yl + yc) / 3.0
        r1 = (2.0 * p) - yl
        s1 = (2.0 * p) - yh
        r2 = p + (yh - yl)
        s2 = p - (yh - yl)
        r3 = (2.0 * p) + (yh - (2.0 * yl))
        s3 = (2.0 * p) - ((2.0 * yh) - yl)
        m5 = (r2 + r3) / 2.0
        m4 = (r1 + r2) / 2.0
        m3 = (p + r1) / 2.0
        m2 = (p + s1) / 2.0
        m1 = (s1 + s2) / 2.0
        m0 = (s2 + s3) / 2.0
        return dict(p=p, r1=r1, r2=r2, r3=r3, s1=s1, s2=s2, s3=s3, m5=m5, m4=m4, m3=m3, m2=m2, m1=m1, m0=m0)

    def _support_resistance(self, price, levels):
        segments = [
            (levels["s3"], levels["m0"], levels["s3"], levels["m0"]),
            (levels["m0"], levels["s2"], levels["m0"], levels["s2"]),
            (levels["s2"], levels["m1"], levels["s2"], levels["m1"]),
            (levels["m1"], levels["s1"], levels["m1"], levels["s1"]),
            (levels["s1"], levels["m2"], levels["s1"], levels["m2"]),
            (levels["m2"], levels["p"], levels["m2"], levels["p"]),
            (levels["p"], levels["m3"], levels["p"], levels["m3"]),
            (levels["m3"], levels["r1"], levels["m3"], levels["r1"]),
            (levels["r1"], levels["m4"], levels["r1"], levels["m4"]),
            (levels["m4"], levels["r2"], levels["m4"], levels["r2"]),
            (levels["r2"], levels["m5"], levels["r2"], levels["m5"]),
            (levels["m5"], levels["r3"], levels["s3"], levels["m0"]),
        ]
        for lower, upper, support, resistance in segments:
            if (price - lower) * (price - upper) < 0:
                return support, resistance
        return None, None

    def _initialize_exit_levels(self, stop_price, limit_price):
        self.stop_price = stop_price
        self.limit_price = limit_price

    def _reset_exit_levels(self):
        self.stop_price = None
        self.limit_price = None

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self.close_order = self.close()

    def _check_exit_thresholds(self):
        if not self.position or self.close_order is not None:
            return False
        bar_high = float(self.data0_feed.high[0])
        bar_low = float(self.data0_feed.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and bar_low <= self.stop_price:
                self._submit_close("stop")
                return True
            if self.limit_price is not None and bar_high >= self.limit_price:
                self._submit_close("limit")
                return True
        else:
            if self.stop_price is not None and bar_high >= self.stop_price:
                self._submit_close("stop")
                return True
            if self.limit_price is not None and bar_low <= self.limit_price:
                self._submit_close("limit")
                return True
        return False

    def _update_trailing(self):
        if not self.position or self.p.trailing_stop_pips <= 0:
            return
        close_price = float(self.data0_feed.close[0])
        threshold = (self.p.trailing_stop_pips + self.p.trailing_step_pips) * self.p.point_size
        trail_distance = self.p.trailing_stop_pips * self.p.point_size
        if self.position.size > 0:
            if close_price - self.entry_price > threshold and (self.stop_price is None or self.stop_price < close_price - threshold):
                self.stop_price = close_price - trail_distance
        else:
            if self.entry_price - close_price > threshold and (self.stop_price is None or self.stop_price > close_price + threshold):
                self.stop_price = close_price + trail_distance

    def _ready(self):
        return len(self.h1_feed) > 2 and self.prev_session_ohlc is not None

    def next(self):
        """Update session pivots, manage exits, and open breakout positions when conditions align."""
        self.bar_num += 1
        self._update_session_ohlc()
        if not self._ready():
            return
        if self._check_exit_thresholds():
            return
        if self.position:
            self._update_trailing()
            return
        if self.order is not None:
            return
        levels = self._pivot_levels()
        if levels is None:
            return
        price = float(self.data0_feed.close[0])
        support, resistance = self._support_resistance(price, levels)
        if support is None or resistance is None:
            return
        dif1 = (price - support) / self.p.point_size
        dif2 = (resistance - price) / self.p.point_size
        ext_step = 5 * self.p.point_size
        if dif2 > 14 and self.adx[0] > 20 and self.plus_di[0] > self.plus_di[-1] and self.plus_di[0] > self.minus_di[0] and (self.ma_close[0] - self.ma_open[0]) >= ext_step and self.ma_close[-1] > self.ma_open[-1] and self.osma[0] > self.osma[-1]:
            stop_price = price - self.p.stoploss_pips * self.p.point_size if self.p.stoploss_pips > 0 else None
            if stop_price is not None and stop_price >= price:
                return
            self.order = self.buy(size=max(0.01, float(self.p.fixed_lot)))
            self.active_side = "long"
            self.entry_price = price
            self._initialize_exit_levels(stop_price, resistance)
            return
        if dif1 > 14 and self.adx[0] > 20 and self.minus_di[0] > self.minus_di[-1] and self.plus_di[0] < self.minus_di[0] and (self.ma_open[0] - self.ma_close[0]) >= ext_step and self.ma_open[-1] > self.ma_close[-1] and self.osma[0] < self.osma[-1]:
            stop_price = price + self.p.stoploss_pips * self.p.point_size if self.p.stoploss_pips > 0 else None
            if stop_price is not None and stop_price <= price:
                return
            self.order = self.sell(size=max(0.01, float(self.p.fixed_lot)))
            self.active_side = "short"
            self.entry_price = price
            self._initialize_exit_levels(stop_price, support)

    def notify_order(self, order):
        """Track submitted orders and reset context when entries or closes complete."""
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.order:
                self.entry_price = order.executed.price
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                self.order = None
            elif order == self.close_order:
                self.close_order = None
                self.active_side = None
                self.entry_price = None
                self._reset_exit_levels()
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.order:
                self.order = None
            elif order == self.close_order:
                self.close_order = None

    def notify_trade(self, trade):
        """Aggregate closed-trade counts and reset position state on closure."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self.active_side = None
            self.entry_price = None
            self._reset_exit_levels()


def test_001_0001_mostashar15_pivot() -> None:
    """Migrated regression test for pivot_fibonacci_system/0001_mostashar15_pivot."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    h1_df = _resample(df, "60min")

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.adddata(Mt5PandasFeed(dataname=h1_df, timeframe=bt.TimeFrame.Minutes, compression=60))
    cerebro.addstrategy(MostasHaR15PivotStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 6001
    assert strat.buy_count == 212
    assert strat.sell_count == 175
    assert strat.win_count == 200
    assert strat.loss_count == 187
    assert strat.trade_count == 387
    assert total_trades == 387
    assert abs(final_value - 999163.7) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
