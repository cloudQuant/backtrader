#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from ...linebuffer import _reject_factor_infinity
from .. import Indicator

__all__ = [
    "KDJIndicator",
]


class KDJIndicator(Indicator):
    """Indicator class implementing the custom KDJ oscillator.

    Lines:
        kdc (Line): Output difference line (%K - %D).
        rsv (Line): Raw Stochastic Value line.
        k (Line): Smoothed %K line.
        d (Line): Smoothed %D line.
    """

    lines = ("kdc", "rsv", "k", "d")
    params = (
        ("m1", 3),
        ("m2", 6),
        ("kdj_period", 30),
    )

    def __init__(self):
        """Initialize the custom KDJ indicator and establish minimum warmup period."""
        self.addminperiod(int(self.p.kdj_period) + int(self.p.m2) + 2)

    @staticmethod
    def _finite(line, values):
        valid = True
        for value in values:
            if not math.isfinite(value):
                _reject_factor_infinity(line, value)
                valid = False
        return valid

    @staticmethod
    def _sum_checked(line, values):
        # Check each intermediate before a later NaN can mask an overflow.
        # Keep the interpreter's own sum for the output; Python versions may
        # use a different floating-point accumulation algorithm.
        result = 0
        for value in values:
            if math.isinf(value):
                _reject_factor_infinity(line, value)
            result += value
            if math.isinf(result):
                _reject_factor_infinity(line, result)
        return sum(values)

    def next(self):
        """Calculate RSV, %K, %D, and %K-%D values on each new bar."""
        kdj_period = int(self.p.kdj_period)
        m1 = int(self.p.m1)
        m2 = int(self.p.m2)
        highs = [float(self.data.high[-i]) for i in range(kdj_period)]
        lows = [float(self.data.low[-i]) for i in range(kdj_period)]
        close = float(self.data.close[0])
        rsv = float("nan")
        if self._finite(self.lines.rsv, highs + lows + [close]):
            max_high = max(highs)
            min_low = min(lows)
            denominator = max_high - min_low
            if self._finite(self.lines.rsv, (denominator,)):
                if denominator == 0.0:
                    rsv = 1.0
                else:
                    numerator = close - min_low
                    if self._finite(self.lines.rsv, (numerator,)):
                        ratio = numerator / denominator
                        if self._finite(self.lines.rsv, (ratio,)):
                            result = ratio * 100.0
                            if self._finite(self.lines.rsv, (result,)):
                                rsv = result
        self.lines.rsv[0] = rsv
        rsv_values = []
        for i in range(m1):
            value = float(self.lines.rsv[-i]) if len(self) > i else 50.0
            rsv_values.append(value)
        rsv_sum = self._sum_checked(self.lines.k, rsv_values)
        self.lines.k[0] = (
            rsv_sum / float(m1)
            if self._finite(self.lines.k, (rsv_sum,))
            else float("nan")
        )
        k_values = []
        for i in range(m2):
            value = float(self.lines.k[-i]) if len(self) > i else 50.0
            k_values.append(value)
        k_sum = self._sum_checked(self.lines.d, k_values)
        self.lines.d[0] = (
            k_sum / float(m2) if self._finite(self.lines.d, (k_sum,)) else float("nan")
        )
        difference = float(self.lines.k[0]) - float(self.lines.d[0])
        self.lines.kdc[0] = (
            difference if self._finite(self.lines.kdc, (difference,)) else float("nan")
        )
