#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "PivotZigZagProxy",
]


class PivotZigZagProxy(Indicator):
    """Compact pivot and zigzag proxy indicator used by the strategy.

    It tracks the nearest recent high/low pivot pairs over a configurable depth
    and emits them as four separate output lines.
    """

    lines = ("high0", "low0", "high1", "low1")
    params = (("depth", 12),)

    def __init__(self):
        """Initialize minimum required bars for pivot calculation."""
        self.addminperiod(self.p.depth * 3)

    def next(self):
        """Compute and expose the most recent two high and two low pivot levels."""
        pivots = []
        lookback = min(len(self.data) - 1, self.p.depth * 8)
        for idx in range(2, lookback):
            high = float(self.data.high[-idx])
            low = float(self.data.low[-idx])
            if high >= float(self.data.high[-idx - 1]) and high >= float(self.data.high[-idx + 1]):
                pivots.append(("high", high, idx))
            if low <= float(self.data.low[-idx - 1]) and low <= float(self.data.low[-idx + 1]):
                pivots.append(("low", low, idx))
        pivots.sort(key=lambda item: item[2])
        pivots = pivots[:4]
        highs = [value for kind, value, _ in pivots if kind == "high"]
        lows = [value for kind, value, _ in pivots if kind == "low"]
        self.lines.high0[0] = highs[0] if len(highs) > 0 else 0.0
        self.lines.high1[0] = highs[1] if len(highs) > 1 else 0.0
        self.lines.low0[0] = lows[0] if len(lows) > 0 else 0.0
        self.lines.low1[0] = lows[1] if len(lows) > 1 else 0.0
