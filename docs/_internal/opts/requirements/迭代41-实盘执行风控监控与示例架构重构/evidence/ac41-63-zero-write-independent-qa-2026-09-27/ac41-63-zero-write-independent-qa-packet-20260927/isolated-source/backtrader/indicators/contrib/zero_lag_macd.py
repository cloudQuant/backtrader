#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
)

__all__ = [
    "ZeroLagMacd",
]


class ZeroLagMacd(Indicator):
    """Zero-lag MACD indicator using double-smoothed EMA differences."""

    lines = ("macd", "signal")
    params = (
        ("fast", 12),
        ("slow", 26),
    )

    def __init__(self):
        """Build fast/slow ZLEMA components and signal line."""
        ema_fast = ExponentialMovingAverage(self.data, period=self.p.fast)
        ema_fast2 = ExponentialMovingAverage(ema_fast, period=self.p.fast)
        zlema_fast = 2.0 * ema_fast - ema_fast2
        ema_slow = ExponentialMovingAverage(self.data, period=self.p.slow)
        ema_slow2 = ExponentialMovingAverage(ema_slow, period=self.p.slow)
        zlema_slow = 2.0 * ema_slow - ema_slow2
        self.lines.macd = zlema_fast - zlema_slow
        self.lines.signal = ExponentialMovingAverage(self.lines.macd, period=9)
