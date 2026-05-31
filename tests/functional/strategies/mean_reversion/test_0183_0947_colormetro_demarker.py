"""Inlined regression test for mean_reversion/0183_0947_colormetro_demarker.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
    XAUUSD_M15.csv (Gold, M15, 2025-12-03 01:15 to 2026-03-10 09:00).
    A second H8 feed (480 min) is resampled from the base M15 data for signal
    computation, implementing a dual-timeframe structure.

Strategy Principle:
    DeMarker (DeM) oscillator computes the ratio of upward price pressure to
    total price pressure over a lookback window. The ColorMetroDeMarker
    indicator derives fast and slow adaptive trend lines from the DeM value,
    using step-based channel logic. Trend direction is determined by DeM
    exceeding or falling below channel bounds.

Strategy Logic:
    The ColorMetroDeMarkerStrategy compares fast_line relative to slow_line
    on the H8 signal bar: a bullish crossover triggers a buy, a bearish one a
    sell. Positions are managed with fixed stop-loss and take-profit levels,
    and a direction-based reversal mechanism. Assertions verify trade counts,
    win/loss totals, bar count, and final portfolio value.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Load an MT5-exported CSV into a Pandas DataFrame with standard OHLC columns."""
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


def resample_h8(df):
    """Resample a DataFrame from M15 to H8 (480 min) using OHLCV aggregation."""
    out = df.resample("480min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum", "openinterest": "last", "spread": "last",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["openinterest"] = out["openinterest"].fillna(0)
    out["spread"] = out["spread"].fillna(0)
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    """PandasData feed for MT5-exported CSV with an extra spread line."""
    lines = ("spread",)
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5), ("spread", 6),
    )


class DeMarkerIndicator(bt.Indicator):
    """DeMarker indicator (custom — not built into bt.indicators)."""
    lines = ("dem",)
    params = (("period", 14),)

    def __init__(self):
        """Set minimum period to period + 1 for valid DeM computation."""
        self.addminperiod(self.p.period + 1)

    def next(self):
        """Compute DeM = sum(max(high-high_prev,0)) / (sum(max(high-high_prev,0)) + sum(max(low_prev-low,0)))."""
        de_max_sum = 0.0
        de_min_sum = 0.0
        for i in range(self.p.period):
            high_now = float(self.data.high[-i])
            high_prev = float(self.data.high[-(i + 1)])
            low_now = float(self.data.low[-i])
            low_prev = float(self.data.low[-(i + 1)])
            de_max_sum += max(high_now - high_prev, 0.0)
            de_min_sum += max(low_prev - low_now, 0.0)
        denom = de_max_sum + de_min_sum
        if denom == 0:
            self.lines.dem[0] = 0.0
        else:
            self.lines.dem[0] = de_max_sum / denom


class ColorMetroDeMarkerIndicator(bt.Indicator):
    """Colour Metro DeMarker indicator: derives fast/slow adaptive trend lines from the DeM oscillator."""
    lines = ("fast_line", "slow_line", "demarker")
    params = dict(period_demarker=7, step_size_fast=5, step_size_slow=15)

    def __init__(self):
        """Initialize DeMarker instance, set minperiod, reset channel tracking vars."""
        self.dem = DeMarkerIndicator(self.data, period=int(self.p.period_demarker))
        self.addminperiod(int(self.p.period_demarker) + 3)
        self._fmin1 = 999999.0
        self._fmax1 = -999999.0
        self._smin1 = 999999.0
        self._smax1 = -999999.0
        self._ftrend = 0
        self._strend = 0

    def next(self):
        """Compute fast_line, slow_line and demarker from DeM value using step-based channel logic."""
        dem0 = float(self.dem[0]) * 100.0
        fmax0 = dem0 + 2.0 * float(self.p.step_size_fast)
        fmin0 = dem0 - 2.0 * float(self.p.step_size_fast)
        if dem0 > self._fmax1:
            self._ftrend = 1
        if dem0 < self._fmin1:
            self._ftrend = -1
        if self._ftrend > 0 and fmin0 < self._fmin1:
            fmin0 = self._fmin1
        if self._ftrend < 0 and fmax0 > self._fmax1:
            fmax0 = self._fmax1
        smax0 = dem0 + 2.0 * float(self.p.step_size_slow)
        smin0 = dem0 - 2.0 * float(self.p.step_size_slow)
        if dem0 > self._smax1:
            self._strend = 1
        if dem0 < self._smin1:
            self._strend = -1
        if self._strend > 0 and smin0 < self._smin1:
            smin0 = self._smin1
        if self._strend < 0 and smax0 > self._smax1:
            smax0 = self._smax1
        fast_line = fmin0 + float(self.p.step_size_fast) if self._ftrend > 0 else fmax0 - float(self.p.step_size_fast)
        slow_line = smin0 + float(self.p.step_size_slow) if self._strend > 0 else smax0 - float(self.p.step_size_slow)
        self.lines.fast_line[0] = fast_line
        self.lines.slow_line[0] = slow_line
        self.lines.demarker[0] = dem0
        self._fmin1 = fmin0
        self._fmax1 = fmax0
        self._smin1 = smin0
        self._smax1 = smax0


