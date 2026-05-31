"""Inlined regression test for mean_reversion/0268_0925_cci_histogram.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
- XAUUSD M15 (primary): 2025-12-03 01:15 to 2026-03-10 09:00
- XAUUSD H4 (signal): resampled from M15

Strategy Principle:
CCI Histogram is a CCI-based color-state strategy. The indicator wraps CCI
and classifies its value into three color zones (above high_level, between,
below low_level). Trades are triggered on color transitions, indicating
overbought/oversold regime shifts.

Strategy Logic:
- CCIHistogramIndicator computes CCI and derives a color_state line:
  0.0 = overbought (CCI > high_level), 1.0 = neutral, 2.0 = oversold (CCI < low_level)
- Buy when color_state transitions from non-zero to 0.0 (exits overbought)
- Sell when color_state transitions from non-2.0 to 2.0 (exits oversold)
- Strategy fires once per new H4 bar with stop-loss/take-profit at point distances
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
    """Load MT5-exported CSV data into a datetime-indexed DataFrame.

    Parameters
    ----------
    filepath : str or Path
        Path to the MT5 CSV file.
    fromdate : datetime or None
        Earliest date to include.
    todate : datetime or None
        Latest date to include.
    bar_shift_minutes : int
        Minutes to shift the datetime index forward.

    Returns
    -------
    pd.DataFrame
        Columns: datetime, open, high, low, close, volume, openinterest.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.read().strip().split("\n")
    cleaned = "\n".join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep="\t")
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"], format="%Y.%m.%d %H:%M:%S")
    df = df.rename(columns={
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low", "<CLOSE>": "close",
        "<TICKVOL>": "volume", "<VOL>": "openinterest",
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


def _build_signal_frame(df, minutes):
    """Resample a DataFrame to a lower-frequency signal frame for dual-timeframe strategies."""
    out = df.resample(f"{int(minutes)}min", label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum", "openinterest": "sum",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["openinterest"] = out["openinterest"].fillna(0)
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    """PandasData feed configured for MT5-exported CSV column ordering."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class CCIHistogramIndicator(bt.Indicator):
    """CCI-based colour-state indicator classifying CCI into three zones.

    Lines
    -----
    cci : float
        Commodity Channel Index value.
    color_state : float
        0.0 = overbought (CCI > high_level), 1.0 = neutral, 2.0 = oversold.
    hist_base : float
        Always 0.0 (placeholder for histogram baseline).
    """
    lines = ("cci", "color_state", "hist_base")
    params = dict(cci_period=14, high_level=100, low_level=-100)

    def __init__(self):
        """Initialise indicator state: attach CCI sub-indicator and set minimum period."""
        cci = bt.indicators.CommodityChannelIndex(self.data, period=int(self.p.cci_period))
        self.lines.cci = cci
        self.addminperiod(int(self.p.cci_period) + 2)

    def next(self):
        """Classify current CCI value into colour state (0=overbought, 1=neutral, 2=oversold)."""
        cci_value = float(self.lines.cci[0])
        color = 1.0
        if cci_value > float(self.p.high_level):
            color = 0.0
        elif cci_value < float(self.p.low_level):
            color = 2.0
        self.lines.color_state[0] = color
        self.lines.hist_base[0] = 0.0


class ExpCCIHistogramStrategy(bt.Strategy):
    """Dual-timeframe strategy trading CCI colour-state transitions on H4 data."""
    params = dict(
        cci_period=14, high_level=100, low_level=-100,
        signal_bar=1,
        stop_loss_points=1000, take_profit_points=2000,
        fixed_lot=0.1, point=0.0001,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
        indicator_minutes=240,
    )

    def __init__(self):
        """Initialise strategy: bind data feeds and create CCIHistogramIndicator."""
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.indicator = CCIHistogramIndicator(
            self.signal_data,
            cci_period=self.p.cci_period,
            high_level=self.p.high_level,
            low_level=self.p.low_level,
        )
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._last_signal_len = 0

    def _check_exit_levels(self):
        if not self.position:
            return False
        close_price = float(self.base.close[0])
        point_value = float(self.p.point)
        stop_distance = self.p.stop_loss_points * point_value if self.p.stop_loss_points > 0 else None
        take_distance = self.p.take_profit_points * point_value if self.p.take_profit_points > 0 else None
        entry_price = float(self.position.price)
        if self.position.size > 0:
            if stop_distance is not None and close_price <= entry_price - stop_distance:
                self.close()
                return True
            if take_distance is not None and close_price >= entry_price + take_distance:
                self.close()
                return True
        elif self.position.size < 0:
            if stop_distance is not None and close_price >= entry_price + stop_distance:
                self.close()
                return True
            if take_distance is not None and close_price <= entry_price - take_distance:
                self.close()
                return True
        return False

    def next(self):
        """Process a new bar: check exit levels, trade colour-state transitions."""
        self.bar_num += 1
        if len(self.base) < 2:
            return
        if self._check_exit_levels():
            return
        current_ago = max(int(self.p.signal_bar) - 1, 0)
        prev_ago = current_ago + 1
        min_signal_bars = int(self.p.cci_period) + prev_ago + 4
        if len(self.signal_data) < min_signal_bars:
            return
        current_signal_len = len(self.signal_data)
        if current_signal_len == self._last_signal_len:
            return
        self._last_signal_len = current_signal_len
        prev_color = float(self.indicator.color_state[-prev_ago])
        curr_color = float(self.indicator.color_state[-current_ago]) if current_ago else float(self.indicator.color_state[0])
        if not math.isfinite(prev_color) or not math.isfinite(curr_color):
            return
        size = float(self.p.fixed_lot)
        if size <= 0:
            return
        if curr_color == 0.0 and prev_color > 0.0:
            self.signal_count += 1
            if self.position.size < 0 and self.p.sell_pos_close:
                self.close()
            if self.position.size <= 0 and self.p.buy_pos_open:
                self.buy(size=size)
            return
        if curr_color == 2.0 and prev_color < 2.0:
            self.signal_count += 1
            if self.position.size > 0 and self.p.buy_pos_close:
                self.close()
            if self.position.size >= 0 and self.p.sell_pos_open:
                self.sell(size=size)

    def notify_trade(self, trade):
        """Track trade lifecycle: count open direction and record win/loss on close."""
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False


def test_267_0268_0925_cci_histogram() -> None:
    """Migrated regression test for mean_reversion/0268_0925_cci_histogram."""
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
    cerebro.addstrategy(ExpCCIHistogramStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 5492
    assert strat.buy_count == 13
    assert strat.sell_count == 6
    assert strat.win_count == 12
    assert strat.loss_count == 7
    assert strat.trade_count == 19
    assert total_trades == 19
    assert abs(final_value - 1000436.5) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
