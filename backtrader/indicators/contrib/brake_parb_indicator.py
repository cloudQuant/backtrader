#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "BrakeParbIndicator",
]


class BrakeParbIndicator(Indicator):
    """Parabolic-style trailing-stop indicator with flip arrows.

    Maintains a power-curve stop that rises while long (and falls while short)
    from a begin price; when price breaks the stop the direction flips. Exposes
    the active stop on ``up``/``down`` lines and direction-flip cues on
    ``buy``/``sell`` lines.
    """

    lines = ("buy", "sell", "up", "down")
    params = (
        ("a", 1.5),
        ("b", 1.0),
        ("bigin_shift", 10.0),
    )

    def __init__(self):
        """Set the minimum period and initialize the parabolic-stop state."""
        self.addminperiod(5)
        self._is_long = True
        self._max_price = float("-inf")
        self._min_price = float("inf")
        self._begin_bar = 0
        self._begin_price = None

    def next(self):
        """Advance the parabolic stop and emit up/down stop and flip lines.

        Extends the stop along the power curve, flips direction (resetting the
        begin price and extremes) when price breaks the stop, and sets the
        ``up``/``down`` stop lines plus ``buy``/``sell`` flip cues for the bar.
        """
        if self._begin_price is None:
            self._begin_price = float(self.data.low[0])
        self._max_price = max(self._max_price, float(self.data.high[0]))
        self._min_price = min(self._min_price, float(self.data.low[0]))
        bars_since_begin = max(0, len(self.data) - 1 - self._begin_bar)
        b = float(self.p.b) * 0.00001 * 15.0
        bigin_shift = float(self.p.bigin_shift) * 0.00001
        parab = math.pow(max(0.0, float(bars_since_begin)), float(self.p.a)) * b
        value = self._begin_price + parab if self._is_long else self._begin_price - parab
        if self._is_long and value > float(self.data.low[0]):
            self._is_long = False
            self._begin_price = self._max_price + bigin_shift
            self._begin_bar = len(self.data) - 1
            value = self._begin_price
            self._max_price = float("-inf")
            self._min_price = float("inf")
        elif (not self._is_long) and value < float(self.data.high[0]):
            self._is_long = True
            self._begin_price = self._min_price - bigin_shift
            self._begin_bar = len(self.data) - 1
            value = self._begin_price
            self._max_price = float("-inf")
            self._min_price = float("inf")
        prev_up = float(self.lines.up[-1]) if len(self) > 0 else 0.0
        prev_dn = float(self.lines.down[-1]) if len(self) > 0 else 0.0
        if self._is_long:
            self.lines.up[0] = value
            self.lines.down[0] = 0.0
        else:
            self.lines.up[0] = 0.0
            self.lines.down[0] = value
        self.lines.buy[0] = (
            self.lines.down[0] if prev_up > 0.0 and float(self.lines.down[0]) > 0.0 else 0.0
        )
        self.lines.sell[0] = (
            self.lines.up[0] if prev_dn > 0.0 and float(self.lines.up[0]) > 0.0 else 0.0
        )
