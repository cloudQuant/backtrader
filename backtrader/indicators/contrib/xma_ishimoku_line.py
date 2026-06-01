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
    "XMAIshimokuLine",
]


def resolve_ma_class(name):
    """Map a moving-average name to its backtrader indicator class.

    Args:
        name: MA type name (e.g. ``sma``, ``ema``, ``smma`` or MT5-style
            ``mode_*`` variants).

    Returns:
        The matching backtrader moving-average indicator class, defaulting to
        the weighted moving average for unrecognized names.
    """
    mode = str(name).lower()
    if mode in {"sma", "mode_sma"}:
        return SMA
    if mode in {"ema", "mode_ema"}:
        return EMA
    if mode in {"smma", "mode_smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


class XMAIshimokuLine(Indicator):
    """Smoothed Ishimoku-style midprice line.

    Computes the midpoint of the rolling highest high and lowest low over the
    up/down periods, then smooths it with the configured moving average over
    ``xlength`` to produce a single ``xma`` trend line.
    """

    lines = ("xma",)
    params = (
        ("up_period", 3),
        ("dn_period", 3),
        ("xma_method", "sma"),
        ("xlength", 8),
        ("xphase", 15),
    )

    def __init__(self):
        """Build the high/low midpoint and its moving average; set min period."""
        highest = Highest(self.data.high, period=self.p.up_period)
        lowest = Lowest(self.data.low, period=self.p.dn_period)
        midpoint = (highest + lowest) / 2.0
        ma_cls = resolve_ma_class(self.p.xma_method)
        self.lines.xma = ma_cls(midpoint, period=self.p.xlength)
        self.addminperiod(max(self.p.up_period, self.p.dn_period, self.p.xlength) + 3)
