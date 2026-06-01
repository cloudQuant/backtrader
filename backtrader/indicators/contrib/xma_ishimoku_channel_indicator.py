#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    EMA,
    SMA,
    Highest,
    Indicator,
    Lowest,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "XMAIshimokuChannelIndicator",
]


def resolve_ma_class(name):
    """Resolve a moving-average identifier into a Backtrader indicator class."""
    mode = str(name).lower()
    if mode in {"sma", "mode_sma"}:
        return SMA
    if mode in {"ema", "mode_ema"}:
        return EMA
    if mode in {"smma", "mode_smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


class XMAIshimokuChannelIndicator(Indicator):
    """Compute XMA-smoothed midpoint channel lines."""

    lines = (
        "mid",
        "upper",
        "lower",
    )
    params = (
        ("up_period", 3),
        ("dn_period", 3),
        ("up_mode", "high"),
        ("dn_mode", "low"),
        ("xma_method", "sma"),
        ("xlength", 100),
        ("xphase", 15),
        ("up_percent", 1.0),
        ("dn_percent", 1.0),
        ("price_shift", 0),
    )

    def __init__(self):
        """Prepare indicator buffers and min-period for channel outputs."""
        ma_cls = resolve_ma_class(self.p.xma_method)
        highest = Highest(self.data.high, period=self.p.up_period)
        lowest = Lowest(self.data.low, period=self.p.dn_period)
        midpoint = (highest + lowest) / 2.0
        self.lines.mid = ma_cls(midpoint, period=self.p.xlength) + self.p.price_shift
        self.lines.upper = self.lines.mid * (1.0 + self.p.up_percent / 100.0)
        self.lines.lower = self.lines.mid * (1.0 - self.p.dn_percent / 100.0)
        self.addminperiod(max(self.p.up_period, self.p.dn_period, self.p.xlength) + 3)
