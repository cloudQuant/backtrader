#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "FiboCandlesIndicator",
]


FIBO_LEVELS = {1: 0.236, 2: 0.382, 3: 0.500, 4: 0.618, 5: 0.762}


def _reject_infinite_result(line, value):
    """Reject computed infinity when the callback has a strict factor context."""
    from ...linebuffer import _factor_context_for_line

    context = _factor_context_for_line(line)
    if context is not None:
        from ...research.strict import reject_infinity

        phase = getattr(context, "phase", None) or "next"
        reject_infinity(context, value, phase, operation=line)


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
        highs = [float(self.data.high[-i]) for i in range(period)]
        lows = [float(self.data.low[-i]) for i in range(period)]
        max_high = max(highs)
        min_low = min(lows)
        rng = max_high - min_low
        o = float(self.data.open[0])
        c = float(self.data.close[0])
        float(self.data.high[0])
        float(self.data.low[0])
        trend = self._trend
        if not all(math.isfinite(value) for value in (*highs, *lows, o, c)):
            self.lines.color[0] = math.nan
            return
        if math.isinf(rng):
            _reject_infinite_result(self.lines.color, rng)

        if o > c:  # bearish candle
            distance = c - min_low if trend < 0 else None
            if distance is not None and math.isinf(distance):
                _reject_infinite_result(self.lines.color, distance)
            if not (trend < 0 and rng * level < distance):
                trend = 1
            else:
                trend = -1
        else:  # bullish candle
            distance = max_high - c if trend > 0 else None
            if distance is not None and math.isinf(distance):
                _reject_infinite_result(self.lines.color, distance)
            if not (trend > 0 and rng * level < distance):
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
