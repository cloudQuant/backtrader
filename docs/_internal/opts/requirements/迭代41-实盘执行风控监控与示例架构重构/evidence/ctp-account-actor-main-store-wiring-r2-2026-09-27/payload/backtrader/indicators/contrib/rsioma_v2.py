#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    EMA,
    RSI,
    Indicator,
    Momentum,
)

__all__ = [
    "RsiomaV2",
]


class RsiomaV2(Indicator):
    """RSIOMA V2 indicator: an RSI of smoothed price with an EMA signal line.

    The price close is smoothed with an EMA (optionally transformed by a
    Momentum step), an RSI is computed on that series to form the rsioma line,
    and the rsioma is smoothed again with an EMA to form the signal line.
    """

    lines = ("rsioma", "signal")
    params = (
        ("rsioma_period", 14),
        ("ma_rsioma_period", 21),
        ("mom_period", 1),
    )

    def __init__(self):
        """Build the EMA/Momentum/RSI/EMA chain for the rsioma and signal lines."""
        base = EMA(self.data.close, period=max(int(self.p.rsioma_period), 1))
        if int(self.p.mom_period) > 1:
            base = Momentum(base, period=int(self.p.mom_period))
        self.l.rsioma = RSI(base, period=max(int(self.p.rsioma_period), 1), safediv=True)
        self.l.signal = EMA(self.l.rsioma, period=max(int(self.p.ma_rsioma_period), 1))
