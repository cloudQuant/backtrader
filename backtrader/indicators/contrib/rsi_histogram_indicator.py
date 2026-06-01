#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    RSI,
    Indicator,
)

__all__ = [
    "RSIHistogramIndicator",
]


class RSIHistogramIndicator(Indicator):
    """Compute RSI values and convert to a three-state color histogram."""

    lines = ("value", "midline", "color_state")
    params = (
        ("rsi_period", 14),
        ("high_level", 60),
        ("low_level", 40),
    )

    def __init__(self):
        """Initialize RSI and minimum period."""
        self.rsi = RSI(self.data.close, period=self.p.rsi_period, safediv=True)
        self.addminperiod(self.p.rsi_period + 1)

    def next(self):
        """Update value, midline, and current color state."""
        rsi_value = float(self.rsi[0])
        color = 1.0
        if rsi_value > float(self.p.high_level):
            color = 0.0
        elif rsi_value < float(self.p.low_level):
            color = 2.0
        self.lines.value[0] = rsi_value
        self.lines.midline[0] = 50.0
        self.lines.color_state[0] = color
