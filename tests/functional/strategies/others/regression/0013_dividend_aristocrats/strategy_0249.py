#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
股息贵族轮动策略
基于连续股息增长年数和动量因子筛选
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import io
import backtrader as bt
import pandas as pd
import numpy as np


def load_mt5_csv(filepath, fromdate=None, todate=None):
    """加载MT5 CSV数据"""
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


def prepare_dividend_aristocrats_features(df, params):
    """准备股息贵族策略特征"""
    out = df.copy()
    momentum_period = int(params.get("momentum_period", 126))
    lookback_period = int(params.get("lookback_period", 50))

    # 计算动量（6个月收益率）
    out["momentum"] = out["close"].pct_change(momentum_period)

    # 计算50日均线
    out["ma50"] = out["close"].rolling(window=lookback_period).mean()

    # 计算波动率
    out["volatility"] = out["close"].pct_change().rolling(window=20).std()

    # 评分系统：动量 + 趋势强度
    out["trend_score"] = 0.0
    out.loc[out["close"] > out["ma50"], "trend_score"] = 1.0

    # 综合得分
    out["score"] = out["momentum"] * 100 + out["trend_score"]

    # 入场信号：得分由负转正
    out["entry_signal"] = ((out["score"].shift(1) <= 0) & (out["score"] > 0)).astype(
        float
    )

    # 出场信号：得分由正转负
    out["exit_signal"] = ((out["score"].shift(1) > 0) & (out["score"] <= 0)).astype(
        float
    )

    out = out[
        [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "openinterest",
            "momentum",
            "ma50",
            "score",
            "entry_signal",
            "exit_signal",
        ]
    ].copy()
    return out.dropna()


class Mt5DividendAristocratsFeed(bt.feeds.PandasData):
    """股息贵族策略数据源"""

    lines = (
        "momentum",
        "ma50",
        "score",
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
        ("momentum", 6),
        ("ma50", 7),
        ("score", 8),
        ("entry_signal", 9),
        ("exit_signal", 10),
    )


class DividendAristocratsStrategy(bt.Strategy):
    """股息贵族轮动策略"""

    params = dict(
        momentum_period=126,
        lookback_period=50,
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
        exit_signal = float(self.data.exit_signal[0]) > 0.5

        # 无持仓时检查入场
        if not self.position:
            if entry_signal:
                self.buy_count += 1
                self.pending_order = self.buy(
                    size=self._get_position_size(
                        target_notional_pct=float(self.p.lot_size)
                    )
                )
            return

        # 有持仓时检查出场
        if exit_signal:
            self.sell_count += 1
            self.pending_order = self.close()

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
