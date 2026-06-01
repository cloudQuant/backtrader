#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "ColorXDerivative",
]


class ColorXDerivative(Indicator):
    """Smoothed price-derivative indicator with a momentum color state.

    Computes the average rate of change of a weighted price over ``i_slowing``
    bars, smoothed across ``xlength`` windows, and classifies it into a color
    index: rising/falling while positive (0/1) or negative (3/4), with 2 as a
    neutral state.
    """

    lines = ("value", "color_idx")
    params = (
        ("i_slowing", 34),
        ("xlength", 15),
    )

    def __init__(self):
        """Set the minimum period to cover the slowing and smoothing windows."""
        self.addminperiod(max(self.p.i_slowing + 2, self.p.xlength + 2))

    def _price(self, ago=0):
        return (
            float(self.data.high[ago])
            + float(self.data.low[ago])
            + 2.0 * float(self.data.close[ago])
        ) / 4.0

    def next(self):
        """Compute the smoothed derivative value and its color state.

        Stores the smoothed derivative on the ``value`` line and a color index on
        ``color_idx`` reflecting whether the value is rising or falling above or
        below zero relative to the previous bar.
        """
        der = 100.0 * (self._price(0) - self._price(-self.p.i_slowing)) / float(self.p.i_slowing)
        window = [
            100.0
            * (self._price(-i) - self._price(-(i + self.p.i_slowing)))
            / float(self.p.i_slowing)
            for i in range(self.p.xlength)
        ]
        smooth = sum(window) / float(len(window)) if window else der
        self.lines.value[0] = smooth
        prev = float(self.lines.value[-1]) if len(self) > 1 else smooth
        color = 2.0
        if smooth > 0:
            color = 0.0 if prev <= smooth else 1.0
        elif smooth < 0:
            color = 4.0 if prev >= smooth else 3.0
        self.lines.color_idx[0] = color
