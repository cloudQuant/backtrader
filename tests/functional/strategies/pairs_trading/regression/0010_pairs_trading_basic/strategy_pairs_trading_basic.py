from __future__ import absolute_import, division, print_function, unicode_literals

import io
import backtrader as bt
import pandas as pd
import numpy as np


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = "\n".join(lines)
    sep = "\t" if "\t" in lines[0] else ","
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df["<DATE>"].astype(str) + " " + df["<TIME>"].astype(str)
    parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M", errors="coerce")
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M:%S", errors="coerce")
    df["datetime"] = parsed
    df = df.rename(
        columns={
            "<OPEN>": "open",
            "<HIGH>": "high",
            "<LOW>": "low",
            "<CLOSE>": "close",
            "<TICKVOL>": "tick_volume",
            "<VOL>": "real_volume",
        }
    )
    df["openinterest"] = 0
    df["volume"] = df["tick_volume"] if "tick_volume" in df.columns else 0
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest"]]
    df = df.set_index("datetime").sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def calculate_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.inf)
    return 100 - (100 / (1 + rs))


def prepare_pairs_trading_basic_features(df, params):
    lookback = int(params.get("lookback_period", 252))
    entry_z = float(params.get("entry_z", 2.0))
    exit_z = float(params.get("exit_z", 0.5))
    stop_z = float(params.get("stop_z", 3.0))

    out = df.copy()
    # Use simple price vs MA as spread proxy for single asset
    ma = out["close"].rolling(lookback).mean()
    std = out["close"].rolling(lookback).std()
    out["z_score"] = (out["close"] - ma) / std.replace(0, np.inf)

    # Entry: Z-score extreme (mean reversion)
    out["entry_signal"] = 0.0
    out.loc[out["z_score"] < -entry_z, "entry_signal"] = 1.0  # Long: price too low
    out.loc[out["z_score"] > entry_z, "entry_signal"] = -1.0  # Short: price too high

    # Exit: Z-score returns to normal
    out["exit_signal"] = 0.0
    out.loc[abs(out["z_score"]) < exit_z, "exit_signal"] = 1.0
    out.loc[abs(out["z_score"]) > stop_z, "exit_signal"] = 1.0  # Stop loss

    out = out[
        [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "openinterest",
            "z_score",
            "entry_signal",
            "exit_signal",
        ]
    ].copy()
    return out.dropna()


class Mt5PairsTradingBasicFeed(bt.feeds.PandasData):
    lines = (
        "z_score",
        "entry_signal",
        "exit_signal",
    )
    params = (
        ("datetime", None),
        ("open", 0),
        ("high", 1),
        ("low", 2),
        ("close", 3),
        ("volume", 4),
        ("openinterest", 5),
        ("z_score", 6),
        ("entry_signal", 7),
        ("exit_signal", 8),
    )


class PairsTradingBasicStrategy(bt.Strategy):
    params = dict(
        lookback_period=252,
        entry_z=2.0,
        exit_z=0.5,
        stop_z=3.0,
        max_holding_days=20,
        lot_size=1.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_bar = 0
        self.entry_direction = 0
        self.broker_value_series = []

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = (
            broker_value * float(target_notional_pct) / (execution_price * multiplier)
        )
        return max(0.01, round(size, 2))

    def next(self):
        self.bar_num += 1
        self.broker_value_series.append(
            (bt.num2date(self.data.datetime[0]), float(self.broker.getvalue()))
        )

        if self.pending_order is not None:
            return

        entry_signal = float(self.data.entry_signal[0])
        exit_signal = float(self.data.exit_signal[0])

        if not self.position:
            if entry_signal > 0.5:
                self.buy_count += 1
                self.entry_bar = self.bar_num
                self.entry_direction = 1
                self.pending_order = self.buy(size=self._get_position_size())
            elif entry_signal < -0.5:
                self.sell_count += 1
                self.entry_bar = self.bar_num
                self.entry_direction = -1
                self.pending_order = self.sell(size=self._get_position_size())
        else:
            holding_days = self.bar_num - self.entry_bar
            should_exit = exit_signal > 0.5 or holding_days >= self.p.max_holding_days
            if should_exit:
                self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        pass
