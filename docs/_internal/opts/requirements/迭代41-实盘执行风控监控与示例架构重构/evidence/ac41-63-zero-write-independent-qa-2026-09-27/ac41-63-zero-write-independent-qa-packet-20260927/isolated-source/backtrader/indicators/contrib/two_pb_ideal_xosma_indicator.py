#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from collections import deque

from .. import Indicator

__all__ = [
    "TwoPbIdealXOSMAIndicator",
]


class TwoPbIdealXOSMAIndicator(Indicator):
    """Compute the smoothed 2pbIdealXOSMA histogram from cascaded ideal-MAs."""

    lines = ("signal",)
    params = (
        ("period1", 10),
        ("period2", 10),
        ("periodx1", 10),
        ("periodx2", 10),
        ("periody1", 10),
        ("periody2", 10),
        ("periodz1", 10),
        ("periodz2", 10),
        ("smooth_method", "jjma"),
        ("smooth_period", 9),
        ("smooth_phase", 100),
    )

    def __init__(self):
        """Initialize ideal-MA stage weights, recursive states, and min period."""
        self._w1 = 1.0 / max(1, int(self.p.period1))
        self._w2 = 1.0 / max(1, int(self.p.period2))
        self._wx1 = 1.0 / max(1, int(self.p.periodx1))
        self._wx2 = 1.0 / max(1, int(self.p.periodx2))
        self._wy1 = 1.0 / max(1, int(self.p.periody1))
        self._wy2 = 1.0 / max(1, int(self.p.periody2))
        self._wz1 = 1.0 / max(1, int(self.p.periodz1))
        self._wz2 = 1.0 / max(1, int(self.p.periodz2))
        self._fast_state = None
        self._moving01 = None
        self._moving11 = None
        self._moving21 = None
        self._smooth_state = None
        self._smooth_values = deque(maxlen=max(1, int(self.p.smooth_period)))
        self.addminperiod(
            max(
                int(self.p.period1),
                int(self.p.period2),
                int(self.p.periodx1),
                int(self.p.periodx2),
                int(self.p.periody1),
                int(self.p.periody2),
                int(self.p.periodz1),
                int(self.p.periodz2),
                int(self.p.smooth_period),
            )
            + 5
        )

    @staticmethod
    def _ideal_ma_smooth(weight_1, weight_2, series_1, series_0, result_1):
        dseries = series_0 - series_1
        dseries2 = dseries * dseries - 1.0
        denominator = 1.0 + weight_2 * dseries2
        if denominator == 0:
            return result_1
        return (
            weight_1 * (series_0 - result_1) + result_1 + weight_2 * result_1 * dseries2
        ) / denominator

    def _smooth_histogram(self, value):
        method = str(self.p.smooth_method).lower()
        period = max(1, int(self.p.smooth_period))
        if method == "sma":
            self._smooth_values.append(value)
            return sum(self._smooth_values) / len(self._smooth_values)
        if method == "lwma":
            self._smooth_values.append(value)
            values = list(self._smooth_values)
            weights = list(range(1, len(values) + 1))
            return sum(v * w for v, w in zip(values, weights)) / sum(weights)
        if method == "smma":
            if self._smooth_state is None:
                self._smooth_state = value
            else:
                self._smooth_state = ((period - 1) * self._smooth_state + value) / period
            return self._smooth_state
        alpha = 2.0 / (period + 1.0)
        if self._smooth_state is None:
            self._smooth_state = value
        else:
            self._smooth_state = self._smooth_state + alpha * (value - self._smooth_state)
        return self._smooth_state

    def next(self):
        """Advance the ideal-MA cascade and emit the smoothed histogram value."""
        price = float(self.data.close[0])
        prev_price = float(self.data.close[-1]) if len(self.data) > 1 else price
        if self._fast_state is None:
            self._fast_state = price
            self._moving01 = price
            self._moving11 = price
            self._moving21 = price

        self._fast_state = self._ideal_ma_smooth(
            self._w1, self._w2, prev_price, price, self._fast_state
        )
        moving00 = self._ideal_ma_smooth(self._wx1, self._wx2, prev_price, price, self._moving01)
        moving10 = self._ideal_ma_smooth(
            self._wy1, self._wy2, self._moving01, moving00, self._moving11
        )
        moving20 = self._ideal_ma_smooth(
            self._wz1, self._wz2, self._moving11, moving10, self._moving21
        )

        self._moving01 = moving00
        self._moving11 = moving10
        self._moving21 = moving20

        raw_macd = self._fast_state - moving20
        self.lines.signal[0] = self._smooth_histogram(raw_macd)
