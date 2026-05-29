"""Inlined regression test for multi_indicator_system/0021_macdcci.

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
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low", "<CLOSE>": "close",
        "<TICKVOL>": "tick_volume", "<VOL>": "real_volume",
    })
    df["openinterest"] = 0
    df["volume"] = df["tick_volume"]
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


class MACDCCIStrategy(bt.Strategy):
    params = dict(
        inp_lot=0.01,
        cci_ma_period=8,
        macd_fast_ema_period=13, macd_slow_ema_period=33,
        macd_coefficient=86000,
        buy_level=85.0, increase=1.62, back=0,
        max_lot=100.0,
    )

    def __init__(self):
        self.cci = bt.indicators.CCI(self.data, period=self.p.cci_ma_period)
        self.macd = bt.indicators.MACD(self.data.close, period_me1=self.p.macd_fast_ema_period,
                                        period_me2=self.p.macd_slow_ema_period, period_signal=2)
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.buy_ready = False
        self.sell_ready = False
        self.number_of_losses = 0

    def _next_lot(self):
        if self.number_of_losses > 0:
            lot = float(self.p.inp_lot) * (2 ** float(self.p.increase))
        else:
            lot = float(self.p.inp_lot)
        return min(lot, float(self.p.max_lot))

    def next(self):
        self.bar_num += 1
        if len(self) < max(self.p.cci_ma_period, self.p.macd_slow_ema_period) + 5:
            return
        if self.order is not None:
            return
        cci = float(self.cci[0])
        macd = float(self.macd.macd[0]) * float(self.p.macd_coefficient)
        if cci > float(self.p.buy_level) and macd > float(self.p.buy_level):
            self.sell_ready = True
            self.buy_ready = False
        elif cci < -float(self.p.buy_level) and macd < -float(self.p.buy_level):
            self.buy_ready = True
            self.sell_ready = False
        if self.position:
            if self.position.size > 0 and self.sell_ready and cci < -float(self.p.buy_level):
                self.order = self.close()
                return
            if self.position.size < 0 and self.buy_ready and cci > float(self.p.buy_level):
                self.order = self.close()
                return
            return
        size = self._next_lot()
        if self.buy_ready and cci < float(self.p.buy_level):
            self.signal_count += 1
            self.order = self.buy(size=size)
            self.buy_ready = False
            return
        if self.sell_ready and cci < -float(self.p.buy_level):
            self.signal_count += 1
            self.order = self.sell(size=size)
            self.sell_ready = False

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if order.executed.size > 0:
                self.buy_count += 1
            elif order.executed.size < 0:
                self.sell_count += 1
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
            self.number_of_losses = max(self.number_of_losses - 1, 0)
        else:
            self.loss_count += 1
            self.number_of_losses += 1


def test_020_0021_macdcci() -> None:
    """Migrated regression test for multi_indicator_system/0021_macdcci."""
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
    cerebro.addstrategy(MACDCCIStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 6096
    assert strat.buy_count == 97
    assert strat.sell_count == 98
    assert strat.win_count == 50
    assert strat.loss_count == 47
    assert strat.trade_count == 97
    assert total_trades == 97
    assert abs(final_value - 998989.87) < 0.1
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
