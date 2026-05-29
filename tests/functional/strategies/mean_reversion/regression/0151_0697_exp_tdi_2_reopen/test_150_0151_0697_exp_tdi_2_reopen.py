"""Inlined regression test for mean_reversion/0151_0697_exp_tdi_2_reopen.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import numpy as np
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
    df = df[["datetime", "open", "high", "low", "close", "tick_volume", "openinterest"]]
    df = df.set_index("datetime")
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def resample_frame(df, rule):
    out = df.resample(rule, label="right", closed="right").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "tick_volume": "sum", "openinterest": "last",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["openinterest"] = out["openinterest"].fillna(0)
    out["volume"] = out["tick_volume"]
    return out


def price_series(frame, applied_price="PRICE_CLOSE_"):
    if applied_price == "PRICE_OPEN_":
        return frame["open"]
    if applied_price == "PRICE_HIGH_":
        return frame["high"]
    if applied_price == "PRICE_LOW_":
        return frame["low"]
    if applied_price == "PRICE_MEDIAN_":
        return (frame["high"] + frame["low"]) / 2.0
    if applied_price == "PRICE_TYPICAL_":
        return (frame["high"] + frame["low"] + frame["close"]) / 3.0
    if applied_price == "PRICE_WEIGHTED_":
        return (frame["high"] + frame["low"] + 2.0 * frame["close"]) / 4.0
    return frame["close"]


def smooth_series(series, method="MODE_SMA_", period=20):
    period = max(int(period), 1)
    values = pd.Series(series).astype(float)
    method = str(method).upper()
    if method == "MODE_EMA_":
        return values.ewm(span=period, adjust=False).mean()
    if method == "MODE_SMMA_":
        return values.ewm(alpha=1.0 / period, adjust=False).mean()
    if method == "MODE_LWMA_":
        weights = np.arange(1, period + 1, dtype=float)
        return values.rolling(period).apply(lambda x: float(np.dot(x, weights) / weights.sum()), raw=True)
    return values.rolling(period).mean()


def compute_tdi_frame(frame, tdi_method="MODE_SMA_", tdi_period=20, applied_price="PRICE_CLOSE_"):
    out = frame.copy()
    src = price_series(out, applied_price=applied_price).astype(float)
    period = max(int(tdi_period), 1)
    mom = src - src.shift(period)
    mom_abs = mom.abs()
    mom_sum = period * smooth_series(mom, method=tdi_method, period=period)
    mom_abs_sum2 = 2 * period * smooth_series(mom_abs, method=tdi_method, period=2 * period)
    out["direct"] = mom_sum
    out["tdi"] = mom_sum.abs() - (mom_abs_sum2 - mom_abs)
    out = out.replace([np.inf, -np.inf], np.nan)
    out = out.dropna(subset=["direct", "tdi"])
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class TdiFeed(bt.feeds.PandasData):
    lines = ("tdi", "direct")
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
        ("tdi", 6), ("direct", 7),
    )


class ExpTdi2ReOpenStrategy(bt.Strategy):
    params = dict(
        signal_tf_minutes=240,
        tdi_method="MODE_SMA_",
        tdi_period=20,
        applied_price="PRICE_CLOSE_",
        signal_bar=1,
        stop_loss=1000,
        take_profit=2000,
        price_step=300,
        pos_total=10,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        size=0.1,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal = self.datas[1]
        self.tdi = self.signal.tdi
        self.direct = self.signal.direct

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.layers = []
        self.last_signal_dt = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _side(self):
        if not self.layers:
            return None
        return self.layers[0]["side"]

    def _add_layer(self, side, entry_price):
        unit = self._unit()
        if side == "buy":
            stop = round(entry_price - float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            take = round(entry_price + float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None
        else:
            stop = round(entry_price + float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            take = round(entry_price - float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None
        self.layers.append({"side": side, "entry_price": float(entry_price), "stop_price": stop, "take_profit_price": take, "size": float(self.p.size)})
        if side == "buy":
            self.buy_count += 1
        else:
            self.sell_count += 1
        self.completed_order_count += 1

    def _close_all(self, reason):
        if not self.layers:
            return
        self.completed_order_count += len(self.layers)
        self.layers = []

    def _manage_layers(self):
        if not self.layers:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        survivors = []
        closed = False
        for layer in self.layers:
            if layer["side"] == "buy":
                stop_hit = layer["stop_price"] is not None and low <= layer["stop_price"]
                take_hit = layer["take_profit_price"] is not None and high >= layer["take_profit_price"]
            else:
                stop_hit = layer["stop_price"] is not None and high >= layer["stop_price"]
                take_hit = layer["take_profit_price"] is not None and low <= layer["take_profit_price"]
            if stop_hit or take_hit:
                closed = True
                self.completed_order_count += 1
            else:
                survivors.append(layer)
        self.layers = survivors
        return closed

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        curr_direct = float(self.direct[-idx])
        curr_tdi = float(self.tdi[-idx])
        prev_direct = float(self.direct[-(idx + 1)])
        prev_tdi = float(self.tdi[-(idx + 1)])
        buy_open = sell_open = buy_close = sell_close = False
        if prev_direct > prev_tdi:
            if self.p.buy_pos_open and curr_direct <= curr_tdi:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True
        if prev_direct < prev_tdi:
            if self.p.sell_pos_open and curr_direct >= curr_tdi:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True
        return buy_open, buy_close, sell_open, sell_close

    def _maybe_reopen(self):
        if not self.layers:
            return False
        if len(self.layers) - 1 >= int(self.p.pos_total):
            return False
        last_entry = self.layers[-1]["entry_price"]
        close_price = float(self.base.close[0])
        step_distance = float(self.p.price_step) * self._unit()
        side = self._side()
        if side == "sell" and close_price < last_entry - step_distance:
            self._add_layer("sell", close_price)
            return True
        if side == "buy" and close_price > last_entry + step_distance:
            self._add_layer("buy", close_price)
            return True
        return False

    def next(self):
        self.bar_num += 1
        self._manage_layers()
        if len(self.signal) < max(int(self.p.signal_bar) + 2, int(self.p.tdi_period) + 3):
            return
        signal_dt = bt.num2date(self.signal.datetime[-max(int(self.p.signal_bar), 1)])
        if self.last_signal_dt != signal_dt:
            self.last_signal_dt = signal_dt
            buy_open, buy_close, sell_open, sell_close = self._evaluate_signals()
            if buy_open or sell_open:
                self.signal_count += 1
            if buy_close and self._side() == "buy":
                self._close_all("opposite_signal")
            if sell_close and self._side() == "sell":
                self._close_all("opposite_signal")
            if buy_open and not self.layers:
                self._add_layer("buy", float(self.base.close[0]))
                return
            if sell_open and not self.layers:
                self._add_layer("sell", float(self.base.close[0]))
                return
        self._maybe_reopen()

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_150_0151_0697_exp_tdi_2_reopen() -> None:
    """Migrated regression test for mean_reversion/0151_0697_exp_tdi_2_reopen."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    base_frame = df.copy()
    base_frame["volume"] = base_frame["tick_volume"]
    base_frame = base_frame[["open", "high", "low", "close", "volume", "openinterest"]]

    signal_frame = resample_frame(df, "240min")
    signal_frame = compute_tdi_frame(signal_frame, tdi_method="MODE_SMA_", tdi_period=20)
    signal_frame = signal_frame[["open", "high", "low", "close", "volume", "openinterest", "tdi", "direct"]]

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(
        commission=0.0, margin=0.01, mult=100.0,
        commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False,
    )
    cerebro.adddata(Mt5PandasFeed(dataname=base_frame, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.adddata(TdiFeed(dataname=signal_frame, timeframe=bt.TimeFrame.Minutes, compression=240))
    cerebro.addstrategy(ExpTdi2ReOpenStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 5217
    assert strat.buy_count == 4
    assert strat.sell_count == 6
    assert strat.signal_count == 5
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
