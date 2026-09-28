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
    "T3Average",
    "T3Trix",
]


class T3Average(Indicator):
    """Tillson T3 moving average built from a six-stage EMA cascade."""

    lines = ("t3",)
    params = (
        ("period", 10),
        ("vfactor", 0.7),
    )

    def __init__(self):
        """Build the six EMA stages and combine them into the T3 line.

        Side effects:
            Creates the cascade of six EMAs and assigns ``t3`` as the
            volume-factor-weighted combination of the third through sixth stages.
        """
        period = max(int(self.p.period), 1)
        vfactor = min(max(float(self.p.vfactor), 0.0), 1.0)
        e1 = EMA(self.data, period=period)
        e2 = EMA(e1, period=period)
        e3 = EMA(e2, period=period)
        e4 = EMA(e3, period=period)
        e5 = EMA(e4, period=period)
        e6 = EMA(e5, period=period)

        c1 = -(vfactor**3)
        c2 = 3 * vfactor**2 + 3 * vfactor**3
        c3 = -6 * vfactor**2 - 3 * vfactor - 3 * vfactor**3
        c4 = 1 + 3 * vfactor + vfactor**3 + 3 * vfactor**2
        self.l.t3 = c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3


class T3Trix(Indicator):
    """TRIX-style oscillator built from fast and slow T3 rate-of-change lines."""

    lines = ("fast", "slow", "hist")
    params = (
        ("xlength1", 10),
        ("xlength2", 18),
        ("xphase", 70),
    )

    def __init__(self):
        """Build fast/slow T3 averages and their normalized rate-of-change lines.

        Side effects:
            Derives the volume factor from ``xphase``, builds the fast and slow
            ``T3Average`` lines, and assigns ``fast``/``slow`` as their per-bar
            relative changes with ``hist`` aliased to ``fast``.
        """
        vfactor = min(max(float(self.p.xphase) / 100.0, 0.0), 1.0)
        fast_t3 = T3Average(self.data.close, period=int(self.p.xlength1), vfactor=vfactor)
        slow_t3 = T3Average(self.data.close, period=int(self.p.xlength2), vfactor=vfactor)
        self.l.fast = btfunc.DivByZero(fast_t3 - fast_t3(-1), fast_t3(-1), zero=0.0)
        self.l.slow = btfunc.DivByZero(slow_t3 - slow_t3(-1), slow_t3(-1), zero=0.0)
        self.l.hist = self.l.fast
