"""Inlined regression test for mean_reversion/0242_0546_anubis.

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


def resample_h4(df):
    out = pd.DataFrame()
    out["open"] = df["open"].resample("4h").first()
    out["high"] = df["high"].resample("4h").max()
    out["low"] = df["low"].resample("4h").min()
    out["close"] = df["close"].resample("4h").last()
    out["volume"] = df["volume"].resample("4h").sum()
    out["openinterest"] = 0
    out = out.dropna()
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class AnubisStrategy(bt.Strategy):
    params = dict(
        lots=1.0,
        cci_threshold=80, cci_period=11,
        stop_loss=100, breakeven=65,
        macd_fast=20, macd_slow=50, macd_signal=2,
        loss_factor=0.6, risk=5.0, close_k=2.0,
        threshold=28, std_k=2.9,
        max_sell_positions=2, max_buy_positions=2,
        point=0.01, price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.h4 = self.datas[1]
        self.h4_std30 = bt.ind.StdDev(self.h4.close, period=30, movav=bt.ind.MovAv.Exponential)
        self.h4_cci = bt.ind.CCI(self.h4, period=int(self.p.cci_period))
        self.m15_macd = bt.ind.MACD(self.m15.close, period_me1=int(self.p.macd_fast),
                                     period_me2=int(self.p.macd_slow),
                                     period_signal=int(self.p.macd_signal))
        self.m15_atr = bt.ind.ATR(self.m15, period=12)
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
        self.stop_price = None
        self.take_profit_price = None
        self.last_long_price = None
        self.last_short_price = None
        self.open_bar_buy = None
        self.open_bar_sell = None
        self.last_trade_profit = 0.0

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _effective_size(self):
        factor = float(self.p.loss_factor) if self.last_trade_profit < 0 else 1.0
        return max(0.01, float(self.p.lots) * factor)

    def _arm(self, direction, price, take):
        sl = float(self.p.stop_loss) * self._point()
        if direction == "buy":
            self.stop_price = self._round(price - sl) if sl > 0 else None
            self.take_profit_price = self._round(price + take) if take > 0 else None
            self.signal_count += 1
            self.order = self.buy(size=self._effective_size())
            self.open_bar_buy = self.data.datetime.datetime(0)
            self.last_long_price = price
        else:
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - take) if take > 0 else None
            self.signal_count += 1
            self.order = self.sell(size=self._effective_size())
            self.open_bar_sell = self.data.datetime.datetime(0)
            self.last_short_price = price

    def _set_breakeven(self):
        if not self.position:
            return
        be = float(self.p.breakeven) * self._point()
        if self.position.size > 0:
            if float(self.m15.close[0]) - float(self.position.price) > be:
                if self.stop_price is None or float(self.position.price) > float(self.stop_price):
                    self.stop_price = self._round(float(self.position.price))
        else:
            if float(self.position.price) - float(self.m15.close[0]) > be:
                if self.stop_price is None or float(self.position.price) < float(self.stop_price):
                    self.stop_price = self._round(float(self.position.price))

    def _check_protection(self):
        if not self.position or self.order is not None:
            return
        high = float(self.m15.high[0])
        low = float(self.m15.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return

    def next(self):
        self.bar_num += 1
        warmup = max(40, int(self.p.cci_period) + 5, int(self.p.macd_slow) + int(self.p.macd_signal) + 5)
        if len(self.m15) < warmup or len(self.h4) < 35 or self.order is not None:
            return

        std_take = float(self.p.std_k) * float(self.h4_std30[0])
        cci0 = float(self.h4_cci[0])
        macd1 = float(self.m15_macd.macd[-1])
        macd2 = float(self.m15_macd.macd[-2])
        macds1 = float(self.m15_macd.signal[-1])
        macds2 = float(self.m15_macd.signal[-2])
        atr1 = float(self.m15_atr[-1])
        close1 = float(self.m15.close[-1])
        open1 = float(self.m15.open[-1])
        open_cmd = 0
        if cci0 > float(self.p.cci_threshold) and macd2 >= macds2 and macd1 < macds1 and macd1 > 0:
            open_cmd = -1
        if cci0 < -float(self.p.cci_threshold) and macd2 <= macds2 and macd1 > macds1 and macd1 < 0:
            open_cmd = 1

        num_buys = 1 if self.position.size > 0 else 0
        num_sells = 1 if self.position.size < 0 else 0
        if num_sells == 0:
            self.last_short_price = None
        if num_buys == 0:
            self.last_long_price = None

        current_dt = self.data.datetime.datetime(0)
        current_price = float(self.m15.close[0])
        min_spacing = 20.0 * self._point()

        if not self.position:
            if open_cmd == 1 and num_buys < int(self.p.max_buy_positions):
                if self.open_bar_buy != current_dt and (self.last_long_price is None or abs(current_price - float(self.last_long_price)) > min_spacing):
                    self._arm("buy", current_price, std_take)
                    return
            if open_cmd == -1 and num_sells < int(self.p.max_sell_positions):
                if self.open_bar_sell != current_dt and (self.last_short_price is None or abs(current_price - float(self.last_short_price)) > min_spacing):
                    self._arm("sell", current_price, std_take)
                    return

        if self.position:
            self._set_breakeven()
            if self.position.size > 0:
                if (close1 - open1 > float(self.p.close_k) * atr1) or (macd1 < macd2 and float(self.m15.close[0]) - float(self.position.price) > float(self.p.threshold) * self._point()):
                    self.order = self.close()
                    return
            else:
                if (open1 - close1 > float(self.p.close_k) * atr1) or (macd1 > macd2 and float(self.position.price) - float(self.m15.close[0]) > float(self.p.threshold) * self._point()):
                    self.order = self.close()
                    return
            self._check_protection()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.last_trade_profit = trade.pnlcomm
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_241_0242_0546_anubis() -> None:
    """Migrated regression test for mean_reversion/0242_0546_anubis."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    h4_df = resample_h4(df)

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.adddata(Mt5PandasFeed(dataname=h4_df, timeframe=bt.TimeFrame.Minutes, compression=240))
    cerebro.addstrategy(AnubisStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 5721
    assert strat.buy_count == 40
    assert strat.sell_count == 96
    assert strat.win_count == 55
    assert strat.loss_count == 81
    assert strat.trade_count == 136
    assert total_trades == 136
    assert abs(final_value - 981586.4) < 0.01
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
