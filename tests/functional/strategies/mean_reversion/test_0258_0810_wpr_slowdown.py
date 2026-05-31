"""Inlined regression test for mean_reversion/0258_0810_wpr_slowdown.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
- XAUUSD M15 (primary): 2025-12-03 01:15 to 2026-03-10 09:00
- XAUUSD H4 (signal): resampled from M15

Strategy Principle:
WPR Slowdown is a mean-reversion strategy that detects Williams %R reaching
extreme overbought/oversold levels with a "slowdown" condition (the %R line
stops moving rapidly, suggesting impending reversal). Entries are filtered
through a dual-timeframe setup: price action on M15 but indicator computed
on the H4 signal chart.

Strategy Logic:
- A custom WPRSlowdown indicator computes Williams %R(12) on H4 data
- When %R >= level_max (-20), a buy signal fires if slowdown is detected
  (|wpr[0] - wpr[-1]| < 1.0) — the line is flattening at the extreme
- When %R <= level_min (-80), a sell signal fires with the same slowdown check
- Signal lines store ATR-derived price levels (low - 3/8 ATR for buys,
  high + 3/8 ATR for sells) as trigger/confluence levels
- The strategy tracks signal freshness (only reacts once per new H4 bar),
  manages stop-loss / take-profit exits at fixed point distances, and
  tracks buy/sell/wins/losses for assertion verification
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
    """Load an MT5-format CSV file into a Pandas DataFrame with deduplication.

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


class WPRSlowdown(bt.Indicator):
    """Williams %R Slowdown — detects %R extreme flattening as reversal signal.

    Fires buy when %R >= level_max (overbought) and the change between
    consecutive bars is small (slowdown), indicating exhaustion. Fires sell
    symmetrically at level_min (oversold). Signal lines store ATR-scaled
    price levels.
    """
    lines = ("sell", "buy")
    params = dict(wpr_period=12, level_max=-20.0, level_min=-80.0, seek_slowdown=True)

    def __init__(self):
        """Set Williams %R and ATR indicators used by slowdown logic."""
        self.addminperiod(max(int(self.p.wpr_period) + 2, 18))
        self.wpr = bt.indicators.WilliamsR(self.data, period=int(self.p.wpr_period))
        self.atr = bt.indicators.ATR(self.data, period=15)

    def next(self):
        """Compute WPR slowdown signal for the current bar.

        Sets buy/sell lines to ATR-derived price levels when the WPR extreme
        + slowdown condition is met, or NaN otherwise.
        """
        self.lines.buy[0] = float("nan")
        self.lines.sell[0] = float("nan")
        w0 = float(self.wpr[0])
        w1 = float(self.wpr[-1])
        atr = float(self.atr[0])
        if w0 >= float(self.p.level_max):
            if (not self.p.seek_slowdown) or abs(w1 - w0) < 1.0:
                self.lines.buy[0] = float(self.data.low[0]) - atr * 3.0 / 8.0
        if w0 <= float(self.p.level_min):
            if (not self.p.seek_slowdown) or abs(w1 - w0) < 1.0:
                self.lines.sell[0] = float(self.data.high[0]) + atr * 3.0 / 8.0


class ExpWPRSlowdownStrategy(bt.Strategy):
    """WPR Slowdown strategy — trades WPR extreme + slowdown signals on H4.

    Receives WPRSlowdown indicator signals from the H4 signal data and
    executes M15 entries with fixed stop-loss/take-profit. Tracks signal
    freshness (one reaction per new H4 bar), allows separate enable/disable
    of buy and sell opens and closes.
    """
    params = dict(
        wpr_period=12,
        level_max=-20.0,
        level_min=-80.0,
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
        """Initialize signal references and strategy state for one-trade-cycle flow."""
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.ind = WPRSlowdown(
            self.signal_data,
            wpr_period=self.p.wpr_period,
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
        """Execute the main trading logic on each M15 bar.

        Checks stop-loss/take-profit exit levels first, then evaluates
        WPRSlowdown indicator signals from the H4 data. Only reacts to
        fresh signals (once per new H4 bar). Manages open/close polarity
        according to configured buy/sell flags and signal state.
        """
        self.bar_num += 1
        if self._check_exit_levels():
            return
        sb = max(int(self.p.signal_bar) - 1, 0)
        if len(self.signal_data) < max(int(self.p.wpr_period) + 2, 18) + sb:
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
        """Track trade open and close events for win/loss/buy/sell counters."""
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


def test_259_0258_0810_wpr_slowdown() -> None:
    """Migrated regression test for mean_reversion/0258_0810_wpr_slowdown."""
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
        ExpWPRSlowdownStrategy,
        wpr_period=12, level_max=-20.0, level_min=-80.0, seek_slowdown=True,
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

    assert strat.bar_num == 5860, f"bar_num: expected=5860, got={strat.bar_num}"
    assert strat.buy_count == 15, f"buy_count: expected=15, got={strat.buy_count}"
    assert strat.sell_count == 2, f"sell_count: expected=2, got={strat.sell_count}"
    assert strat.win_count == 7, f"win_count: expected=7, got={strat.win_count}"
    assert strat.loss_count == 10, f"loss_count: expected=10, got={strat.loss_count}"
    assert strat.trade_count == 17, f"trade_count: expected=17, got={strat.trade_count}"
    assert total_trades == 17, f"total_trades: expected=17, got={total_trades}"
    assert abs(final_value - 999953.0) < 0.01, f"final_value: expected=999953.0, got={final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
