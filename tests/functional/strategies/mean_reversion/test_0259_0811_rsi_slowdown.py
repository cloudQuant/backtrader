"""Inlined regression test for mean_reversion/0259_0811_rsi_slowdown.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
- XAUUSD M15 (primary): 2025-12-03 01:15 to 2026-03-10 09:00
- XAUUSD H4 (signal): resampled from M15

Strategy Principle:
RSI Slowdown is a dual-timeframe mean-reversion strategy that detects RSI(2)
reaching extreme levels with a flattening/slowdown condition. It mirrors the
WPR Slowdown approach but uses RSI instead of Williams %R as the oscillator,
making it more sensitive to short-term momentum exhaustion.

Strategy Logic:
- A custom RSISlowdown indicator computes RSI(2) on H4 data
- Buy signal: RSI >= level_max (90, overbought) with |rsi[0] - rsi[-1]| < 1.0
  (slowdown/flattening), suggesting upward momentum is exhausted
- Sell signal: RSI <= level_min (10, oversold) with the same slowdown condition
- Signal lines store ATR-scaled price levels (low - 3/8 ATR for buys,
  high + 3/8 ATR for sells)
- The strategy fires once per new H4 bar, with stop-loss/take-profit at
  fixed point distances, configurable buy/sell open/close gating
"""
from __future__ import annotations
import backtrader as bt

import datetime
import math
from pathlib import Path

import pytest
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M15.csv"


class Mt5PandasFeed(bt.feeds.PandasData):
    """PandasData feed configured for MT5-exported CSV column ordering."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class ExpRSISlowdownStrategy(bt.Strategy):
    """RSI Slowdown strategy — trades RSI extreme + slowdown signals on H4.

    Receives RSISlowdown indicator signals from the H4 signal data and
    executes M15 entries with fixed stop-loss/take-profit. Tracks signal
    freshness (one reaction per new H4 bar) and supports configurable
    buy/sell open and close gating.
    """
    params = dict(
        rsi_period=2,
        level_max=90.0,
        level_min=10.0,
        seek_slowdown=True,
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        fixed_lot=0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        """Initialize signal handles, counters, and position tracking state."""
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.ind = bt.indicators.RSISlowdown(
            self.signal_data,
            rsi_period=self.p.rsi_period,
            level_max=self.p.level_max,
            level_min=self.p.level_min,
            seek_slowdown=self.p.seek_slowdown,
        )
        self.signal_count = 0
        self.trade_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.bar_num = 0
        self._position_was_open = False
        self._last_signal_len = 0

    def _has(self, line, offset):
        v = float(line[-offset]) if offset else float(line[0])
        return not math.isnan(v) and v != 0.0

    def _check_exit_levels(self):
        if not self.position:
            return False
        cp = float(self.base.close[0])
        pv = float(self.p.point)
        ep = float(self.position.price)
        sd = self.p.stop_loss_points * pv
        td = self.p.take_profit_points * pv
        if self.position.size > 0 and (cp <= ep - sd or cp >= ep + td):
            self.close()
            return True
        if self.position.size < 0 and (cp >= ep + sd or cp <= ep - td):
            self.close()
            return True
        return False

    def next(self):
        """Evaluate fresh RSI slowdown signals and run entry/exit management."""
        self.bar_num += 1
        if self._check_exit_levels():
            return
        sb = max(int(self.p.signal_bar) - 1, 0)
        if len(self.signal_data) < max(int(self.p.rsi_period) + 2, 18) + sb:
            return
        if len(self.signal_data) == self._last_signal_len:
            return
        self._last_signal_len = len(self.signal_data)
        buy_open = self._has(self.ind.buy, sb) and self.p.buy_pos_open
        sell_open = self._has(self.ind.sell, sb) and self.p.sell_pos_open
        buy_close = sell_open and self.p.buy_pos_close
        sell_close = buy_open and self.p.sell_pos_close
        if (self.p.buy_pos_open and self.p.buy_pos_close) or (self.p.sell_pos_open and self.p.sell_pos_close):
            if not buy_close and self.p.sell_pos_close:
                for bar in range(sb + 1, len(self.signal_data) - 1):
                    if self._has(self.ind.buy, bar):
                        sell_close = True
                        break
            if not sell_close and self.p.buy_pos_close:
                for bar in range(sb + 1, len(self.signal_data) - 1):
                    if self._has(self.ind.sell, bar):
                        buy_close = True
                        break
        if sell_close and self.position.size < 0:
            self.close()
        if buy_close and self.position.size > 0:
            self.close()
        if buy_open and self.position.size <= 0:
            self.signal_count += 1
            self.buy(size=float(self.p.fixed_lot))
        if sell_open and self.position.size >= 0:
            self.signal_count += 1
            self.sell(size=float(self.p.fixed_lot))

    def notify_trade(self, trade):
        """Track open/close trade events and aggregate win/loss statistics."""
        if trade.isopen and not self._position_was_open:
            self._position_was_open = True
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False


def _build_signal_frame(df, minutes):
    """Resample a DataFrame to a higher timeframe for signal computation.

    Args:
        df: Source minute-level DataFrame.
        minutes: Target bar duration in minutes.

    Returns:
        Resampled DataFrame with OHLCV aggregation.
    """
    out = df.resample(
        f"{int(minutes)}min", label="right", closed="right",
    ).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum", "openinterest": "sum",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["openinterest"] = out["openinterest"].fillna(0)
    return out


def test_260_0259_0811_rsi_slowdown() -> None:
    """Migrated regression test for mean_reversion/0259_0811_rsi_slowdown."""
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
    cerebro.addstrategy(
        ExpRSISlowdownStrategy,
        rsi_period=2, level_max=90.0, level_min=10.0, seek_slowdown=True,
        signal_bar=1, stop_loss_points=1000, take_profit_points=2000,
        fixed_lot=0.1, point=0.01,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
    )
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    # Captured-from-canonical-hook expected values
    assert strat.bar_num == 5860, f"bar_num: expected=5860, got={strat.bar_num}"
    assert strat.buy_count == 20, f"buy_count: expected=20, got={strat.buy_count}"
    assert strat.sell_count == 1, f"sell_count: expected=1, got={strat.sell_count}"
    assert strat.win_count == 7, f"win_count: expected=7, got={strat.win_count}"
    assert strat.loss_count == 14, f"loss_count: expected=14, got={strat.loss_count}"
    assert strat.trade_count == 21, f"trade_count: expected=21, got={strat.trade_count}"
    assert total_trades == 21, f"total_trades: expected=21, got={total_trades}"
    assert abs(final_value - 999575.5000000003) < 0.01, f"final_value: expected=999575.50, got={final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
