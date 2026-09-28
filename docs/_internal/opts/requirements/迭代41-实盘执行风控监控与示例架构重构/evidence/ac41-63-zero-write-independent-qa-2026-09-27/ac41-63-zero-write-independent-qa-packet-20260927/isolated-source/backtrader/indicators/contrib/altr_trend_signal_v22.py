#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    AverageDirectionalMovementIndex,
    Indicator,
)

__all__ = [
    "AltrTrendSignalV22",
]


class AltrTrendSignalV22(Indicator):
    """Adaptive trend breakout indicator used by the strategy."""

    lines = ("sell", "buy")
    params = (
        ("k", 30),
        ("kstop", 0.5),
        ("kperiod", 150),
        ("per_adx", 14),
    )

    def __init__(self):
        """Create ADX trend indicator and initialize state."""
        self.adx = AverageDirectionalMovementIndex(self.data, period=max(int(self.p.per_adx), 1))
        self.addminperiod(max(int(self.p.per_adx), 1) + 2)
        self._trend = 0

    def next(self):
        """Compute breakout level and emit short/long trigger values."""
        self.lines.buy[0] = 0.0
        self.lines.sell[0] = 0.0

        adx_prev = float(self.adx[-1]) if len(self) > 1 else float(self.adx[0])
        if math.isnan(adx_prev) or adx_prev <= 0:
            return

        ssp = max(int(math.ceil(float(self.p.kperiod) / adx_prev)), 1)
        lookback = min(ssp, len(self.data))
        if lookback <= 0:
            return

        highs = []
        lows = []
        avg_range = 0.0
        for idx in range(lookback):
            high = float(self.data.high[-idx])
            low = float(self.data.low[-idx])
            highs.append(high)
            lows.append(low)
            avg_range += abs(high - low)

        trading_range = avg_range / (ssp + 1.0)
        ss_max = max(highs)
        ss_min = min(lows)
        threshold = (ss_max - ss_min) * float(self.p.k) / 100.0
        smin = ss_min + threshold
        smax = ss_max - threshold

        previous_trend = self._trend
        trend = previous_trend
        close = float(self.data.close[0])

        if close < smin:
            trend = -1
        if close > smax:
            trend = 1

        if previous_trend == 0:
            previous_trend = trend

        if trend != previous_trend and close > smax:
            self.lines.buy[0] = float(self.data.low[0]) - trading_range * float(self.p.kstop)
        if trend != previous_trend and close < smin:
            self.lines.sell[0] = float(self.data.high[0]) + trading_range * float(self.p.kstop)

        self._trend = trend if trend != 0 else previous_trend
