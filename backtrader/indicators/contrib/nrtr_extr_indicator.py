#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "NRTRExtrIndicator",
]


class NRTRExtrIndicator(Indicator):
    """Reconstructs NRTR_extr indicator from its MQ5 source.

    Same as NRTR but uses high/low extremes instead of close for price tracking.
    In uptrend: price = max(price, high[bar]); check close < value.
    In downtrend: price = min(price, low[bar]); check close > value.
    On flip up: price = low[bar], value = price*(1-dK).
    On flip down: price = high[bar], value = price*(1+dK).
    """

    lines = ("trend_up", "trend_down", "sign_up", "sign_down")
    params = (
        ("iperiod", 10),
        ("idig", 0),
    )

    def __init__(self):
        """Initialize internal NRTR state and warm-up period."""
        self._period = int(self.p.iperiod)
        self._idig = int(self.p.idig)
        self._trend = 0
        self._trend_prev = 0
        self._price = 0.0
        self._value = 0.0
        self._first = True
        self.addminperiod(self._period + 2)

    def next(self):
        """Update trend state, channel values, and signal lines."""
        period = self._period

        if self._first:
            self._trend_prev = 0
            self._price = float(self.data.close[0])
            self._value = self._price
            self._first = False

        self._trend = self._trend_prev
        price = self._price
        value = self._value

        avg_range = 0.0
        for i in range(period):
            avg_range += abs(float(self.data.high[-i]) - float(self.data.low[-i]))
        avg_range /= period

        digits_diff = 5 - self._idig
        dK = avg_range / pow(10, digits_diff) if pow(10, digits_diff) != 0 else avg_range

        cur_close = float(self.data.close[0])
        cur_high = float(self.data.high[0])
        cur_low = float(self.data.low[0])

        if self._trend >= 0:
            price = max(price, cur_high)  # uses high instead of close
            value = max(value, price * (1.0 - dK))
            if cur_close < value:
                price = cur_high  # uses high
                value = price * (1.0 + dK)
                self._trend = -1
        elif self._trend <= 0:
            price = min(price, cur_low)  # uses low instead of close
            value = min(value, price * (1.0 + dK))
            if cur_close > value:
                price = cur_low  # uses low
                value = price * (1.0 - dK)
                self._trend = 1

        tu = value if self._trend > 0 else 0.0
        td = value if self._trend < 0 else 0.0
        su = tu if self._trend_prev < 0 and self._trend > 0 else 0.0
        sd = td if self._trend_prev > 0 and self._trend < 0 else 0.0

        self._trend_prev = self._trend
        self._price = price
        self._value = value

        self.lines.trend_up[0] = tu
        self.lines.trend_down[0] = td
        self.lines.sign_up[0] = su
        self.lines.sign_down[0] = sd
