"""Inlined regression test for mean_reversion/0254_0783_scalpel_ea.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
- XAUUSD M15 (primary): 2025-12-03 01:15 to 2026-03-10 09:00
- XAUUSD M30: resampled from M15
- XAUUSD H1: resampled from M15
- XAUUSD H4: resampled from M15

Strategy Principle:
Scalpel EA is a mean-reversion scalping strategy that uses CCI for entry
timing on the M15 chart, with higher timeframe (M30, H1, H4) trend alignment
for filter confirmation. Entries are gated by volatility expansion and
structural break patterns in the higher timeframes.

Strategy Logic:
- On each M15 bar, compute CCI(15) and volatility metrics
- Require bull/bear alignment across M30, H1, H4 (ascending lows for buys,
  descending highs for sells)
- Require volatility expansion (current volume > past volume on directional
  bars) and a 3-bar structural break pattern
- Set fixed stop-loss, take-profit, and optional trailing/reduce logic
- A relaxed entry mode allows less strict conditions when the strict set
  fails to trigger
- Position management: trailing stop adjustment when profit exceeds take-profit,
  time-based exits (live_minutes, reduce_minutes), Friday close filter
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
    """Load an MT5-format CSV file into a Pandas DataFrame.

    Parses tab-separated columns (DATE, TIME, OPEN, HIGH, LOW, CLOSE, TICKVOL, VOL),
    renames them to backtrader convention, and optionally shifts the datetime index.

    Args:
        filepath: Path to the CSV file.
        fromdate: Optional start date filter.
        todate: Optional end date filter.
        bar_shift_minutes: Minutes to shift the datetime index by.

    Returns:
        DataFrame with columns [open, high, low, close, volume, openinterest].
    """
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.read().strip().split("\n")
    cleaned = "\n".join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep="\t")
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"], format="%Y.%m.%d %H:%M:%S")
    df = df.rename(columns={
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low",
        "<CLOSE>": "close", "<TICKVOL>": "volume", "<VOL>": "openinterest",
    })
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest"]]
    df = df.set_index("datetime")
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def resample_frame(df, rule):
    """Resample a DataFrame to a higher timeframe using right-closed aggregation.

    Args:
        df: Source DataFrame with OHLCV data.
        rule: Pandas resample rule string (e.g. '30min', '4h').

    Returns:
        Resampled DataFrame with aggregated OHLCV columns.
    """
    out = df.resample(rule, label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum", "openinterest": "last",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["openinterest"] = out["openinterest"].fillna(0)
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    """PandasData feed configured for MT5-exported CSV column ordering.

    Maps the 0-based DataFrame columns (open=0, high=1, low=2, close=3,
    volume=4, openinterest=5) produced by load_mt5_csv().
    """
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class ScalpelEaStrategy(bt.Strategy):
    """Scalpel EA — CCI-driven mean-reversion scalper with multi-timeframe filters.

    Uses CCI(15) on M15 for entry signals, confirmed by higher timeframe
    (M30, H1, H4) trend alignment and volatility expansion. Includes
    relaxed entry fallback, trailing stop management, and configurable
    time-based exits.
    """
    params = dict(
        lots=-5.0,
        take_profit=30, stop_loss=21, trailing_stop=10,
        cci_period=15, cci_limit=100.0, max_pos=1,
        interval_minutes=0, reduce_minutes=600, live_minutes=0,
        volatility=14, threshold_pips=0.1,
        friday_close=22, spread_limit=100.0,
        point=0.01, digits_adjust=10,
        min_lot=0.01, lot_step=0.01, max_lot=100.0, margin_per_lot=250.0,
        price_digits=2,
        relaxed_entries=True,
    )

    def __init__(self):
        """Initialize indicators, runtime counters, and order/trade state."""
        self.base = self.datas[0]
        self.m30 = self.datas[1]
        self.h1 = self.datas[2]
        self.h4 = self.datas[3]
        self.cci = bt.indicators.CCI(self.base, period=self.p.cci_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.stop_price = None
        self.take_profit_price = None
        self.entry_dt = None
        self.last_entry_dt = None
        self.current_side = None

    def _pip_value(self):
        return self.p.point * self.p.digits_adjust

    def _threshold_price(self):
        return self.p.threshold_pips * self._pip_value()

    def _spread_price(self):
        return self.p.spread_limit * self._pip_value()

    def _enough_history(self):
        lookback = max(abs(self.p.volatility) * 2 + 5, self.p.cci_period + 5)
        return len(self.base) >= lookback and len(self.m30) >= 3 and len(self.h1) >= 3 and len(self.h4) >= 2

    def _floor_lot(self, value):
        stepped = math.floor(value / self.p.lot_step) * self.p.lot_step
        stepped = max(0.0, min(stepped, self.p.max_lot))
        return round(stepped, 2)

    def _use_lots(self):
        lots = self.p.lots
        if lots < 0:
            volume = lots
            while volume <= -1:
                volume /= 100.0
            margin_lots_min = self.p.margin_per_lot * self.p.min_lot
            free_margin = self.broker.get_cash()
            if margin_lots_min <= 0 or margin_lots_min > free_margin:
                return 0.0
            count_lots_min = int(free_margin / margin_lots_min)
            volume = abs(volume) * count_lots_min * self.p.min_lot
            checked = self._floor_lot(volume)
            return checked if checked >= self.p.min_lot else 0.0
        checked = self._floor_lot(lots)
        return checked if checked >= self.p.min_lot else 0.0

    def _current_dt(self):
        return bt.num2date(self.base.datetime[0])

    def _position_age_minutes(self):
        if self.entry_dt is None:
            return 0
        delta = self._current_dt() - self.entry_dt
        return max(0, int(delta.total_seconds() // 60))

    def _manage_open_position(self):
        if not self.position:
            return False
        dt = self._current_dt()
        price = float(self.base.close[0])
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        age_minutes = self._position_age_minutes()
        should_close = False
        if self.p.live_minutes > 0:
            should_close = age_minutes > self.p.live_minutes
        if not should_close and self.p.friday_close > 0:
            should_close = dt.weekday() == 4 and dt.hour > self.p.friday_close
        reduce_steps = 0
        if self.p.reduce_minutes > 0:
            reduce_steps = age_minutes // self.p.reduce_minutes
        reduce_price = reduce_steps * self._pip_value()
        if self.position.size > 0:
            if not should_close and self.take_profit_price is not None and price > self.take_profit_price - reduce_price:
                should_close = True
            if should_close or (self.stop_price is not None and low <= self.stop_price) or (self.take_profit_price is not None and high >= self.take_profit_price):
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and price - self.position.price > self.p.take_profit * self.p.point:
                new_stop = round(price - self.p.take_profit * self.p.point, self.p.price_digits)
                if self.stop_price is None or new_stop > self.stop_price:
                    self.stop_price = new_stop
        else:
            if not should_close and self.take_profit_price is not None and price < self.take_profit_price + reduce_price:
                should_close = True
            if should_close or (self.stop_price is not None and high >= self.stop_price) or (self.take_profit_price is not None and low <= self.take_profit_price):
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and self.position.price - price > self.p.take_profit * self.p.point:
                new_stop = round(price + self.p.take_profit * self.p.point, self.p.price_digits)
                if self.stop_price is None or new_stop < self.stop_price:
                    self.stop_price = new_stop
        return False

    def _count_side_exposure(self):
        if not self.position:
            return 0, 0
        return (1, 0) if self.position.size > 0 else (0, 1)

    def _cci_flags(self):
        cci_value = float(self.cci[-1])
        if self.p.cci_limit > 0:
            ccib = 0 < cci_value < self.p.cci_limit
            ccis = -self.p.cci_limit < cci_value < 0
        else:
            ccib = cci_value > -self.p.cci_limit
            ccis = cci_value < self.p.cci_limit
        return cci_value, ccib, ccis

    def _volatility_stats(self):
        threshold = self._threshold_price()
        v = self.p.volatility
        if v > 0:
            vol1u = vol1d = volu = vold = 0.0
            for i in range(v, v * 2):
                h = float(self.base.close[-i])
                l = float(self.base.open[-i])
                tick = float(self.base.volume[-i])
                if h > l + threshold:
                    vol1u += tick
                elif l > h + threshold:
                    vol1d += tick
            for i in range(1, v):
                h = float(self.base.close[-i])
                l = float(self.base.open[-i])
                tick = float(self.base.volume[-i])
                if h > l + threshold:
                    volu += tick
                elif l > h + threshold:
                    vold += tick
            h0 = float(self.base.close[0])
            l0 = float(self.base.open[0])
            tick0 = float(self.base.volume[0])
            if h0 > l0 + threshold:
                vol0u = volu + tick0
                vol0d = vold
            elif l0 > h0 + threshold:
                vol0d = vold + tick0
                vol0u = volu
            else:
                vol0u = volu
                vol0d = vold
            return vol0u, vol0d, vol1u, vol1d
        if v < 0:
            v = abs(v)
            vol1u = volu = 0.0
            for i in range(v, v * 2):
                h = float(self.base.close[-i])
                l = float(self.base.open[-i])
                if abs(h - l) > threshold:
                    vol1u += float(self.base.volume[-i])
            for i in range(1, v):
                h = float(self.base.close[-i])
                l = float(self.base.open[-i])
                if abs(h - l) >= threshold:
                    volu += float(self.base.volume[-i])
            vol1d = vol1u
            vold = volu
            h0 = float(self.base.close[0])
            l0 = float(self.base.open[0])
            vol0u = volu + float(self.base.volume[0]) if abs(h0 - l0) >= threshold else volu
            vol0d = vol0u
            return vol0u, vol0d, vol1u, vol1d
        h0 = float(self.base.close[0])
        l0 = float(self.base.open[0])
        vol0u = float(self.base.volume[0]) if abs(h0 - l0) >= threshold else 0.0
        return vol0u, vol0u, vol0u, vol0u

    def _entry_filters(self):
        cci_value, ccib, ccis = self._cci_flags()
        if not ccib and not ccis:
            return None
        high4 = float(self.h4.high[0])
        low4 = float(self.h4.low[0])
        high4s = float(self.h4.high[-1])
        low4s = float(self.h4.low[-1])
        high1 = float(self.h1.high[0])
        low1 = float(self.h1.low[0])
        high1s = float(self.h1.high[-1])
        low1s = float(self.h1.low[-1])
        high30 = float(self.m30.high[0])
        low30 = float(self.m30.low[0])
        high30s = float(self.m30.high[-1])
        low30s = float(self.m30.low[-1])
        vol0u, vol0d, vol1u, vol1d = self._volatility_stats()
        price = float(self.base.close[0])
        buy_signal = (
            ccib and
            low4 > low4s and low1 > low1s and low30 > low30s and
            price > float(self.base.high[-1]) and
            vol0u > vol1u and vol1u > 0 and
            float(self.base.high[-2]) > float(self.base.high[-1]) and
            float(self.base.high[-3]) > float(self.base.high[-2])
        )
        sell_signal = (
            high4 < high4s and high1 < high1s and high30 < high30s and
            price < float(self.base.low[-1]) and
            vol0d > vol1d and vol1d > 0 and
            float(self.base.low[-2]) < float(self.base.low[-1]) and
            float(self.base.low[-3]) < float(self.base.low[-2]) and
            ((self.p.cci_limit > 0 and cci_value < 0 and cci_value > -self.p.cci_limit) or (self.p.cci_limit < 0 and cci_value < self.p.cci_limit))
        )
        if self.p.relaxed_entries and not (buy_signal or sell_signal):
            buy_signal = ccib and price > float(self.base.close[-1]) and vol0u >= vol1u
            sell_signal = ccis and price < float(self.base.close[-1]) and vol0d >= vol1d
        return dict(cci=cci_value, buy_signal=buy_signal, sell_signal=sell_signal)

    def next(self):
        """Execute the main trading logic on each M15 bar.

        Checks enough history, manages any open position (stop/tp/time exits),
        enforces position limits and interval cooldowns, evaluates entry filters
        (CCI + multi-tf alignment + volatility), and submits buy/sell orders
        when conditions are met.
        """
        self.bar_num += 1
        if not self._enough_history():
            return
        if self.entry_order is not None:
            return
        if self._manage_open_position():
            return
        buys, sells = self._count_side_exposure()
        if abs(buys - sells) >= self.p.max_pos:
            return
        dt = self._current_dt()
        if dt.weekday() == 4:
            return
        if self.p.interval_minutes > 0 and self.last_entry_dt is not None:
            if (dt - self.last_entry_dt).total_seconds() < self.p.interval_minutes * 60:
                return
        if float(self.base.high[0]) - float(self.base.low[0]) > self._spread_price():
            return
        signals = self._entry_filters()
        if not signals:
            return
        lots = self._use_lots()
        if lots <= 0:
            return
        price = float(self.base.close[0])
        if signals["buy_signal"]:
            self.stop_price = round(price - self.p.stop_loss * self.p.point, self.p.price_digits)
            self.take_profit_price = round(price + self.p.take_profit * self.p.point, self.p.price_digits)
            self.current_side = "buy"
            self.last_entry_dt = dt
            self.entry_order = self.buy(size=lots)
        elif signals["sell_signal"]:
            self.stop_price = round(price + self.p.stop_loss * self.p.point, self.p.price_digits)
            self.take_profit_price = round(price - self.p.take_profit * self.p.point, self.p.price_digits)
            self.current_side = "sell"
            self.last_entry_dt = dt
            self.entry_order = self.sell(size=lots)

    def notify_order(self, order):
        """Update strategy state after entry/exit orders leave pending status."""
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                self.entry_dt = self._current_dt()
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
                self.entry_dt = None
                self.current_side = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            if not self.position:
                self.stop_price = None
                self.take_profit_price = None
                self.current_side = None
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        """Update trade outcome counters when a closed trade is reported."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_253_0254_0783_scalpel_ea() -> None:
    """Migrated regression test for mean_reversion/0254_0783_scalpel_ea."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    m30_df = resample_frame(df, "30min")
    h1_df = resample_frame(df, "60min")
    h4_df = resample_frame(df, "4h")

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.adddata(Mt5PandasFeed(dataname=m30_df, timeframe=bt.TimeFrame.Minutes, compression=30))
    cerebro.adddata(Mt5PandasFeed(dataname=h1_df, timeframe=bt.TimeFrame.Minutes, compression=60))
    cerebro.adddata(Mt5PandasFeed(dataname=h4_df, timeframe=bt.TimeFrame.Minutes, compression=240))
    cerebro.addstrategy(ScalpelEaStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 6118
    assert strat.buy_count == 266
    assert strat.sell_count == 184
    assert strat.win_count == 215
    assert strat.loss_count == 235
    assert strat.trade_count == 450
    assert total_trades == 450
    assert abs(final_value - 1695.87) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
