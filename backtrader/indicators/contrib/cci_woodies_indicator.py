#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "CCIWoodiesIndicator",
]


def _applied_price(data, price_type, ago=0):
    """Get price based on ENUM_APPLIED_PRICE."""
    o = float(data.open[-ago])
    h = float(data.high[-ago])
    low_price = float(data.low[-ago])
    c = float(data.close[-ago])
    if price_type == 0:
        return c  # PRICE_CLOSE
    if price_type == 1:
        return o  # PRICE_OPEN
    if price_type == 2:
        return h  # PRICE_HIGH
    if price_type == 3:
        return low_price  # PRICE_LOW
    if price_type == 4:
        return (h + low_price) / 2  # PRICE_MEDIAN
    if price_type == 5:
        return (h + low_price + c) / 3  # PRICE_TYPICAL
    if price_type == 6:
        return (h + low_price + c + c) / 4  # PRICE_WEIGHTED
    return c


class CCIWoodiesIndicator(Indicator):
    """Reconstructs CCI_Woodies indicator.

    DRAW_FILLING between FastCCI and SlowCCI.
    Buffer 0 = FastCCI, Buffer 1 = SlowCCI.
    When Fast > Slow → bullish (Lime fill); when Fast < Slow → bearish (Plum fill).
    """

    lines = ("fast_cci", "slow_cci")
    params = (
        ("fast_period", 6),
        ("fast_price", 4),
        ("slow_period", 14),
        ("slow_price", 4),
    )

    def __init__(self):
        """Build internal period and price type state for fast and slow CCI."""
        self._fp = int(self.p.fast_period)
        self._sp = int(self.p.slow_period)
        self._fpr = int(self.p.fast_price)
        self._spr = int(self.p.slow_price)
        self.addminperiod(max(self._fp, self._sp) + 2)

    def _calc_cci(self, period, price_type):
        prices = []
        for i in range(period):
            if i >= len(self.data):
                break
            prices.append(_applied_price(self.data, price_type, i))
        if not prices:
            return 0.0
        mean = sum(prices) / len(prices)
        mad = sum(abs(p - mean) for p in prices) / len(prices)
        tp = prices[0]  # current bar
        if mad == 0:
            return 0.0
        return (tp - mean) / (0.015 * mad)

    def next(self):
        """Compute and store current fast and slow CCI values for each bar."""
        self.lines.fast_cci[0] = self._calc_cci(self._fp, self._fpr)
        self.lines.slow_cci[0] = self._calc_cci(self._sp, self._spr)
