#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "VWAPCloseIndicator",
]


class VWAPCloseIndicator(Indicator):
    """Reconstructs VWAP_Close indicator.

    VWAP = sum(close[i] * volume[i], i=0..n-1) / sum(volume[i], i=0..n-1)
    Uses tick volume by default.
    Buffer 0 = VWAP line.
    """

    lines = ("vwap",)
    params = (("n", 2),)

    def __init__(self):
        """Initialize VWAP rolling window size and minimum period.

        The indicator keeps the latest ``n`` bar prices and volumes and starts
        producing values only after enough history is available.
        """
        self._n = int(self.p.n)
        self.addminperiod(self._n + 1)

    def next(self):
        """Compute and emit the next VWAP-close value.

        The calculation uses close*volume weighted average over up to ``n`` prior
        bars and falls back to the previous VWAP value when volume is not
        available.
        """
        n = self._n
        sum1 = 0.0
        sum2 = 0
        for i in range(n):
            if i >= len(self.data):
                break
            c = float(self.data.close[-i])
            v = float(self.data.volume[-i])
            if v < 1:
                v = 1
            sum1 += c * v
            sum2 += v

        if sum2 > 0:
            self.lines.vwap[0] = sum1 / sum2
        else:
            prev = (
                float(self.lines.vwap[-1])
                if len(self.lines.vwap) > 1
                else float(self.data.close[0])
            )
            self.lines.vwap[0] = prev if not math.isnan(prev) else float(self.data.close[0])
