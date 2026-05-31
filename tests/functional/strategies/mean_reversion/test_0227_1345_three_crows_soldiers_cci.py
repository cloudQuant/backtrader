"""Inlined regression test for a three-crow/soldiers trend-reversal strategy.

Self-contained single-file test (manually authored). Runs with runonce=True only.

Data Used:
    XAUUSD M15 bars from ``tests/datas/XAUUSD_M15.csv``, filtered from
    ``2025-12-03 01:15:00`` to ``2026-03-10 09:00:00`` with a 15-minute bar shift.

Strategy Principle:
    The strategy identifies 3 white soldiers / 3 black crows candlestick
    formations and confirms entries with CCI regime thresholds.

Strategy Logic:
    It computes CCI and a moving average, detects continuation patterns, opens long
    on white-soldier exhaustion and short on black-crow exhaustion, and exits
    when CCI crosses back into neutral zones.
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
    """Load an MT5 tab-separated CSV file into a datetime-indexed DataFrame."""
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


class Mt5PandasFeed(bt.feeds.PandasData):
    """PandasData feed mapping MT5 OHLCV columns into Backtrader data lines."""
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class ThreeCrowsSoldiersCCIStrategy(bt.Strategy):
    """3 Black Crows / 3 White Soldiers + CCI confirmation."""
    params = dict(cci_period=37, ma_period=13, lot=0.1, point=0.01, price_digits=2)

    def __init__(self):
        """Initialize CCI and MA indicators plus entry/exit counters."""
        self.cci = bt.indicators.CCI(self.data, period=self.p.cci_period)
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.ma_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def _avg_body(self):
        total = 0.0
        count = min(self.p.ma_period, len(self.data) - 1)
        if count <= 0:
            return 0.0
        for i in range(-count, 0):
            total += abs(float(self.data.close[i]) - float(self.data.open[i]))
        return total / count

    def _mid_point(self, idx):
        return (float(self.data.high[idx]) + float(self.data.low[idx])) / 2.0

    def _three_white_soldiers(self):
        if len(self.data) < 4:
            return False
        avg = self._avg_body()
        if avg <= 0:
            return False
        return (
            (float(self.data.close[-3]) - float(self.data.open[-3]) > avg) and
            (float(self.data.close[-2]) - float(self.data.open[-2]) > avg) and
            (float(self.data.close[-1]) - float(self.data.open[-1]) > avg) and
            (self._mid_point(-2) > self._mid_point(-3)) and
            (self._mid_point(-1) > self._mid_point(-2))
        )

    def _three_black_crows(self):
        if len(self.data) < 4:
            return False
        avg = self._avg_body()
        if avg <= 0:
            return False
        return (
            (float(self.data.open[-3]) - float(self.data.close[-3]) > avg) and
            (float(self.data.open[-2]) - float(self.data.close[-2]) > avg) and
            (float(self.data.open[-1]) - float(self.data.close[-1]) > avg) and
            (self._mid_point(-2) < self._mid_point(-3)) and
            (self._mid_point(-1) < self._mid_point(-2))
        )

    def next(self):
        """Evaluate candle-pattern and CCI conditions, then enter/exit positions."""
        self.bar_num += 1
        if len(self.data) < max(self.p.cci_period, self.p.ma_period) + 5:
            return

        cci_1 = float(self.cci[-1])
        cci_2 = float(self.cci[-2]) if len(self.cci) > 2 else cci_1

        if self.position:
            if self.position.size > 0:
                if ((cci_1 > -80 and cci_2 < -80) or (cci_1 < 80 and cci_2 > 80)):
                    self.close()
                    return
            elif self.position.size < 0:
                if ((cci_1 < 80 and cci_2 > 80) or (cci_1 < -80 and cci_2 > -80)):
                    self.close()
                    return
        else:
            if self._three_white_soldiers() and cci_1 < -50:
                self.buy(size=self.p.lot)
                return
            if self._three_black_crows() and cci_1 > 50:
                self.sell(size=self.p.lot)
                return

    def notify_trade(self, trade):
        """Count trade lifecycle events and classify win/loss outcomes."""
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


def test_226_0227_1345_three_crows_soldiers_cci() -> None:
    """Migrated regression test for mean_reversion/0227_1345_three_crows_soldiers_cci."""
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
    cerebro.addstrategy(ThreeCrowsSoldiersCCIStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 6057
    assert strat.buy_count == 1
    assert strat.sell_count == 0
    assert strat.win_count == 0
    assert strat.loss_count == 1
    assert strat.trade_count == 1
    assert total_trades == 1
    assert abs(final_value - 999839.0) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
