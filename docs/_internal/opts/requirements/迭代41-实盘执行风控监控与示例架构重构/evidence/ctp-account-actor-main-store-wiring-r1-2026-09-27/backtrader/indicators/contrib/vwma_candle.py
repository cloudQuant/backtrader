#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "VWMACandle",
]


class VWMACandle(Indicator):
    """Volume-weighted candle color indicator.

    Computes volume-weighted moving averages of the open and close over
    ``length`` bars and emits a ``color`` line of 2.0 (bullish), 0.0 (bearish)
    or 1.0 (neutral) depending on their relationship.
    """

    lines = ("color",)
    params = (
        ("length", 12),
        ("use_tick_volume", True),
    )

    def __init__(self):
        """Reserve the warm-up window needed for the volume-weighted average."""
        self.addminperiod(int(self.p.length) + 3)

    def _vwma(self, field, ago=0):
        length = int(self.p.length)
        total = 0.0
        vals = 0.0
        for i in range(length):
            idx = ago + i
            vol = (
                float(self.data.volume[-idx])
                if self.p.use_tick_volume
                else float(self.data.openinterest[-idx])
            )
            total += max(vol, 0.0)
            vals += float(getattr(self.data, field)[-idx]) * max(vol, 0.0)
        return float(getattr(self.data, field)[-ago]) if total == 0.0 else vals / total

    def next(self):
        """Set the candle color from volume-weighted open vs close."""
        op = self._vwma("open", 0)
        cl = self._vwma("close", 0)
        color = 1.0
        if op < cl:
            color = 2.0
        elif op > cl:
            color = 0.0
        self.lines.color[0] = color
