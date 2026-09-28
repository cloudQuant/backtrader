#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "LocoIndicator",
]


def _applied_price(data, mode, ago=0):
    mode = str(mode).lower()
    o = float(data.open[ago])
    h = float(data.high[ago])
    low_price = float(data.low[ago])
    c = float(data.close[ago])
    if mode in ("price_open", "open", "price_open_"):
        return o
    if mode in ("price_high", "high", "price_high_"):
        return h
    if mode in ("price_low", "low", "price_low_"):
        return low_price
    if mode in ("price_median", "median", "price_median_"):
        return (h + low_price) / 2.0
    if mode in ("price_typical", "typical", "price_typical_"):
        return (h + low_price + c) / 3.0
    if mode in ("price_weighted", "weighted", "price_weighted_"):
        return (h + low_price + 2.0 * c) / 4.0
    if mode in ("price_simpl", "simpl", "simple", "price_simpl_"):
        return (o + c) / 2.0
    if mode in ("price_quarter", "quarter", "price_quarter_"):
        return (h + low_price + o + c) / 4.0
    return c


class LocoIndicator(Indicator):
    """Loco follow-through line with a binary bullish/bearish color flag.

    Tracks the applied price and produces a ``loco`` line plus a ``color`` flag
    (0 = bullish, 1 = bearish) that flips when price reverses its run of higher
    or lower readings.
    """

    lines = ("loco", "color")
    params = (
        ("length", 1),
        ("ipc", "price_close_"),
        ("price_shift_points", 0.0),
    )

    def __init__(self):
        """Reserve the warm-up window and initialise carry-forward state."""
        self.addminperiod(max(int(self.p.length), 1) + 2)
        self._initialized = False
        self._prev = None

    def next(self):
        """Update the Loco line and color flag for the current bar."""
        series0 = _applied_price(self.data, self.p.ipc, 0)
        if not self._initialized:
            result = series0
            color = 0
            self._prev = result
            self._initialized = True
        else:
            prev = float(self._prev)
            ago = min(int(self.p.length), len(self.data) - 1)
            series1 = _applied_price(self.data, self.p.ipc, -ago)
            if series1 > prev and series0 > prev:
                result = max(prev, series0 * 0.999)
                color = 0
            elif series1 < prev and series0 < prev:
                result = min(prev, series0 * 1.001)
                color = 1
            else:
                if series0 > prev:
                    result = series0 * 0.999
                    color = 0
                else:
                    result = series0 * 1.001
                    color = 1
            self._prev = result
        self.lines.loco[0] = result + float(self.p.price_shift_points)
        self.lines.color[0] = color
