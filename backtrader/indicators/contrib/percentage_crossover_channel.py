#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "PercentageCrossoverChannel",
]


class PercentageCrossoverChannel(Indicator):
    """Percent-based dynamic channel indicator.

    The middle line is gradually adjusted toward current price with separate
    upper/lower bands derived from the configured percentage distance.
    """

    lines = ("upper", "middle", "lower")
    params = (("percent", 50.0),)

    def __init__(self):
        """Initialize percent offsets and minimum warm-up settings."""
        self.addminperiod(2)
        percent = max(self.p.percent, 0.001) / 100.0
        self.plus_value = 1 + percent / 100.0
        self.minus_value = 1 - percent / 100.0

    def next(self):
        """Update middle, upper, and lower channel lines for the current bar."""
        price = float(self.data.close[0])
        # ``price`` is a built-in float. Its self-difference is zero only
        # when finite; for NaN or either infinity it is NaN. This avoids
        # consulting a replaceable module callback on every bar.
        invalid = price - price
        if invalid != 0.0:
            if price == price:  # noqa: PLR0124 - infinity, not a NaN sentinel
                from ...linebuffer import _reject_factor_infinity

                _reject_factor_infinity(self.lines.middle, price)
            self.lines.middle[0] = invalid
            self.lines.upper[0] = invalid
            self.lines.lower[0] = invalid
            return
        if len(self.data) == 1 or self.lines.middle[-1] != self.lines.middle[-1]:
            middle = price
        else:
            prev_middle = float(self.lines.middle[-1])
            if price * self.minus_value > prev_middle:
                middle = price * self.minus_value
            elif price * self.plus_value < prev_middle:
                middle = price * self.plus_value
            else:
                middle = prev_middle
        self.lines.middle[0] = middle
        self.lines.upper[0] = middle * self.plus_value
        self.lines.lower[0] = middle * self.minus_value
