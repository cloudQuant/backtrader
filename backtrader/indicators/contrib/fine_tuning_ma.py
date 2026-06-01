#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "FineTuningMA",
]


def _price_value(data, shift, mode):
    key = str(mode).lower()
    open_ = float(data.open[-shift]) if shift else float(data.open[0])
    high = float(data.high[-shift]) if shift else float(data.high[0])
    low = float(data.low[-shift]) if shift else float(data.low[0])
    close = float(data.close[-shift]) if shift else float(data.close[0])
    if key in ("close", "1", "price_close"):
        return close
    if key in ("open", "2", "price_open"):
        return open_
    if key in ("high", "3", "price_high"):
        return high
    if key in ("low", "4", "price_low"):
        return low
    if key in ("median", "5", "price_median"):
        return (high + low) / 2.0
    if key in ("typical", "6", "price_typical"):
        return (close + high + low) / 3.0
    if key in ("weighted", "7", "price_weighted"):
        return (2.0 * close + high + low) / 4.0
    if key in ("simple", "8", "price_simpl"):
        return (open_ + close) / 2.0
    if key in ("quarter", "9", "price_quarter"):
        return (open_ + close + high + low) / 4.0
    if key in ("trendfollow0", "10", "price_trendfollow0"):
        if close > open_:
            return high
        if close < open_:
            return low
        return close
    if key in ("trendfollow1", "11", "price_trendfollow1"):
        if close > open_:
            return (high + close) / 2.0
        if close < open_:
            return (low + close) / 2.0
        return close
    return close


class FineTuningMA(Indicator):
    """Weighted moving average with rank/shift-shaped per-bar weights."""

    lines = ("value",)
    params = (
        ("ftma", 10),
        ("rank1", 2.0),
        ("rank2", 2.0),
        ("rank3", 2.0),
        ("shift1", 1.0),
        ("shift2", 1.0),
        ("shift3", 1.0),
        ("ipc", "typical"),
    )

    def __init__(self):
        """Precompute the normalized FineTuningMA weights and warmup period."""
        self.ftma = max(int(self.p.ftma), 1)
        self.weights = []
        total = 0.0
        for h in range(self.ftma):
            denom = max(self.ftma - 1.0, 1.0)
            part = float(h) / denom
            w = self.p.shift1 + math.pow(part, float(self.p.rank1)) * (1.0 - self.p.shift1)
            w = (
                self.p.shift2 + math.pow(1.0 - part, float(self.p.rank2)) * (1.0 - self.p.shift2)
            ) * w
            w = (
                self.p.shift3
                + math.pow(1.0 - abs(part - 0.5) * 2.0, float(self.p.rank3)) * (1.0 - self.p.shift3)
            ) * w
            self.weights.append(w)
            total += w
        self.weights = [w / total for w in self.weights] if total else [1.0 / self.ftma] * self.ftma
        self.addminperiod(self.ftma + 2)

    def next(self):
        """Output the weighted average of the applied price over the window."""
        if len(self.data) < self.ftma:
            self.l.value[0] = _price_value(self.data, 0, self.p.ipc)
            return
        total = 0.0
        for h in range(self.ftma):
            total += self.weights[h] * _price_value(self.data, h, self.p.ipc)
        self.l.value[0] = total
