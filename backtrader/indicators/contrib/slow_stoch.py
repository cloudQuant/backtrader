#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
    StochasticFull,
)

__all__ = [
    "SlowStoch",
]


class SlowStoch(Indicator):
    """EMA-smoothed slow stochastic exposing an oscillator and a signal line."""

    lines = ("sto", "signal")
    params = (
        ("k_period", 5),
        ("d_period", 3),
        ("slowing", 3),
        ("xlength", 5),
    )

    def __init__(self):
        """Build the StochasticFull and EMA-smooth its %D and slow %D lines."""
        stoch = StochasticFull(
            self.data,
            period=max(int(self.p.k_period), 1),
            period_dfast=max(int(self.p.d_period), 1),
            period_dslow=max(int(self.p.slowing), 1),
            safediv=True,
        )
        self.l.sto = ExponentialMovingAverage(stoch.percD, period=max(int(self.p.xlength), 1))
        self.l.signal = ExponentialMovingAverage(
            stoch.percDSlow, period=max(int(self.p.xlength), 1)
        )
