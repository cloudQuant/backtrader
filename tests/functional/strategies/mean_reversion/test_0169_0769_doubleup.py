"""Inlined regression test for mean_reversion/0169_0769_doubleup.

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
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class DoubleUpStrategy(bt.Strategy):
    params = dict(
        cci_period=8,
        macd_fast_period=13, macd_slow_period=33, macd_signal_period=2,
        buy_sell_level=150.0,
        macd_scale=1000000.0, balance_divisor=50001.0,
        min_lot=0.1, max_lot=100.0, max_m_pos=4,
        profit_distance_points=120, point=0.01, price_digits=2,
    )

    def __init__(self):
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.m_pos = 0
        self.order = None
        self.pending_reopen_side = None
        self.last_close_reason = None
        self.cci = bt.indicators.CommodityChannelIndex(self.data, period=int(self.p.cci_period))
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=int(self.p.macd_fast_period),
            period_me2=int(self.p.macd_slow_period),
            period_signal=int(self.p.macd_signal_period),
        )
        self.addminperiod(max(int(self.p.cci_period), int(self.p.macd_slow_period)) + int(self.p.macd_signal_period) + 2)

    def _dynamic_lot(self):
        lot = round(float(self.broker.getvalue()) / float(self.p.balance_divisor), 2)
        return min(max(lot, float(self.p.min_lot)), float(self.p.max_lot))

    def _entry_size(self):
        exponent = min(max(int(self.m_pos), 0), int(self.p.max_m_pos))
        size = self._dynamic_lot() * (2 ** exponent)
        return min(size, float(self.p.max_lot))

    def _price_distance(self):
        if not self.position:
            return 0.0
        return abs(float(self.position.price) - float(self.data.close[0]))

    def _floating_pnl(self):
        if not self.position:
            return 0.0
        close_price = float(self.data.close[0])
        if self.position.size > 0:
            return (close_price - float(self.position.price)) * abs(float(self.position.size))
        return (float(self.position.price) - close_price) * abs(float(self.position.size))

    def _submit_open(self, side):
        if self.order is not None:
            return False
        size = self._entry_size()
        if size <= 0:
            return False
        self.signal_count += 1
        if side == "buy":
            self.order = self.buy(size=size)
        else:
            self.order = self.sell(size=size)
        return True

    def _prepare_reverse_close(self, reopen_side):
        if not self.position or self.order is not None:
            return False
        pnl = self._floating_pnl()
        if pnl < 0:
            self.m_pos = min(self.m_pos + 1, int(self.p.max_m_pos))
        elif pnl > 0:
            self.m_pos = 0
        self.pending_reopen_side = reopen_side
        self.last_close_reason = f"reverse_to_{reopen_side}"
        self.order = self.close()
        return True

    def _check_profit_close(self):
        if not self.position or self.order is not None:
            return False
        if self._floating_pnl() <= 0:
            return False
        if self._price_distance() <= float(self.p.profit_distance_points) * float(self.p.point):
            return False
        self.m_pos = min(self.m_pos + 2, int(self.p.max_m_pos))
        self.pending_reopen_side = None
        self.last_close_reason = "profit_distance_close"
        self.order = self.close()
        return True

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        cci_now = float(self.cci[0])
        macd_now = float(self.macd.macd[0]) * float(self.p.macd_scale)
        level = float(self.p.buy_sell_level)

        if cci_now > level and macd_now > level:
            if self.position.size > 0:
                self._prepare_reverse_close("sell")
                return
            if self.position.size == 0:
                self._submit_open("sell")
                return
        elif cci_now < -level and macd_now < -level:
            if self.position.size < 0:
                self._prepare_reverse_close("buy")
                return
            if self.position.size == 0:
                self._submit_open("buy")
                return

        self._check_profit_close()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        reopen_side = None
        if order.status == bt.Order.Completed:
            if self.position:
                side = "buy" if self.position.size > 0 else "sell"
                if side == "buy":
                    self.buy_count += 1
                else:
                    self.sell_count += 1
            else:
                reopen_side = self.pending_reopen_side

        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None
            self.pending_reopen_side = None
            self.last_close_reason = None
            if reopen_side is not None and not self.position:
                self._submit_open(reopen_side)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_168_0169_0769_doubleup() -> None:
    """Migrated regression test for mean_reversion/0169_0769_doubleup."""
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
    cerebro.addstrategy(DoubleUpStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 6096
    assert strat.buy_count == 72
    assert strat.sell_count == 65
    assert strat.win_count == 129
    assert strat.loss_count == 7
    assert strat.trade_count == 136
    assert total_trades == 136
    assert abs(final_value - 2592084.08) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
