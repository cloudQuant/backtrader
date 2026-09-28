#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "InstantaneousTrendFilterIndicator",
]


class InstantaneousTrendFilterIndicator(Indicator):
    """Indicator computing trend and trigger values from a low-lag trend filter."""

    lines = ("trend", "trigger")
    params = (("alpha", 0.07),)

    def __init__(self):
        """Initialize coefficients and warm-up requirements."""
        alpha = float(self.p.alpha)
        a2 = alpha * alpha
        self.k0 = alpha - a2 / 4.0
        self.k1 = 0.5 * a2
        self.k2 = alpha - 0.75 * a2
        self.k3 = 2.0 * (1.0 - alpha)
        self.k4 = (1.0 - alpha) ** 2
        self.addminperiod(1)

    def next(self):
        """Compute the current trend/trigger outputs."""
        price0 = float(self.data.close[0])
        if len(self) <= 4:
            trend = price0
        else:
            price1 = float(self.data.close[-1])
            price2 = float(self.data.close[-2])
            trend = (
                self.k0 * price0
                + self.k1 * price1
                - self.k2 * price2
                + self.k3 * float(self.l.trend[-1])
                - self.k4 * float(self.l.trend[-2])
            )
        self.l.trend[0] = trend
        if len(self) <= 2:
            self.l.trigger[0] = trend
        else:
            self.l.trigger[0] = 2.0 * trend - float(self.l.trend[-2])
