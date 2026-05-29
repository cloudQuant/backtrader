"""Inlined regression test for pivot_fibonacci_system/0004_fibo_isar.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[6]
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


class FiboIsarStrategy(bt.Strategy):
    params = dict(
        control_time=False,
        start_time=7, stop_time=17,
        bbu_size=0,
        trailing_stop=10, trailing_step=5,
        step_fast=0.02, maximum_fast=0.2,
        step_slow=0.01, maximum_slow=0.1,
        count_bar_search=3, indent_stop_loss=30,
        fibo_entrance_level=50.0, fibo_profit_level=161.0,
        size=0.1, point=0.01, digits_adjust=10, price_digits=2,
        order_valid_bars=3,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.fast_sar = bt.indicators.ParabolicSAR(self.data0, af=self.p.step_fast, afmax=self.p.maximum_fast)
        self.slow_sar = bt.indicators.ParabolicSAR(self.data0, af=self.p.step_slow, afmax=self.p.maximum_slow)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_buy = None
        self.pending_sell = None
        self.stop_price = None
        self.take_profit_price = None
        self.current_side = None

    def _price_unit(self):
        return self.p.point

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _time_allowed(self):
        if not self.p.control_time:
            return True
        dt = bt.num2date(self.data0.datetime[0])
        return self.p.start_time <= dt.hour <= self.p.stop_time

    def _enough_history(self):
        return len(self.data0) >= max(10, self.p.count_bar_search * 3 + 2)

    def _get_fibo(self, high, low, level):
        return round(low + (high - low) * level, self.p.price_digits)

    def _get_fibo_short(self, high, low, level):
        return round(high - (high - low) * level, self.p.price_digits)

    def _maximumminimum(self, is_low):
        x = 0
        count = self.p.count_bar_search
        while True:
            start1 = x
            end1 = x + count
            start2 = x + count
            end2 = x + 2 * count
            vals1 = []
            vals2 = []
            for i in range(start1, end1):
                idx = -(i + 1)
                if abs(idx) > len(self.data0):
                    break
                vals1.append(float(self.data0.low[idx] if is_low else self.data0.high[idx]))
            for i in range(start2, end2):
                idx = -(i + 1)
                if abs(idx) > len(self.data0):
                    break
                vals2.append(float(self.data0.low[idx] if is_low else self.data0.high[idx]))
            if not vals1:
                return float(self.data0.low[-1] if is_low else self.data0.high[-1])
            if not vals2:
                return min(vals1) if is_low else max(vals1)
            current = min(vals1) if is_low else max(vals1)
            nxt = min(vals2) if is_low else max(vals2)
            if is_low and current > nxt:
                x += count
                continue
            if (not is_low) and current < nxt:
                x += count
                continue
            return current

    def _has_position_side(self, is_buy):
        if not self.position:
            return False
        return self.position.size > 0 if is_buy else self.position.size < 0

    def _clear_order_ref(self, order):
        if self.pending_buy is not None and order.ref == self.pending_buy.ref:
            self.pending_buy = None
        if self.pending_sell is not None and order.ref == self.pending_sell.ref:
            self.pending_sell = None

    def _place_buy_limit(self):
        sar_slow = float(self.slow_sar[-1])
        sar_fast = float(self.fast_sar[-1])
        price = float(self.data0.close[0])
        if not (sar_slow < sar_fast < price):
            return
        min_price = self._maximumminimum(True)
        max_price = float(self.data0.high[-1])
        op = self._get_fibo(max_price, min_price, self.p.fibo_entrance_level / 100.0)
        tp = self._get_fibo(max_price, min_price, self.p.fibo_profit_level / 100.0)
        sl = round(min_price - self.p.indent_stop_loss * self._trade_unit(), self.p.price_digits)
        if (price - op) < 5 * self._price_unit() or (price - sl) < 5 * self._price_unit() or (tp - price) < 5 * self._price_unit():
            return
        if self.pending_buy is None and not self._has_position_side(True):
            valid = bt.num2date(self.data0.datetime[0]) + pd.Timedelta(minutes=15 * self.p.order_valid_bars)
            self.pending_buy = self.buy(size=self.p.size, exectype=bt.Order.Limit, price=op, valid=valid)
            self.stop_price = sl
            self.take_profit_price = tp
            self.current_side = "buy"

    def _place_sell_limit(self):
        sar_slow = float(self.slow_sar[-1])
        sar_fast = float(self.fast_sar[-1])
        price = float(self.data0.close[0])
        if not (sar_slow > sar_fast > price):
            return
        max_price = self._maximumminimum(False)
        min_price = float(self.data0.low[-1])
        op = self._get_fibo(max_price, min_price, self.p.fibo_entrance_level / 100.0)
        tp = self._get_fibo_short(max_price, min_price, self.p.fibo_profit_level / 100.0)
        sl = round(max_price + self.p.indent_stop_loss * self._trade_unit(), self.p.price_digits)
        if (op - price) < 5 * self._price_unit() or (sl - price) < 5 * self._price_unit() or (price - tp) < 5 * self._price_unit():
            return
        if self.pending_sell is None and not self._has_position_side(False):
            valid = bt.num2date(self.data0.datetime[0]) + pd.Timedelta(minutes=15 * self.p.order_valid_bars)
            self.pending_sell = self.sell(size=self.p.size, exectype=bt.Order.Limit, price=op, valid=valid)
            self.stop_price = sl
            self.take_profit_price = tp
            self.current_side = "sell"

    def _manage_position(self):
        if not self.position:
            return
        high = float(self.data0.high[0])
        low = float(self.data0.low[0])
        close = float(self.data0.close[0])
        price_unit = self._price_unit()
        trade_unit = self._trade_unit()
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.close()
                return
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.close()
                return
            if self.p.trailing_stop > 0:
                candidate = round(close - self.p.trailing_stop * trade_unit, self.p.price_digits)
                if close - self.position.price >= self.p.trailing_stop * trade_unit and candidate > (self.stop_price or float("-inf")):
                    if self.stop_price is None or candidate - self.stop_price >= self.p.trailing_step * trade_unit:
                        self.stop_price = candidate
            if self.p.bbu_size > 0 and (self.stop_price is None or self.stop_price < self.position.price):
                if close - self.position.price >= self.p.bbu_size * price_unit:
                    self.stop_price = round(self.position.price + price_unit, self.p.price_digits)
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.close()
                return
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.close()
                return
            if self.p.trailing_stop > 0:
                candidate = round(close + self.p.trailing_stop * trade_unit, self.p.price_digits)
                if self.position.price - close >= self.p.trailing_stop * trade_unit and candidate < (self.stop_price or float("inf")):
                    if self.stop_price is None or self.stop_price - candidate > self.p.trailing_step * trade_unit:
                        self.stop_price = candidate
            if self.p.bbu_size > 0 and (self.stop_price is None or self.stop_price > self.position.price):
                if self.position.price - close >= self.p.bbu_size * price_unit:
                    self.stop_price = round(self.position.price - price_unit, self.p.price_digits)

    def next(self):
        self.bar_num += 1
        if not self._enough_history():
            return
        self._manage_position()
        if not self._time_allowed():
            return
        self._place_buy_limit()
        self._place_sell_limit()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
                self.current_side = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            if not self.position:
                self.stop_price = None
                self.take_profit_price = None
                self.current_side = None
        self._clear_order_ref(order)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_003_0004_fibo_isar() -> None:
    """Migrated regression test for pivot_fibonacci_system/0004_fibo_isar."""
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
    cerebro.addstrategy(FiboIsarStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 6128
    assert strat.buy_count == 172
    assert strat.sell_count == 169
    assert strat.win_count == 194
    assert strat.loss_count == 141
    assert strat.trade_count == 335
    assert total_trades == 335
    assert abs(final_value - 1005690.9) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
