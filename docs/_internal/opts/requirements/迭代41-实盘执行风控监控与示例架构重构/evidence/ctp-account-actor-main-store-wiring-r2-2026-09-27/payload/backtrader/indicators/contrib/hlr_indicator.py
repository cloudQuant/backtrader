#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    Highest,
    Indicator,
    Lowest,
)

__all__ = [
    "HLRIndicator",
    "ZeroLagHLRIndicator",
]


class HLRIndicator(Indicator):
    """Base HLR indicator returning a normalized high-low range position."""

    lines = ("value",)
    params = (("period", 40),)

    def __init__(self):
        """Initialize highest/lowest trackers and line averaging setup."""
        period = int(self.p.period)
        self.highest = Highest(self.data.high, period=period)
        self.lowest = Lowest(self.data.low, period=period)
        self.mid = (self.data.high + self.data.low) / 2.0
        self.addminperiod(period + 1)

    def next(self):
        """Compute the HLR oscillator value for current bar."""
        hh = float(self.highest[0])
        ll = float(self.lowest[0])
        span = hh - ll
        self.l.value[0] = 0.0 if span == 0.0 else 100.0 * ((float(self.mid[0]) - ll) / span)


class ZeroLagHLRIndicator(Indicator):
    """Zero-lag variant of HLR computed from a blended set of HLR periods."""

    lines = ("fast", "slow")
    params = (
        ("smoothing", 15),
        ("factor1", 0.05),
        ("hlr_period1", 8),
        ("factor2", 0.1),
        ("hlr_period2", 21),
        ("factor3", 0.16),
        ("hlr_period3", 34),
        ("factor4", 0.26),
        ("hlr_period4", 55),
        ("factor5", 0.43),
        ("hlr_period5", 89),
        ("preserve_source_hlr3_weight", True),
    )

    def __init__(self):
        """Instantiate source HLR components and initialize smoothing state."""
        self.hlr1 = HLRIndicator(self.data, period=int(self.p.hlr_period1))
        self.hlr2 = HLRIndicator(self.data, period=int(self.p.hlr_period2))
        self.hlr3 = HLRIndicator(self.data, period=int(self.p.hlr_period3))
        self.hlr4 = HLRIndicator(self.data, period=int(self.p.hlr_period4))
        self.hlr5 = HLRIndicator(self.data, period=int(self.p.hlr_period5))
        self.smooth_const = (float(self.p.smoothing) - 1.0) / float(self.p.smoothing)
        self.hlr3_weight = float(
            self.p.factor2 if self.p.preserve_source_hlr3_weight else self.p.factor3
        )
        max_period = max(
            int(self.p.hlr_period1),
            int(self.p.hlr_period2),
            int(self.p.hlr_period3),
            int(self.p.hlr_period4),
            int(self.p.hlr_period5),
        )
        self.addminperiod((3 * max_period) + 3)

    def next(self):
        """Update fast and smoothed slow HLR outputs."""
        fast = (
            float(self.p.factor1) * float(self.hlr1.value[0])
            + float(self.p.factor2) * float(self.hlr2.value[0])
            + self.hlr3_weight * float(self.hlr3.value[0])
            + float(self.p.factor4) * float(self.hlr4.value[0])
            + float(self.p.factor5) * float(self.hlr5.value[0])
        )
        if len(self) <= 1:
            slow = fast / float(self.p.smoothing)
        else:
            slow = (fast / float(self.p.smoothing)) + (float(self.l.slow[-1]) * self.smooth_const)
        self.l.fast[0] = fast
        self.l.slow[0] = slow
