#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ATR,
    Indicator,
)

__all__ = [
    "AroonOscillatorSignAlert",
]


class AroonOscillatorSignAlert(Indicator):
    """Aroon oscillator alert indicator with buy/sell level trigger lines."""

    lines = ("sell", "buy", "osc")
    params = (
        ("atr_period", 14),
        ("aroon_period", 9),
        ("up_level", 50),
        ("dn_level", -50),
    )

    def __init__(self):
        """Initialize ATR/Aroon period constraints and ATR helper indicator."""
        self.addminperiod(max(int(self.p.atr_period), int(self.p.aroon_period)) + 3)
        self.atr = ATR(self.data, period=int(self.p.atr_period))

    def next(self):
        """Compute oscillator and emit trigger prices when levels are crossed."""
        p = int(self.p.aroon_period)
        highs = [float(self.data.high[-i]) for i in range(p)]
        lows = [float(self.data.low[-i]) for i in range(p)]
        highest = highs.index(max(highs))
        lowest = lows.index(min(lows))
        osc = 100.0 * (highest - lowest) / float(p)
        prev = float(self.lines.osc[-1]) if len(self) > 1 else osc
        self.lines.osc[0] = osc
        self.lines.buy[0] = float("nan")
        self.lines.sell[0] = float("nan")
        atr = float(self.atr[0])
        if osc > float(self.p.dn_level) and prev <= float(self.p.dn_level):
            self.lines.buy[0] = float(self.data.low[0]) - atr * 3.0 / 8.0
        if osc < float(self.p.up_level) and prev >= float(self.p.up_level):
            self.lines.sell[0] = float(self.data.high[0]) + atr * 3.0 / 8.0
