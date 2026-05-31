"""Inlined regression test for price_patterns/0022_1321_meetinglines_cci.

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
    """Load MT5 tab-separated bars into a datetime-indexed backtest frame."""
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.read().strip().split("\n")
    cleaned = "\n".join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep="\t")
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"], format="%Y.%m.%d %H:%M:%S")
    df = df.rename(columns={
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low", "<CLOSE>": "close",
        "<TICKVOL>": "volume", "<VOL>": "openinterest",
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


class Mt5PandasFeed(bt.feeds.PandasData):
    """Pandas data adapter for MT5 OHLCV export columns."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class MeetingLinesCciStrategy(bt.Strategy):
    """Detect meeting-line candlestick reversals and filter with CCI."""
    params = dict(
        cci_period=18,
        cci_entry_long=-50, cci_entry_short=50,
        cci_exit_upper=80, cci_exit_lower=-80,
        ma_period=3,
        lot=0.1, point=0.01, price_digits=2,
        body_multiplier=1.0, close_tolerance_multiplier=0.1,
    )

    def __init__(self):
        """Initialize CCI/body-SMA indicators and trade counters."""
        self.cci = bt.indicators.CommodityChannelIndex(self.data, period=self.p.cci_period)
        self.body_sma = bt.indicators.SMA(abs(self.data.close - self.data.open), period=self.p.ma_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def _avg_body(self):
        return float(self.body_sma[-1])

    def _is_bullish_meeting_lines(self):
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
        avg = self._avg_body()
        if avg < self.p.point:
            return False
        return ((o2 - c2) > float(self.p.body_multiplier) * avg and
                (c1 - o1) > float(self.p.body_multiplier) * avg and
                abs(c1 - c2) < float(self.p.close_tolerance_multiplier) * avg)

    def _is_bearish_meeting_lines(self):
        o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
        o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
        avg = self._avg_body()
        if avg < self.p.point:
            return False
        return ((c2 - o2) > float(self.p.body_multiplier) * avg and
                (o1 - c1) > float(self.p.body_multiplier) * avg and
                abs(c1 - c2) < float(self.p.close_tolerance_multiplier) * avg)

    def next(self):
        """Increment bar counter and execute entry/exit logic from signals."""
        self.bar_num += 1
        warmup = max(self.p.cci_period, self.p.ma_period) + 5
        if len(self.data) < warmup:
            return

        cci1 = float(self.cci[-1])
        cci2 = float(self.cci[-2])

        if self.position:
            if self.position.size > 0:
                if ((cci1 < self.p.cci_exit_upper and cci2 > self.p.cci_exit_upper) or
                        (cci1 < self.p.cci_exit_lower and cci2 > self.p.cci_exit_lower)):
                    self.close()
                    return
            elif self.position.size < 0:
                if ((cci1 > self.p.cci_exit_lower and cci2 < self.p.cci_exit_lower) or
                        (cci1 < self.p.cci_exit_upper and cci2 > self.p.cci_exit_upper)):
                    self.close()
                    return
        else:
            if self._is_bullish_meeting_lines() and cci1 < self.p.cci_entry_long:
                self.buy(size=self.p.lot)
                return
            if self._is_bearish_meeting_lines() and cci1 > self.p.cci_entry_short:
                self.sell(size=self.p.lot)
                return

    def notify_trade(self, trade):
        """Update trade-open and close statistics by direction/PnL."""
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


def test_021_0022_1321_meetinglines_cci() -> None:
    """Migrated regression test for price_patterns/0022_1321_meetinglines_cci."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.addstrategy(MeetingLinesCciStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 6095
    assert strat.buy_count == 0
    assert strat.sell_count == 0
    assert strat.trade_count == 0
    assert total_trades == 0
    assert abs(final_value - 1000000.0) < 0.01
    # No signals fire with these parameters on this dataset
