#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import backtrader.functions as btfunc

from .. import (
    EMA,
    Highest,
    Indicator,
    Lowest,
)

__all__ = [
    "BlauTSStochastic",
]


def _price_series(data, mode):
    key = str(mode).lower()
    if key in ("1", "close", "price_close"):
        return data.close
    if key in ("2", "open", "price_open"):
        return data.open
    if key in ("3", "high", "price_high"):
        return data.high
    if key in ("4", "low", "price_low"):
        return data.low
    if key in ("5", "median", "price_median"):
        return (data.high + data.low) / 2.0
    if key in ("6", "typical", "price_typical"):
        return (data.high + data.low + data.close) / 3.0
    if key in ("7", "weighted", "price_weighted"):
        return (data.high + data.low + data.close + data.close) / 4.0
    if key in ("8", "simple", "price_simpl"):
        return (data.open + data.close) / 2.0
    if key in ("9", "quarter", "price_quarter"):
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class BlauTSStochastic(Indicator):
    """Blau TS Stochastic: triple-smoothed stochastic momentum oscillator.

    A stochastic numerator (price minus lowest low) and its range (highest high
    minus lowest low) are each triple-smoothed with EMAs; the histogram is
    200 times their ratio minus 100 (guarded against division by zero), and an
    EMA of the histogram forms the signal line exposed on the down line.
    """

    lines = ("up", "down", "hist")
    params = (
        ("xlength", 5),
        ("xlength1", 20),
        ("xlength2", 5),
        ("xlength3", 3),
        ("xlength4", 3),
        ("ipc", "close"),
    )

    def __init__(self):
        """Build the triple-EMA stochastic chain for the hist/up/down lines."""
        price = _price_series(self.data, self.p.ipc)
        hh = Highest(self.data.high, period=int(self.p.xlength))
        ll = Lowest(self.data.low, period=int(self.p.xlength))
        stoch = price - ll
        range_line = hh - ll

        xstoch = EMA(stoch, period=int(self.p.xlength1))
        xxstoch = EMA(xstoch, period=int(self.p.xlength2))
        xxxstoch = EMA(xxstoch, period=int(self.p.xlength3))

        xrange = EMA(range_line, period=int(self.p.xlength1))
        xxrange = EMA(xrange, period=int(self.p.xlength2))
        xxxrange = EMA(xxrange, period=int(self.p.xlength3))

        hist = btfunc.DivByZero(200.0 * xxxstoch, xxxrange, zero=0.0) - 100.0
        signal = EMA(hist, period=int(self.p.xlength4))

        self.l.hist = hist
        self.l.up = hist
        self.l.down = signal