class ColorMetroDeMarkerStrategy(bt.Strategy):
    """Trading strategy that enters positions on ColorMetroDeMarker fast/slow line crossovers with SL/TP."""
    params = dict(
        fixed_lot=0.1, risk_percent=0.0, point=0.01,
        stop_loss_points=1000, take_profit_points=2000,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
        period_demarker=7, step_size_fast=5, step_size_slow=15,
        signal_bar=1, lot_min=0.01, lot_step=0.01, lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        """Initialize data references, indicator, counters, and entry/risk state variables."""
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[-1]
        self.indicator = ColorMetroDeMarkerIndicator(
            self.signal_feed,
            period_demarker=self.p.period_demarker,
            step_size_fast=self.p.step_size_fast,
            step_size_slow=self.p.step_size_slow,
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
        self.pending_entry_direction = 0
        self.pending_reverse_direction = 0
        self.entry_side = None
        self.last_signal_dt = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.warmup = int(self.p.period_demarker) + int(self.p.signal_bar) + 8

    def _round_size(self, size):
        bounded = min(max(size, self.p.lot_min), self.p.lot_max)
        steps = round(bounded / self.p.lot_step)
        return min(max(steps * self.p.lot_step, self.p.lot_min), self.p.lot_max)

    def _position_size(self):
        if self.p.fixed_lot > 0:
            return self._round_size(self.p.fixed_lot)
        return self._round_size(self.p.lot_min)

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

    def _line_at(self, line, shift):
        idx = max(int(shift) - 1, 0)
        if len(line.array) <= idx:
            return None
        return float(line[-idx] if idx else line[0])

    def next(self):
        """Bar-by-bar logic: detect fast/slow crossovers on signal bar, enter/exit positions with SL/TP."""
        self.bar_num += 1
        signal_dt = bt.num2date(self.signal_feed.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        if len(self.signal_feed) < self.warmup:
            return
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        fast_now = self._line_at(self.indicator.fast_line, int(self.p.signal_bar))
        slow_now = self._line_at(self.indicator.slow_line, int(self.p.signal_bar))
        fast_prev = self._line_at(self.indicator.fast_line, int(self.p.signal_bar) + 1)
        slow_prev = self._line_at(self.indicator.slow_line, int(self.p.signal_bar) + 1)
        if None in (fast_now, slow_now, fast_prev, slow_prev):
            return
        self.last_signal_dt = signal_dt
        buy_open = self.p.buy_pos_open and fast_now > slow_now and fast_prev <= slow_prev
        sell_open = self.p.sell_pos_open and fast_now < slow_now and fast_prev >= slow_prev
        if not buy_open and not sell_open and not self.position:
            buy_open = self.p.buy_pos_open and fast_now > slow_now
            sell_open = self.p.sell_pos_open and fast_now < slow_now
        sell_close = self.p.sell_pos_close and fast_now > slow_now
        buy_close = self.p.buy_pos_close and fast_now < slow_now
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
        """Track order lifecycle: count completions/rejections, set entry risk, handle reversals."""
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
        """Track trade outcomes: win/loss count and clear risk on close."""
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


def test_182_0183_0947_colormetro_demarker() -> None:
    """Migrated regression test for mean_reversion/0183_0947_colormetro_demarker."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    h8_df = resample_h8(df)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.adddata(Mt5PandasFeed(dataname=h8_df, timeframe=bt.TimeFrame.Minutes, compression=480))
    cerebro.addstrategy(ColorMetroDeMarkerStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 5832
    assert strat.buy_count == 67
    assert strat.sell_count == 77
    assert strat.win_count == 70
    assert strat.loss_count == 73
    assert strat.trade_count == 143
    assert total_trades == 143
    assert abs(final_value - 1002544.9) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
