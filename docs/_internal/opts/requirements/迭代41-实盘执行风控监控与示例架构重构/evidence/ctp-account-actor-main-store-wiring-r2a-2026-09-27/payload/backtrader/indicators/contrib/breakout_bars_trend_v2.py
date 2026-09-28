#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "BreakoutBarsTrendV2",
]


class BreakoutBarsTrendV2(Indicator):
    """Custom trend-breakout indicator calculating dynamic trend boundaries and reversals.

    Lines:
        value: Trend state value (1.0 or positive series count for uptrend, -1.0 or negative series count for downtrend).
    """

    lines = ("value",)
    params = (
        ("reversal_mode", "PERCENT"),
        ("delta", 1.0),
        ("point", 0.01),
    )

    def __init__(self):
        """Initialize the indicator parameters, trend tracking states, and seed prices."""
        self._mode = str(self.p.reversal_mode).upper()
        self._delta = float(self.p.delta)
        if self._mode == "PIPS":
            if self._delta < 30.0:
                self._delta = 1000.0
        else:
            if self._delta < 0.03 or self._delta > 30.0:
                self._delta = 1.0
        self._seed_close = None
        self._seed_high = None
        self._seed_low = None
        self._initialized = False
        self._uptrend = None
        self._min_price = None
        self._max_price = None
        self.addminperiod(1)

    def _reversal_distance(self, price):
        """Calculate the absolute price pullback distance threshold required for a trend reversal.

        Args:
            price (float): Extreme reference price.

        Returns:
            float: Symmetrical price pullback distance.
        """
        if self._mode == "PIPS":
            return float(self._delta) * float(self.p.point)
        return (float(price) / 100.0) * float(self._delta)

    def next(self):
        """Determine if a trend reversal has occurred, and update trend extremes."""
        close = float(self.data.close[0])
        high = float(self.data.high[0])
        low = float(self.data.low[0])

        if self._seed_close is None:
            self._seed_close = close
            self._seed_high = high
            self._seed_low = low
            self.lines.value[0] = 0.0
            return

        if not self._initialized:
            reversal = self._reversal_distance(self._seed_close)
            if abs(close - self._seed_close) - reversal <= 0.00001:
                self.lines.value[0] = 0.0
                return
            if close > self._seed_close:
                self._initialized = True
                self._uptrend = True
                self._min_price = self._seed_low
                self._max_price = high
                self.lines.value[0] = 1.0
            else:
                self._initialized = True
                self._uptrend = False
                self._min_price = low
                self._max_price = self._seed_high
                self.lines.value[0] = -1.0
            return

        prev_value = float(self.lines.value[-1])
        prev_high = float(self.data.high[-1])
        prev_low = float(self.data.low[-1])

        self._min_price = min(float(self._min_price), prev_low)
        self._max_price = max(float(self._max_price), prev_high)

        if self._uptrend:
            reversal = self._reversal_distance(self._max_price)
            if close > float(self._max_price):
                self.lines.value[0] = prev_value + 1.0
            elif close < max(float(self._max_price), high) - reversal and close < prev_low:
                self._uptrend = False
                self.lines.value[0] = -1.0
                self._max_price = high
                self._min_price = low
            else:
                self.lines.value[0] = prev_value
        else:
            reversal = self._reversal_distance(self._min_price)
            if close < float(self._min_price):
                self.lines.value[0] = prev_value - 1.0
            elif close > min(float(self._min_price), low) + reversal and close > prev_high:
                self._uptrend = True
                self.lines.value[0] = 1.0
                self._min_price = low
                self._max_price = high
            else:
                self.lines.value[0] = prev_value
