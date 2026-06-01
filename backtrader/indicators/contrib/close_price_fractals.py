#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "ClosePriceFractals",
]


class ClosePriceFractals(Indicator):
    """Custom 5-period Fractal indicator calculated solely on closing prices.

    Lines:
        upper: Contains fractal peak closing price if upper fractal is formed.
        lower: Contains fractal valley closing price if lower fractal is formed.
    """

    lines = ("upper", "lower")

    def __init__(self):
        """Initialize the indicator with a minimum period of 5 bars."""
        self.addminperiod(5)

    def next(self):
        """Determine if a peak or valley fractal forms on bar -2 based on close prices."""
        self.lines.upper[0] = float("nan")
        self.lines.lower[0] = float("nan")
        candidate = float(self.data.close[-2])
        if (
            candidate > float(self.data.close[-3])
            and candidate > float(self.data.close[-4])
            and candidate >= float(self.data.close[-1])
            and candidate >= float(self.data.close[0])
        ):
            self.lines.upper[0] = candidate
        if (
            candidate < float(self.data.close[-3])
            and candidate < float(self.data.close[-4])
            and candidate <= float(self.data.close[-1])
            and candidate <= float(self.data.close[0])
        ):
            self.lines.lower[0] = candidate
