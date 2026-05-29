"""Inlined regression test for mean_reversion/0165_0758_exp_2pbidealma_reopen.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import numpy as np
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


def ideal_ma_smooth(w1, w2, prev_series, curr_series, prev_result):
    d_series = curr_series - prev_series
    d_series2 = d_series * d_series - 1.0
    return ((w1 * (curr_series - prev_result)) + prev_result + w2 * prev_result * d_series2) / (1.0 + w2 * d_series2)


def compute_2pbideal1ma(series, period1=10, period2=10):
    values = pd.Series(series).astype(float).to_numpy()
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) == 0:
        return out
    out[0] = values[0]
    w1 = 1.0 / float(period1)
    w2 = 1.0 / float(period2)
    for i in range(1, len(values)):
        out[i] = ideal_ma_smooth(w1, w2, values[i - 1], values[i], out[i - 1])
    return out


def compute_2pbideal3ma(series, period_x1=10, period_x2=10, period_y1=10, period_y2=10, period_z1=10, period_z2=10):
    values = pd.Series(series).astype(float).to_numpy()
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) == 0:
        return out
    out[0] = values[0]
    moving01 = values[0]
    moving11 = values[0]
    moving21 = values[0]
    wx1 = 1.0 / float(period_x1)
    wx2 = 1.0 / float(period_x2)
    wy1 = 1.0 / float(period_y1)
    wy2 = 1.0 / float(period_y2)
    wz1 = 1.0 / float(period_z1)
    wz2 = 1.0 / float(period_z2)
    for i in range(1, len(values)):
        moving00 = ideal_ma_smooth(wx1, wx2, values[i - 1], values[i], moving01)
        moving10 = ideal_ma_smooth(wy1, wy2, moving01, moving00, moving11)
        moving20 = ideal_ma_smooth(wz1, wz2, moving11, moving10, moving21)
        moving01 = moving00
        moving11 = moving10
        moving21 = moving20
        out[i] = moving20
    return out


def compute_signal_frame(frame, period1=10, period2=10, period_x1=10, period_x2=10,
                          period_y1=10, period_y2=10, period_z1=10, period_z2=10):
    out = frame.copy()
    out["ma1"] = compute_2pbideal1ma(out["close"], period1=period1, period2=period2)
    out["ma2"] = compute_2pbideal3ma(
        out["close"],
        period_x1=period_x1, period_x2=period_x2,
        period_y1=period_y1, period_y2=period_y2,
        period_z1=period_z1, period_z2=period_z2,
    )
    out = out.dropna(subset=["ma1", "ma2"])
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
    )


class IdealSignalFeed(bt.feeds.PandasData):
    lines = ("ma1", "ma2")
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
        ("ma1", 6), ("ma2", 7),
    )


class Exp2pbIdealMAReOpenStrategy(bt.Strategy):
    params = dict(
        signal_tf_minutes=240, signal_bar=1,
        stop_loss=1000, take_profit=2000, price_step=300, pos_total=10,
        buy_pos_open=True, sell_pos_open=True,
        buy_pos_close=True, sell_pos_close=True,
        point=0.01, digits_adjust=10, price_digits=2, size=0.1,
        period1=10, period2=10,
        period_x1=10, period_x2=10, period_y1=10, period_y2=10, period_z1=10, period_z2=10,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal = self.datas[1]
        self.ma1 = self.signal.ma1
        self.ma2 = self.signal.ma2

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

    def _open_signal_buy(self):
        prev = float(self.ma1[-2]), float(self.ma2[-2])
        curr = float(self.ma1[-1]), float(self.ma2[-1])
        return prev[0] < prev[1] and curr[0] > curr[1]

    def _open_signal_sell(self):
        prev = float(self.ma1[-2]), float(self.ma2[-2])
        curr = float(self.ma1[-1]), float(self.ma2[-1])
        return prev[0] > prev[1] and curr[0] < curr[1]

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
        if len(self.signal) < 3:
            return
        signal_dt = bt.num2date(self.signal.datetime[0])
        if self.last_signal_dt != signal_dt:
            self.last_signal_dt = signal_dt
            buy_open = self.p.buy_pos_open and self._open_signal_buy()
            sell_open = self.p.sell_pos_open and self._open_signal_sell()
            buy_close = self.p.buy_pos_close and sell_open
            sell_close = self.p.sell_pos_close and buy_open
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


def test_164_0165_0758_exp_2pbidealma_reopen() -> None:
    """Migrated regression test for mean_reversion/0165_0758_exp_2pbidealma_reopen."""
    fromdate = datetime.datetime(2025, 12, 3, 1, 15)
    todate = datetime.datetime(2026, 3, 10, 9, 0)
    df = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate, bar_shift_minutes=15)
    base_frame = df.copy()
    base_frame["volume"] = base_frame["tick_volume"]
    base_frame = base_frame[["open", "high", "low", "close", "volume", "openinterest"]]

    signal_frame = resample_frame(df, "240min")
    signal_frame = compute_signal_frame(signal_frame)
    signal_frame = signal_frame[["open", "high", "low", "close", "volume", "openinterest", "ma1", "ma2"]]

    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1_000_000)
    cerebro.adddata(Mt5PandasFeed(dataname=base_frame, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.adddata(IdealSignalFeed(dataname=signal_frame, timeframe=bt.TimeFrame.Minutes, compression=240))
    cerebro.addstrategy(Exp2pbIdealMAReOpenStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 6124
    assert strat.buy_count == 41
    assert strat.sell_count == 0
    assert strat.signal_count == 1
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
