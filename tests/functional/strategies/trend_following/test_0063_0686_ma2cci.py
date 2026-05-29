"""Inlined regression test for trend_following/0063_0686_ma2cci.

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
    cleaned = "\n".join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep="\t")
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"], format="%Y.%m.%d %H:%M:%S")
    df = df.rename(columns={
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low",
        "<CLOSE>": "close", "<TICKVOL>": "tick_volume",
    })
    if "<VOL>" in df.columns:
        df["openinterest"] = df["<VOL>"]
    else:
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


class MA2CCIStrategy(bt.Strategy):
    params = dict(
        ma_period_fast=10,
        ma_period_slow=37,
        ma_period_cci=39,
        ma_period_atr=3,
        percent_risk=2.0,
        min_indent=15,
        point=0.01,
        price_digits=2,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
    )

    def __init__(self):
        self.ma_fast = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.ma_period_fast)
        self.ma_slow = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.ma_period_slow)
        self.cci = bt.indicators.CommodityChannelIndex(self.data, period=self.p.ma_period_cci)
        self.atr = bt.indicators.ATR(self.data, period=self.p.ma_period_atr)
        self.order = None
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self._position_was_open = False
        self._entry_price = None
        self._stop_price = None
        self._last_position_size = 0.0

    def _distance_unit(self):
        digits_adjust = 10 if int(self.p.price_digits) in (3, 5) else 1
        return float(self.p.point) * digits_adjust

    def _normalize_size(self, size):
        step = float(self.p.lot_step)
        size = round(float(size) / step, 0) * step
        size = max(size, float(self.p.lot_min))
        size = min(size, float(self.p.lot_max))
        return round(size, 2)

    def _calc_size(self, entry_price, stop_price):
        risk_cash = self.broker.getvalue() * (float(self.p.percent_risk) / 100.0)
        risk_per_lot = abs(entry_price - stop_price) * 100.0
        if risk_per_lot <= 0:
            return 0.0
        return self._normalize_size(risk_cash / risk_per_lot)

    def _sync_position_state(self):
        if not self.position:
            self._entry_price = None
            self._stop_price = None
            self._last_position_size = 0.0
            return
        if self._entry_price is not None and self._last_position_size == float(self.position.size):
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)

    def _manage_exit(self):
        if not self.position:
            return False
        ma_fast_prev = float(self.ma_fast[-1])
        ma_slow_prev = float(self.ma_slow[-1])
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if ma_fast_prev < ma_slow_prev and float(self.ma_fast[-2]) >= float(self.ma_slow[-2]):
                self.order = self.close()
                return True
            if self._stop_price is not None and low <= self._stop_price:
                self.order = self.close()
                return True
        else:
            if ma_fast_prev > ma_slow_prev and float(self.ma_fast[-2]) <= float(self.ma_slow[-2]):
                self.order = self.close()
                return True
            if self._stop_price is not None and high >= self._stop_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.ma_period_slow, self.p.ma_period_cci, self.p.ma_period_atr) + 3
        if len(self.data) < warmup:
            return
        if self.order is not None:
            return
        self._sync_position_state()
        if self._manage_exit():
            return
        if self.position:
            return
        maf = float(self.ma_fast[-1])
        mas = float(self.ma_slow[-1])
        maf_p = float(self.ma_fast[-2])
        mas_p = float(self.ma_slow[-2])
        icc = float(self.cci[-1])
        icc_p = float(self.cci[-2])
        atr = float(self.atr[0])
        min_indent = float(self.p.min_indent) * self._distance_unit()
        if (maf > mas and maf_p <= mas_p) and (icc > 0 and icc_p <= 0):
            entry = float(self.data.close[0])
            stop = entry - max(atr, min_indent)
            size = self._calc_size(entry, stop)
            if size > 0:
                self.signal_count += 1
                self._stop_price = round(stop, self.p.price_digits)
                self.order = self.buy(size=size)
                return
        if (maf < mas and maf_p >= mas_p) and (icc < 0 and icc_p >= 0):
            entry = float(self.data.close[0])
            stop = entry + max(atr, min_indent)
            size = self._calc_size(entry, stop)
            if size > 0:
                self.signal_count += 1
                self._stop_price = round(stop, self.p.price_digits)
                self.order = self.sell(size=size)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            self._sync_position_state()
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self._stop_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
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


def test_062_0063_0686_ma2cci() -> None:
    """Migrated regression test for trend_following/0063_0686_ma2cci."""
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
    cerebro.addstrategy(MA2CCIStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 6053, f"bar_num: expected=6053, got={strat.bar_num}"
    assert strat.buy_count == 14, f"buy_count: expected=14, got={strat.buy_count}"
    assert strat.sell_count == 20, f"sell_count: expected=20, got={strat.sell_count}"
    assert strat.win_count == 7, f"win_count: expected=7, got={strat.win_count}"
    assert strat.loss_count == 27, f"loss_count: expected=27, got={strat.loss_count}"
    assert strat.trade_count == 34, f"trade_count: expected=34, got={strat.trade_count}"
    assert total_trades == 34, f"total_trades: expected=34, got={total_trades}"
    assert abs(final_value - 822600.53) < 0.01, f"final_value: expected=822600.53, got={final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
