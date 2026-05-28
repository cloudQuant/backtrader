#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""背离广度看跌信号策略 - 价格上涨但广度疲弱时看跌"""

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


def prepare_breadth_divergence_features(df, params):
    """准备背离广度策略特征"""
    out = df.copy()
    breadth_threshold = float(params.get("breadth_threshold", 0.5))
    holding_period = int(params.get("holding_period", 4))

    # 价格上涨
    out["price_up"] = (out["close"] > out["close"].shift(1)).astype(float)

    # 使用成交量作为广度代理（简化版本）
    out["volume_ma"] = out["volume"].rolling(window=20).mean()
    out["volume_breadth_weak"] = (
        out["volume"] < out["volume_ma"] * breadth_threshold
    ).astype(float)

    # 使用波动率作为广度代理
    out["returns"] = out["close"].pct_change()
    out["volatility"] = out["returns"].rolling(window=20).std()
    out["volatility_ma"] = out["volatility"].rolling(window=50).mean()
    out["volatility_weak"] = (out["volatility"] < out["volatility_ma"]).astype(float)

    # 背离信号：价格上涨但广度疲弱
    out["divergence_signal"] = (
        (out["price_up"] > 0.5)
        & ((out["volume_breadth_weak"] > 0.5) | (out["volatility_weak"] > 0.5))
    ).astype(float)

    # 入场信号（看空）
    out["entry_signal"] = out["divergence_signal"]

    # 出场信号（持有N天后）
    out["exit_signal"] = 0.0

    out = out[
        [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "openinterest",
            "price_up",
            "volume_breadth_weak",
            "divergence_signal",
            "entry_signal",
            "exit_signal",
        ]
    ].copy()
    return out.dropna()


class Mt5BreadthDivergenceFeed(bt.feeds.PandasData):
    lines = (
        "price_up",
        "volume_breadth_weak",
        "divergence_signal",
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
        ("price_up", 6),
        ("volume_breadth_weak", 7),
        ("divergence_signal", 8),
        ("entry_signal", 9),
        ("exit_signal", 10),
    )


class BreadthDivergenceStrategy(bt.Strategy):
    params = dict(
        breadth_threshold=0.5,
        holding_period=4,
        lot_size=1.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.broker_value_series = []
        self.entry_bar = None

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

        entry_signal = float(self.data.entry_signal[0]) > 0.5

        # 无持仓时检查入场（做空）
        if not self.position:
            if entry_signal:
                self.sell_count += 1
                self.entry_bar = self.bar_num
                self.pending_order = self.sell(
                    size=self._get_position_size(
                        target_notional_pct=float(self.p.lot_size)
                    )
                )
            return

        # 有持仓时检查出场（时间止损）
        if self.position and self.entry_bar is not None:
            holding_days = self.bar_num - self.entry_bar
            if holding_days >= self.p.holding_period:
                self.buy_count += 1
                self.pending_order = self.close()
                self.entry_bar = None

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
