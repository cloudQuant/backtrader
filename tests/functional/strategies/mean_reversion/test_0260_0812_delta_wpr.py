"""Inlined regression test for mean_reversion/0260_0812_delta_wpr.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
- XAUUSD M15 (primary): 2025-12-03 01:15 to 2026-03-10 09:00
- XAUUSD H4 (signal): resampled from M15

Strategy Principle:
Delta WPR is a dual-timeframe mean-reversion strategy that uses the
difference between two Williams %R periods (fast 14 vs slow 30) to detect
divergence/convergence. A color signal encodes the relative position and
direction of the two WPR lines relative to a configurable level threshold.

Strategy Logic:
- DeltaWPR indicator computes WPR(14) and WPR(30) on H4 data
- color=0 (buy): WPR(30) > level AND fast WPR > slow WPR (upward momentum)
- color=2 (sell): WPR(30) < -100-level AND fast WPR < slow WPR (downward)
- color=1: neutral (default)
- Entry: transition into color 0 or 2 triggers a buy or sell
- Exit: transition to the opposite color closes the current position
- Fixed stop-loss/take-profit at configured point distances
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
    """Load an MT5-format CSV file into a Pandas DataFrame.

    Strips quotes, handles empty lines, and sorts the resulting index.

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
    cleaned = "\n".join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep="\t")
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"], format="%Y.%m.%d %H:%M:%S")
    df = df.rename(columns={
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low",
        "<CLOSE>": "close", "<TICKVOL>": "volume", "<VOL>": "openinterest",
    })
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest"]]
    df = df.set_index("datetime").sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    """PandasData feed configured for MT5-exported CSV column ordering."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class DeltaWPR(bt.Indicator):
    """Delta Williams %R — WPR spread and color-coded momentum regime.

    Computes two WPRs with different periods and derives:
    - delta: WPR(fast) - WPR(slow), measuring short-term vs medium-term
    - color: 0=bullish alignment, 1=neutral, 2=bearish alignment
    """
    lines = ("color", "delta")
    params = dict(wpr_period1=14, wpr_period2=30, level=-50)

    def __init__(self):
        """Create fast/slow Williams %R indicators and precompute level thresholds."""
        self.addminperiod(max(int(self.p.wpr_period1), int(self.p.wpr_period2)) + 3)
        self.wpr1 = bt.indicators.WilliamsR(self.data, period=int(self.p.wpr_period1))
        self.wpr2 = bt.indicators.WilliamsR(self.data, period=int(self.p.wpr_period2))
        self.max_level = int(self.p.level)
        self.min_level = int(-100 - self.p.level)

    def next(self):
        """Compute delta WPR and color signal for the current bar."""
        w1 = float(self.wpr1[0])
        w2 = float(self.wpr2[0])
        self.lines.delta[0] = w1 - w2
        color = 1.0
        if w2 > self.max_level and w1 > w2:
            color = 0.0
        if w2 < self.min_level and w1 < w2:
            color = 2.0
        self.lines.color[0] = color


class ExpDeltaWPRStrategy(bt.Strategy):
    """Dual-timeframe strategy trading color transitions from DeltaWPR on H4 data."""
    params = dict(
        wpr_period1=14,
        wpr_period2=30,
        level=-50,
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
        """Initialize data handles, indicator, and run-time counters/state."""
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.ind = DeltaWPR(
            self.signal_data,
            wpr_period1=self.p.wpr_period1,
            wpr_period2=self.p.wpr_period2,
            level=self.p.level,
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
        """React on fresh signal changes and place directional market orders."""
        self.bar_num += 1
        if self._check_exit_levels():
            return
        sb = max(int(self.p.signal_bar) - 1, 0)
        if len(self.signal_data) < max(int(self.p.wpr_period1), int(self.p.wpr_period2)) + sb + 3:
            return
        if len(self.signal_data) == self._last_signal_len:
            return
        self._last_signal_len = len(self.signal_data)
        c0 = float(self.ind.color[-sb]) if sb else float(self.ind.color[0])
        c1 = float(self.ind.color[-(sb + 1)])
        buy_open = c1 == 0.0 and c0 != 0.0 and self.p.buy_pos_open
        sell_open = c1 == 2.0 and c0 != 2.0 and self.p.sell_pos_open
        buy_close = sell_open and self.p.buy_pos_close
        sell_close = buy_open and self.p.sell_pos_close
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
        """Track open/close trade events and win/loss statistics."""
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
    out = df.resample(
        f"{int(minutes)}min", label="right", closed="right",
    ).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum", "openinterest": "sum",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["openinterest"] = out["openinterest"].fillna(0)
    return out


def test_261_0260_0812_delta_wpr() -> None:
    """Migrated regression test for mean_reversion/0260_0812_delta_wpr."""
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
        ExpDeltaWPRStrategy,
        wpr_period1=14, wpr_period2=30, level=-50,
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

    assert strat.bar_num == 5632, f"bar_num: expected=5632, got={strat.bar_num}"
    assert strat.buy_count == 9, f"buy_count: expected=9, got={strat.buy_count}"
    assert strat.sell_count == 4, f"sell_count: expected=4, got={strat.sell_count}"
    assert strat.win_count == 6, f"win_count: expected=6, got={strat.win_count}"
    assert strat.loss_count == 7, f"loss_count: expected=7, got={strat.loss_count}"
    assert strat.trade_count == 13, f"trade_count: expected=13, got={strat.trade_count}"
    assert total_trades == 13, f"total_trades: expected=13, got={total_trades}"
    assert abs(final_value - 1000693.4) < 0.01, f"final_value: expected=1000693.4, got={final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
