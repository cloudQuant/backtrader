"""Inlined regression test for trend_following/0149_1285_rsi_cci.

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
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class RSICCIStrategy(bt.Strategy):
    """GG-RSI-CCI combo strategy."""
    params = dict(rsi_period=14, cci_period=14, lot=0.1, point=0.01, price_digits=2)

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.cci = bt.indicators.CCI(self.data, period=self.p.cci_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(self.p.rsi_period, self.p.cci_period) + 5:
            return

        rsi0 = float(self.rsi[-1])
        rsi1 = float(self.rsi[-2])
        cci0 = float(self.cci[-1])
        cci1 = float(self.cci[-2])

        rsi_bull = rsi1 < 50 and rsi0 > 50
        rsi_bear = rsi1 > 50 and rsi0 < 50
        cci_bull = cci1 < 0 and cci0 > 0
        cci_bear = cci1 > 0 and cci0 < 0

        both_bull = rsi0 > 50 and cci0 > 0
        both_bear = rsi0 < 50 and cci0 < 0

        if self.position:
            if self.position.size > 0:
                if rsi_bear or cci_bear:
                    self.close()
                    if both_bear:
                        self.sell(size=self.p.lot)
                    return
            elif self.position.size < 0:
                if rsi_bull or cci_bull:
                    self.close()
                    if both_bull:
                        self.buy(size=self.p.lot)
                    return
        else:
            if (rsi_bull or cci_bull) and both_bull:
                self.buy(size=self.p.lot)
                return
            if (rsi_bear or cci_bear) and both_bear:
                self.sell(size=self.p.lot)
                return

    def notify_trade(self, trade):
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


def test_148_0149_1285_rsi_cci() -> None:
    """Migrated regression test for trend_following/0149_1285_rsi_cci."""
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
    cerebro.addstrategy(RSICCIStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 6103
    assert strat.buy_count == 409
    assert strat.sell_count == 351
    assert strat.win_count == 285
    assert strat.loss_count == 474
    assert strat.trade_count == 759
    assert total_trades == 759
    assert abs(final_value - 1001639.5) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
