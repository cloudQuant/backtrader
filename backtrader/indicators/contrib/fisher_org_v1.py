#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "FisherOrgV1",
]


def _price(data, mode, ago=0):
    """Return a price value from OHLC data based on a mode selector.

    Parameters
    ----------
    data : DataFeed
        Data feed with open/high/low/close lines.
    mode : int
        Price mode: 2=open, 3=high, 4=low, 5=(h+l)/2, 6=(h+l+c)/3,
        7=(2c+h+l)/4, 8=(o+c)/2, 9=(o+h+l+c)/4; default returns close.
    ago : int
        Bar offset.

    Returns
    -------
    float
        Selected price value.
    """
    o = float(data.open[-ago])
    h = float(data.high[-ago])
    low_price = float(data.low[-ago])
    c = float(data.close[-ago])
    if mode == 2:
        return o
    if mode == 3:
        return h
    if mode == 4:
        return low_price
    if mode == 5:
        return (h + low_price) / 2.0
    if mode == 6:
        return (h + low_price + c) / 3.0
    if mode == 7:
        return (2.0 * c + h + low_price) / 4.0
    if mode == 8:
        return (o + c) / 2.0
    if mode == 9:
        return (o + h + low_price + c) / 4.0
    return c


class FisherOrgV1(Indicator):
    """Fisher Transform indicator producing a Gaussian-like signal line and its lagged trigger.

    Lines
    -----
    fisher : float
        Current smoothed Fisher Transform value.
    trigger : float
        Previous bar's fisher value, used for crossover detection.
    """

    lines = ("fisher", "trigger")
    params = (
        ("length", 7),
        ("ipc", 1),
    )

    def __init__(self):
        """Initialise indicator state and smoothing recursive value."""
        self.addminperiod(int(self.p.length) + 2)
        self._value1 = 0.0

    def next(self):
        """Compute Fisher Transform value and set fisher/trigger lines."""
        length = int(self.p.length)
        highs = [float(self.data.high[-i]) for i in range(length)]
        lows = [float(self.data.low[-i]) for i in range(length)]
        smax = max(highs)
        smin = min(lows)
        if smax == smin:
            smax += 1e-12
        price = _price(self.data, int(self.p.ipc), 0)
        wpr = (price - smin) / (smax - smin)
        value0 = (wpr - 0.5) + 0.67 * self._value1
        value0 = min(max(value0, -0.999), 0.999)
        fisher_prev = float(self.lines.fisher[-1]) if len(self) > 1 else 0.0
        if not math.isfinite(fisher_prev):
            fisher_prev = 0.0
        res2 = (1.0 + value0) / (1.0 - value0)
        if res2 < 1e-7:
            res2 = 1.0
        fisher = 0.5 * math.log(res2) + 0.5 * fisher_prev
        self.lines.fisher[0] = fisher
        self.lines.trigger[0] = fisher_prev
        self._value1 = value0
