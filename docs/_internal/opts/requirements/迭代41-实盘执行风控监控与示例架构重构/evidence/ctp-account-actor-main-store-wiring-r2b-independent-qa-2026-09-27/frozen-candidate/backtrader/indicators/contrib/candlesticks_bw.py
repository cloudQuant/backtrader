#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    SMA,
    AwesomeOscillator,
    Indicator,
)

__all__ = [
    "CandlesticksBW",
]


class CandlesticksBW(Indicator):
    """Indicator that encodes AO/AC state into a numeric candle color code."""

    lines = ("color",)
    params = ()

    def __init__(self):
        """Set up AO and AC dependencies and minimum period."""
        self.addminperiod(40)
        self.ao = AwesomeOscillator(self.data)
        self.ac = self.ao - SMA(self.ao, period=5)

    def next(self):
        """Compute the color code for the current bar."""
        ao0 = float(self.ao[0])
        ao1 = float(self.ao[-1])
        ac0 = float(self.ac[0])
        ac1 = float(self.ac[-1])
        open_ = float(self.data.open[0])
        close = float(self.data.close[0])
        if ao0 >= ao1 and ac0 >= ac1:
            color = 0.0 if open_ <= close else 1.0
        elif ao0 <= ao1 and ac0 <= ac1:
            color = 5.0 if open_ >= close else 4.0
        else:
            color = 2.0 if open_ <= close else 3.0
        self.lines.color[0] = color
