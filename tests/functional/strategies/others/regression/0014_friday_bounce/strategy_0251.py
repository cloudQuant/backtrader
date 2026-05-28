#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""周五反弹可靠性策略 - 从50日低点反弹时，周五反弹后后续表现最可靠"""

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


def prepare_friday_bounce_features(df, params):
    """准备周五反弹策略特征"""
    out = df.copy()
    lookback_period = int(params.get("lookback_period", 50))
    holding_days = int(params.get("holding_days", 5))

    # 计算50日低点
    out["low_50"] = out["low"].rolling(window=lookback_period).min()

    # 识别50日低点
    out["is_50_low"] = (out["low"] == out["low_50"]).astype(float)

    # 识别反弹（收盘价高于最低价）
    out["is_bounce"] = (out["close"] > out["low"]).astype(float)

    # 识别周五
    out["is_friday"] = (out.index.dayofweek == 4).astype(float)

    # 周五反弹信号
    out["friday_bounce"] = (
        (out["is_50_low"] > 0.5) & (out["is_bounce"] > 0.5) & (out["is_friday"] > 0.5)
    ).astype(float)

    # 入场信号（周一开盘入场）
    out["entry_signal"] = out["friday_bounce"].shift(1).fillna(0)

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
            "is_50_low",
            "is_bounce",
            "is_friday",
            "friday_bounce",
            "entry_signal",
            "exit_signal",
        ]
    ].copy()
    return out.dropna()


class Mt5FridayBounceFeed(bt.feeds.PandasData):
    lines = (
        "is_50_low",
        "is_bounce",
        "is_friday",
        "friday_bounce",
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
        ("is_50_low", 6),
        ("is_bounce", 7),
        ("is_friday", 8),
        ("friday_bounce", 9),
        ("entry_signal", 10),
        ("exit_signal", 11),
    )


class FridayBounceStrategy(bt.Strategy):
    params = dict(
        lookback_period=50,
        holding_days=5,
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

        # 无持仓时检查入场
        if not self.position:
            if entry_signal:
                self.buy_count += 1
                self.entry_bar = self.bar_num
                self.pending_order = self.buy(
                    size=self._get_position_size(
                        target_notional_pct=float(self.p.lot_size)
                    )
                )
            return

        # 有持仓时检查出场（时间止损）
        if self.position and self.entry_bar is not None:
            holding_days = self.bar_num - self.entry_bar
            if holding_days >= self.p.holding_days:
                self.sell_count += 1
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
