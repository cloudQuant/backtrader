#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "DerivativeIndicator",
]


APPLIED_PRICE_MAP = {
    "PRICE_CLOSE": 0,
    "PRICE_OPEN": 1,
    "PRICE_HIGH": 2,
    "PRICE_LOW": 3,
    "PRICE_MEDIAN": 4,
    "PRICE_TYPICAL": 5,
    "PRICE_WEIGHTED": 6,
    "PRICE_OPEN_CLOSE": 8,
    "PRICE_OHLC_AVERAGE": 9,
    "PRICE_DEMARK": 10,
    "PRICE_AVERAGE_DEMARK": 11,
}


class DerivativeIndicator(Indicator):
    """Derivative indicator derived from a selected applied price.

    The computed `value` line is a momentum-like slope:
    ``100 * (price[0] - price[-i_slowing]) / i_slowing``.
    """

    lines = ("value",)
    params = (
        ("i_slowing", 34),
        ("applied_price", "PRICE_WEIGHTED"),
    )

    def __init__(self):
        """Require at least ``i_slowing + 1`` bars before emitting values."""
        self.addminperiod(int(self.p.i_slowing) + 1)

    def _mode_value(self, value, default_value):
        if isinstance(value, str):
            return APPLIED_PRICE_MAP.get(value, default_value)
        return int(value)

    def _price(self, ago=0):
        mode = self._mode_value(self.p.applied_price, 0)
        open_ = float(self.data.open[ago])
        high = float(self.data.high[ago])
        low = float(self.data.low[ago])
        close = float(self.data.close[ago])
        if mode == 0:
            return close
        if mode == 1:
            return open_
        if mode == 2:
            return high
        if mode == 3:
            return low
        if mode == 4:
            return (high + low) / 2.0
        if mode == 5:
            return (close + high + low) / 3.0
        if mode == 6:
            return (2.0 * close + high + low) / 4.0
        if mode == 8:
            return (open_ + close) / 2.0
        if mode == 9:
            return (open_ + close + high + low) / 4.0
        if mode == 10:
            if close > open_:
                return high
            if close < open_:
                return low
            return close
        if mode == 11:
            if close > open_:
                return (high + close) / 2.0
            if close < open_:
                return (low + close) / 2.0
            return close
        return close

    def next(self):
        """Update the derivative value for the current bar."""
        lag = int(self.p.i_slowing)
        current = self._price(0)
        past = self._price(-lag)
        self.lines.value[0] = 100.0 * (current - past) / float(lag)
