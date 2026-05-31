"""Inlined regression test for price_patterns/0027_1337_harami_cci.

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
    """Load MT5 tab-delimited data into a backtrader-ready OHLCV DataFrame."""
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
    """Backtrader feed mapping MT5 OHLCV positional columns."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class HaramiCCIStrategy(bt.Strategy):
    """Harami pattern + CCI reversal strategy."""
    params = dict(
        cci_period=11, ma_period=5,
        lot=0.1, point=0.01, price_digits=2,
        cci_entry_long=-50, cci_entry_short=50,
        cci_exit_upper=80, cci_exit_lower=-80,
    )

    def __init__(self):
        """Create CCI/SMA indicators and trading counters."""
        self.cci = bt.indicators.CommodityChannelIndex(self.data, period=self.p.cci_period)
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.ma_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def _avg_body(self):
        count = min(self.p.ma_period, len(self.data) - 1)
        if count <= 0:
            return 0.0
        total = 0.0
        for i in range(-count, 0):
            total += abs(float(self.data.close[i]) - float(self.data.open[i]))
        return total / count

    def _bullish_harami(self):
        if len(self.data) < 3:
            return False
        o2 = float(self.data.open[-2])
        c2 = float(self.data.close[-2])
        o1 = float(self.data.open[-1])
        c1 = float(self.data.close[-1])
        avg = self._avg_body()
        if avg <= 0:
            return False
        mid2 = (float(self.data.high[-2]) + float(self.data.low[-2])) / 2.0
        close_avg = float(self.sma[-2])
        return (c1 > o1 and (o2 - c2) > avg and c1 < o2 and o1 > c2 and mid2 < close_avg)

    def _bearish_harami(self):
        if len(self.data) < 3:
            return False
        o2 = float(self.data.open[-2])
        c2 = float(self.data.close[-2])
        o1 = float(self.data.open[-1])
        c1 = float(self.data.close[-1])
        avg = self._avg_body()
        if avg <= 0:
            return False
        mid2 = (float(self.data.high[-2]) + float(self.data.low[-2])) / 2.0
        close_avg = float(self.sma[-2])
        return (c1 < o1 and (c2 - o2) > avg and c1 > o2 and o1 < c2 and mid2 > close_avg)

    def next(self):
        """Evaluate harami signals and CCI levels, then issue/close positions."""
        self.bar_num += 1
        if len(self.data) < max(self.p.cci_period, self.p.ma_period) + 5:
            return

        cci_1 = float(self.cci[-1])
        cci_2 = float(self.cci[-2]) if len(self.cci) > 2 else cci_1
        bull = self._bullish_harami()
        bear = self._bearish_harami()

        if self.position:
            if self.position.size > 0:
                exit_long = ((cci_1 < 80 and cci_2 > 80) or (cci_1 > -80 and cci_2 < -80))
                if exit_long or (bear and cci_1 > 50):
                    self.close()
                    if bear and cci_1 > 50:
                        self.sell(size=self.p.lot)
                    return
            elif self.position.size < 0:
                exit_short = ((cci_1 > -80 and cci_2 < -80) or (cci_1 < 80 and cci_2 > 80))
                if exit_short or (bull and cci_1 < -50):
                    self.close()
                    if bull and cci_1 < -50:
                        self.buy(size=self.p.lot)
                    return
        else:
            if bull and cci_1 < -50:
                self.buy(size=self.p.lot)
                return
            if bear and cci_1 > 50:
                self.sell(size=self.p.lot)
                return

    def notify_trade(self, trade):
        """Track opened and closed trades for counters."""
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


def test_026_0027_1337_harami_cci() -> None:
    """Migrated regression test for price_patterns/0027_1337_harami_cci."""
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
    cerebro.addstrategy(HaramiCCIStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 6109
    assert strat.buy_count == 49
    assert strat.sell_count == 50
    assert strat.win_count == 64
    assert strat.loss_count == 35
    assert strat.trade_count == 99
    assert total_trades == 99
    assert abs(final_value - 1001000.0) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
