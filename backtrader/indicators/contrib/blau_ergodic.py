#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import backtrader.functions as btfunc

from .. import (
    EMA,
    Indicator,
)

__all__ = [
    "BlauErgodic",
]


class BlauErgodic(Indicator):
    """Blau Ergodic oscillator: triple-smoothed normalised momentum.

    Price momentum and its absolute value are each triple-smoothed with EMAs;
    the main line is 100 times their ratio (guarded against division by zero).
    The signal line is an EMA of the main line, and spread is their difference.
    """

    lines = ("main", "signal", "spread")
    params = (
        ("xlength", 2),
        ("xlength1", 20),
        ("xlength2", 5),
        ("xlength3", 3),
        ("xlength4", 3),
    )

    def __init__(self):
        """Build the triple-EMA momentum chain for main, signal and spread."""
        shift = max(int(self.p.xlength) - 1, 1)
        momentum = self.data.close - self.data.close(-shift)
        abs_momentum = abs(momentum)

        xmom = EMA(momentum, period=int(self.p.xlength1))
        xxmom = EMA(xmom, period=int(self.p.xlength2))
        xxxmom = EMA(xxmom, period=int(self.p.xlength3))

        xabsmom = EMA(abs_momentum, period=int(self.p.xlength1))
        xxabsmom = EMA(xabsmom, period=int(self.p.xlength2))
        xxxabsmom = EMA(xxabsmom, period=int(self.p.xlength3))

        self.l.main = btfunc.DivByZero(100.0 * xxxmom, xxxabsmom, zero=0.0)
        self.l.signal = EMA(self.l.main, period=int(self.p.xlength4))
        self.l.spread = self.l.main - self.l.signal
