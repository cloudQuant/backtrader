#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "FiboCandlesIndicator",
]


FIBO_LEVELS = {1: 0.236, 2: 0.382, 3: 0.500, 4: 0.618, 5: 0.762}


class FiboCandlesIndicator(Indicator):
    """Reconstructs the FiboCandles indicator from MQ5 source.

    Uses period-bar high/low range * fibo level to detect trend flips.
    color line: 0 = bullish (trend +1), 1 = bearish (trend -1).
    """

    lines = ("color",)
    params = (
        ("period", 10),
        ("fibo_level", 1),
    )

    def __init__(self):
        """Initialize indicator variables, selected fibonacci ratio level, and trend state."""
        self._level = FIBO_LEVELS.get(int(self.p.fibo_level), 0.236)
        self._trend = 1
        self.addminperiod(int(self.p.period) + 1)

    def next(self):
        """Determine trend direction and assign bullish/bearish candle colors."""
        period = int(self.p.period)
        level = self._level

        # maxHigh / minLow over [bar, bar+period) in MQ5 (as-series)
        # In backtrader forward indexing: last `period` bars including current
        max_high = max(float(self.data.high[-i]) for i in range(period))
        min_low = min(float(self.data.low[-i]) for i in range(period))
        rng = max_high - min_low

        o = float(self.data.open[0])
        c = float(self.data.close[0])
        float(self.data.high[0])
        float(self.data.low[0])
        trend = self._trend

        if o > c:  # bearish candle
            if not (trend < 0 and rng * level < c - min_low):
                trend = 1
            else:
                trend = -1
        else:  # bullish candle
            if not (trend > 0 and rng * level < max_high - c):
                trend = -1
            else:
                trend = 1

        # Color assignment
        if trend == 1:
            open_buf = max(o, c)
            close_buf = min(o, c)
        else:
            open_buf = min(o, c)
            close_buf = max(o, c)

        if open_buf > close_buf:
            self.lines.color[0] = 1.0  # bearish color
        else:
            self.lines.color[0] = 0.0  # bullish color

        self._trend = trend
