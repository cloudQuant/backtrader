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
    "PriceExtremeChannel",
]


class PriceExtremeChannel(Indicator):
    """Custom indicator calculating local highest highs and lowest lows.

    Lines:
        upper (Line): Channel upper boundary.
        lower (Line): Channel lower boundary.
    """

    lines = ("upper", "lower")
    params = (("multiplier", 5),)

    def __init__(self):
        """Initialize the custom highest/lowest channel lines and establish minimum warmup period."""
        period = max(int(self.p.multiplier), 1)
        self.lines.upper = Highest(self.data.high(-1), period=period)
        self.lines.lower = Lowest(self.data.low(-1), period=period)
        self.addminperiod(period + 2)
