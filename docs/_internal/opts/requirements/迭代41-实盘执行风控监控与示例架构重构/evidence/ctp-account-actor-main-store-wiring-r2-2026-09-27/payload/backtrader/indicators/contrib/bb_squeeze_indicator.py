#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ATR,
    SMA,
    BollingerBands,
    Indicator,
    Momentum,
)

__all__ = [
    "BBSqueezeIndicator",
]


class BBSqueezeIndicator(Indicator):
    """
    Bollinger Band Squeeze: measures BB width relative to Keltner Channel.
    Histogram = close - midline of (BB + KC) / 2, colored by whether
    BB is inside KC (squeeze on) or outside (squeeze off).
    Simplified: histogram = momentum (close - SMA), signal direction by
    BB bandwidth vs KC bandwidth.
    """

    lines = (
        "squeeze",
        "momentum",
    )
    params = (
        ("bb_period", 20),
        ("bb_dev", 2.0),
        ("kc_period", 20),
        ("kc_mult", 1.5),
        ("mom_period", 12),
    )

    def __init__(self):
        """Instantiate BB, ATR, SMA, and momentum indicators used by the squeeze."""
        self.bb = BollingerBands(self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev)
        self.atr = ATR(self.data, period=self.p.kc_period)
        self.sma = SMA(self.data.close, period=self.p.kc_period)
        self.mom = Momentum(self.data.close, period=self.p.mom_period)

    def next(self):
        """Calculate squeeze state and momentum for every new bar."""
        bb_upper = float(self.bb.top[0])
        bb_lower = float(self.bb.bot[0])
        bb_width = bb_upper - bb_lower

        kc_upper = float(self.sma[0]) + self.p.kc_mult * float(self.atr[0])
        kc_lower = float(self.sma[0]) - self.p.kc_mult * float(self.atr[0])
        kc_width = kc_upper - kc_lower

        self.lines.squeeze[0] = 1.0 if bb_width < kc_width else -1.0
        self.lines.momentum[0] = float(self.mom[0])
