"""Inlined regression test for trend_following/0158_1316_darkcloud_cci.

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


class DarkCloudCciStrategy(bt.Strategy):
    """Dark Cloud Cover / Piercing Line + CCI confirmation."""
    params = dict(
        cci_period=25,
        cci_entry_long=-50,
        cci_entry_short=50,
        cci_exit_upper=80,
        cci_exit_lower=-80,
        ma_period=5,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.cci = bt.indicators.CommodityChannelIndex(self.data, period=self.p.cci_period)
        self.close_avg = bt.indicators.SMA(self.data.close, period=self.p.ma_period)
        self.sma_body = bt.indicators.SMA(
            abs(self.data.close - self.data.open), period=self.p.ma_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def _avg_body(self):
        return float(self.sma_body[0])

    def _is_dark_cloud_cover(self):
        o2, h2, c2 = float(self.data.open[-2]), float(self.data.high[-2]), float(self.data.close[-2])
        o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
        avg = self._avg_body()
        mid2 = (o2 + c2) / 2.0
        cavg = float(self.close_avg[-1])
        return ((c2 - o2) > avg and
                c1 < c2 and c1 > o2 and
                mid2 > cavg and
                o1 > h2)

    def _is_piercing_line(self):
        o2, l2, c2 = float(self.data.open[-2]), float(self.data.low[-2]), float(self.data.close[-2])
        o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
        avg = self._avg_body()
        mid2 = (o2 + c2) / 2.0
        cavg = float(self.close_avg[-2])
        return ((c1 - o1) > avg and
                (o2 - c2) > avg and
                c1 > c2 and c1 < o2 and
                mid2 < cavg and
                o1 < l2)

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.cci_period, self.p.ma_period) + 5
        if len(self.data) < warmup:
            return

        cci0 = float(self.cci[0])
        cci1 = float(self.cci[-1])

        if self.position:
            if self.position.size > 0:
                if ((cci0 < self.p.cci_exit_upper and cci1 > self.p.cci_exit_upper) or
                        (cci0 < self.p.cci_exit_lower and cci1 > self.p.cci_exit_lower)):
                    self.close()
                    return
            elif self.position.size < 0:
                if ((cci0 > self.p.cci_exit_lower and cci1 < self.p.cci_exit_lower) or
                        (cci0 > self.p.cci_exit_upper and cci1 < self.p.cci_exit_upper)):
                    self.close()
                    return
        else:
            if self._is_piercing_line() and cci0 < self.p.cci_entry_long:
                self.buy(size=self.p.lot)
                return
            if self._is_dark_cloud_cover() and cci0 > self.p.cci_entry_short:
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


def test_157_0158_1316_darkcloud_cci() -> None:
    """Migrated regression test for trend_following/0158_1316_darkcloud_cci."""
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
    cerebro.addstrategy(DarkCloudCciStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    # Captured runonce=True metrics
    assert strat.bar_num == 6081, f"bar_num: expected=6081, got={strat.bar_num}"
    assert strat.buy_count == 0, f"buy_count: expected=0, got={strat.buy_count}"
    assert strat.sell_count == 2, f"sell_count: expected=2, got={strat.sell_count}"
    assert strat.win_count == 1, f"win_count: expected=1, got={strat.win_count}"
    assert strat.loss_count == 1, f"loss_count: expected=1, got={strat.loss_count}"
    assert strat.trade_count == 2, f"trade_count: expected=2, got={strat.trade_count}"
    assert total_trades == 2, f"total_trades: expected=2, got={total_trades}"
    assert abs(final_value - 1000268.7) < 0.01, f"final_value: expected=1000268.7, got={final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
