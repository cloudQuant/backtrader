"""Inlined regression test for mean_reversion/0261_0813_delta_mfi.

Self-contained single-file test (manually authored). Runs with runonce=True only.
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
    """Load MT5-exported CSV data file and return a Pandas DataFrame."""
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
    """Custom PandasData feed for MT5-exported CSV data."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class MoneyFlowIndex(bt.Indicator):
    """Inlined MFI indicator (not built into bt.indicators)."""
    lines = ("mfi",)
    params = (("period", 14),)

    def __init__(self):
        """Initialize the MFI indicator and set the minimum period."""
        self.addminperiod(self.p.period + 1)

    def next(self):
        """Compute the Money Flow Index for the current bar."""
        positive_flow = 0.0
        negative_flow = 0.0
        for i in range(self.p.period):
            curr_tp = (float(self.data.high[-i]) + float(self.data.low[-i]) + float(self.data.close[-i])) / 3.0
            prev_tp = (float(self.data.high[-i - 1]) + float(self.data.low[-i - 1]) + float(self.data.close[-i - 1])) / 3.0
            raw_flow = curr_tp * float(self.data.volume[-i])
            if curr_tp > prev_tp:
                positive_flow += raw_flow
            elif curr_tp < prev_tp:
                negative_flow += raw_flow
        if negative_flow == 0.0:
            self.lines.mfi[0] = 100.0
        else:
            money_ratio = positive_flow / negative_flow
            self.lines.mfi[0] = 100.0 - (100.0 / (1.0 + money_ratio))


class DeltaMFI(bt.Indicator):
    """Delta MFI indicator that computes the difference between two MFI periods and classifies color state."""

    lines = ("color", "delta")
    params = dict(mfi_period1=14, mfi_period2=50, level=50)

    def __init__(self):
        """Initialize the DeltaMFI indicator with two MoneyFlowIndex instances and threshold levels."""
        self.addminperiod(max(int(self.p.mfi_period1), int(self.p.mfi_period2)) + 3)
        self.mfi1 = MoneyFlowIndex(self.data, period=int(self.p.mfi_period1))
        self.mfi2 = MoneyFlowIndex(self.data, period=int(self.p.mfi_period2))
        lvl = int(self.p.level)
        self.max_level = 100 - (100 - lvl)
        self.min_level = 100 - lvl

    def next(self):
        """Compute the delta and color state for the current bar."""
        m1 = float(self.mfi1[0])
        m2 = float(self.mfi2[0])
        self.lines.delta[0] = m1 - m2
        color = 1.0
        if m2 > self.max_level and m1 > m2:
            color = 0.0
        if m2 < self.min_level and m1 < m2:
            color = 2.0
        self.lines.color[0] = color


class ExpDeltaMFIStrategy(bt.Strategy):
    """Delta MFI strategy: trades based on color transitions of the Delta MFI indicator."""

    params = dict(
        mfi_period1=14,
        mfi_period2=50,
        level=50,
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
        """Initialize the strategy: set up data references, DeltaMFI indicator, and state tracking counters."""
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.ind = DeltaMFI(
            self.signal_data,
            mfi_period1=self.p.mfi_period1,
            mfi_period2=self.p.mfi_period2,
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
        """Advance one bar, process stop levels and transition signals, then place trades."""
        self.bar_num += 1
        if self._check_exit_levels():
            return
        sb = max(int(self.p.signal_bar) - 1, 0)
        if len(self.signal_data) < max(int(self.p.mfi_period1), int(self.p.mfi_period2)) + sb + 3:
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
        """Track trade lifecycle and update counters for opens and closed outcomes."""
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


def test_262_0261_0813_delta_mfi() -> None:
    """Migrated regression test for mean_reversion/0261_0813_delta_mfi."""
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
        ExpDeltaMFIStrategy,
        mfi_period1=14, mfi_period2=50, level=50,
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

    assert strat.bar_num == 5324, f"bar_num: expected=5324, got={strat.bar_num}"
    assert strat.buy_count == 18, f"buy_count: expected=18, got={strat.buy_count}"
    assert strat.sell_count == 6, f"sell_count: expected=6, got={strat.sell_count}"
    assert strat.win_count == 7, f"win_count: expected=7, got={strat.win_count}"
    assert strat.loss_count == 17, f"loss_count: expected=17, got={strat.loss_count}"
    assert strat.trade_count == 24, f"trade_count: expected=24, got={strat.trade_count}"
    assert total_trades == 24, f"total_trades: expected=24, got={total_trades}"
    assert abs(final_value - 999221.4) < 0.01, f"final_value: expected=999221.4, got={final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
