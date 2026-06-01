#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "SafeADX",
    "SafeAMA",
]


class SafeADX(Indicator):
    """ADX indicator implementation without division by zero pitfalls."""

    lines = ("adx",)
    params = (("period", 14),)

    def __init__(self):
        """Set minimum lookback period."""
        self.addminperiod(self.p.period + 3)

    def next(self):
        """Compute safe directional movement and ADX-like intensity."""
        pdm_vals = []
        mdm_vals = []
        tr_vals = []
        for idx in range(self.p.period):
            high0 = float(self.data.high[-idx])
            high1 = float(self.data.high[-idx - 1])
            low0 = float(self.data.low[-idx])
            low1 = float(self.data.low[-idx - 1])
            close1 = float(self.data.close[-idx - 1])
            up_move = high0 - high1
            down_move = low1 - low0
            pdm = up_move if up_move > down_move and up_move > 0 else 0.0
            mdm = down_move if down_move > up_move and down_move > 0 else 0.0
            tr = max(high0 - low0, abs(high0 - close1), abs(low0 - close1))
            pdm_vals.append(pdm)
            mdm_vals.append(mdm)
            tr_vals.append(tr)
        tr_sum = sum(tr_vals)
        if tr_sum <= 1e-12:
            self.lines.adx[0] = 0.0
            return
        pdi = 100.0 * sum(pdm_vals) / tr_sum
        mdi = 100.0 * sum(mdm_vals) / tr_sum
        denom = pdi + mdi
        if denom <= 1e-12:
            self.lines.adx[0] = 0.0
            return
        self.lines.adx[0] = 100.0 * abs(pdi - mdi) / denom


class SafeAMA(Indicator):
    """Adaptive moving average indicator with safe initialization."""

    lines = ("ama",)
    params = (
        ("period", 9),
        ("fast_period", 2),
        ("slow_period", 30),
    )

    def __init__(self):
        """Initialize adaptive moving average state and warm-up window."""
        self._prev = None
        self.addminperiod(self.p.period + 3)

    def next(self):
        """Update AMA based on efficiency ratio and smoothing."""
        if len(self) == 0 or self._prev is None:
            self._prev = float(self.data.close[0])
            self.lines.ama[0] = self._prev
            return
        direction = abs(float(self.data.close[0]) - float(self.data.close[-self.p.period]))
        volatility = 0.0
        for idx in range(self.p.period):
            volatility += abs(float(self.data.close[-idx]) - float(self.data.close[-idx - 1]))
        efficiency = 0.0 if volatility <= 1e-12 else direction / volatility
        fast_sc = 2.0 / (self.p.fast_period + 1.0)
        slow_sc = 2.0 / (self.p.slow_period + 1.0)
        smoothing = (efficiency * (fast_sc - slow_sc) + slow_sc) ** 2
        current = self._prev + smoothing * (float(self.data.close[0]) - self._prev)
        self.lines.ama[0] = current
        self._prev = current
