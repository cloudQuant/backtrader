"""Inlined regression test for multi_indicator_system/0014_steve_cartwright_trader_camel_cci_macd.

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


class SteveCartwrightTraderCamelCciMacdStrategy(bt.Strategy):
    params = dict(
        ma_period_ma_high=40, ma_period_ma_low=5, ma_period_cci=30,
        take_profit_pips=40, lot=1.0,
        point=0.01, price_digits=2,
    )

    def __init__(self):
        self.camel_high = bt.indicators.ExponentialMovingAverage(self.data.high, period=self.p.ma_period_ma_high)
        self.camel_low = bt.indicators.ExponentialMovingAverage(self.data.low, period=self.p.ma_period_ma_low)
        self.macd = bt.indicators.MACD(self.data.close, period_me1=12, period_me2=26, period_signal=9)
        self.cci = bt.indicators.CCI(self.data, period=self.p.ma_period_cci)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._entry_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0

    def _pip_size(self):
        digits_adjust = 10 if self.p.price_digits in (3, 5) else 1
        return self.p.point * digits_adjust

    def _clear_position_state(self):
        self._entry_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0
        self._position_was_open = False

    def _set_initial_protection(self):
        if not self.position:
            self._clear_position_state()
            return
        if self._entry_price is not None and self._last_position_size == self.position.size:
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        tp_distance = self.p.take_profit_pips * self._pip_size()
        if self.position.size > 0:
            self._take_profit_price = self._entry_price + tp_distance if self.p.take_profit_pips > 0 else None
        else:
            self._take_profit_price = self._entry_price - tp_distance if self.p.take_profit_pips > 0 else None

    def _maybe_hit_take_profit(self):
        if not self.position or self._take_profit_price is None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0 and high >= self._take_profit_price:
            self.order = self.close()
            return True
        if self.position.size < 0 and low <= self._take_profit_price:
            self.order = self.close()
            return True
        return False

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.ma_period_ma_high + 5, 35)
        if len(self.data) < warmup:
            return
        if self.order:
            return

        self._set_initial_protection()

        macd_signal_prev = float(self.macd.signal[-1])
        macd_main_prev = float(self.macd.macd[-1])
        cci_prev = float(self.cci[-1])
        camel_high_prev = float(self.camel_high[-1])
        camel_low_prev = float(self.camel_low[-1])
        close_prev = float(self.data.close[-1])

        if self.position:
            if self._maybe_hit_take_profit():
                return
            if self.position.size > 0:
                if macd_main_prev < macd_signal_prev or cci_prev < 100:
                    self.order = self.close()
                    return
            else:
                if macd_main_prev > macd_signal_prev:
                    self.order = self.close()
                    return
            return

        if self.broker.getcash() < (1000 * self.p.lot):
            return

        if cci_prev > 100 and macd_main_prev > 0 and macd_main_prev > macd_signal_prev and close_prev > camel_high_prev:
            self.order = self.buy(size=self.p.lot)
            return

        if cci_prev < -100 and macd_main_prev < 0 and macd_main_prev < macd_signal_prev and close_prev < camel_low_prev:
            self.order = self.sell(size=self.p.lot)
            return

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed and self.position:
            self._set_initial_protection()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None
        if not self.position:
            self._clear_position_state()

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
        self._clear_position_state()


def test_013_0014_steve_cartwright_trader_camel_cci_macd() -> None:
    """Migrated regression test for multi_indicator_system/0014_steve_cartwright_trader_camel_cci_macd."""
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
    cerebro.addstrategy(SteveCartwrightTraderCamelCciMacdStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 6071
    assert strat.buy_count == 491
    assert strat.sell_count == 196
    assert strat.win_count == 352
    assert strat.loss_count == 335
    assert strat.trade_count == 687
    assert total_trades == 687
    assert abs(final_value - 1038763.0) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
