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


def prepare_sixty_forty_features(df, params):
    ma_period = int(params.get("ma_period", 200))
    rebalance_days = int(params.get("rebalance_days", 63))

    out = df.copy()
    out["ma"] = out["close"].rolling(ma_period).mean()
    out["trend_up"] = (out["close"] > out["ma"]).astype(float)
    out["days_since_rebalance"] = 0
    cnt = 0
    for i in range(len(out)):
        cnt += 1
        if cnt >= rebalance_days:
            out.iloc[i, out.columns.get_loc("days_since_rebalance")] = 1.0
            cnt = 0

    out = out[
        [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "openinterest",
            "ma",
            "trend_up",
            "days_since_rebalance",
        ]
    ].copy()
    return out.dropna()


class Mt5SixtyFortyFeed(bt.feeds.PandasData):
    lines = (
        "ma",
        "trend_up",
        "days_since_rebalance",
    )
    params = (
        ("datetime", None),
        ("open", 0),
        ("high", 1),
        ("low", 2),
        ("close", 3),
        ("volume", 4),
        ("openinterest", 5),
        ("ma", 6),
        ("trend_up", 7),
        ("days_since_rebalance", 8),
    )


class SixtyFortyStrategy(bt.Strategy):
    params = dict(
        equity_weight=0.60,
        ma_period=200,
        rebalance_days=63,
        lot_size=1.0,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.last_rebalance = 0
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

        trend_up = float(self.data.trend_up[0]) > 0.5
        need_rebalance = float(self.data.days_since_rebalance[0]) > 0.5

        if not need_rebalance:
            return

        target_weight = self.p.equity_weight if trend_up else 0.30
        target_size = self._get_position_size(target_notional_pct=target_weight)

        if not self.position:
            if target_size > 0:
                self.buy_count += 1
                self.pending_order = self.buy(size=target_size)
        else:
            current_size = abs(self.position.size)
            if target_size < 0.01:
                self.sell_count += 1
                self.pending_order = self.close()
            elif abs(current_size - target_size) > target_size * 0.1:
                self.sell_count += 1
                self.pending_order = self.close()

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        pass
