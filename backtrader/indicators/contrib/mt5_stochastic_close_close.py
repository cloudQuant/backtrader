#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "Mt5StochasticCloseClose",
]


class Mt5StochasticCloseClose(Indicator):
    """Close-close based Smoothed Stochastic oscillator implementation."""

    lines = ("main", "signal")
    params = (
        ("k_period", 5),
        ("d_period", 3),
        ("slowing", 3),
    )

    def __init__(self):
        """Set calculation parameters and initial EMA-smoothed state."""
        self.addminperiod(self.p.k_period + max(self.p.d_period, self.p.slowing) + 2)
        self._slow_prev = None
        self._signal_prev = None
        self._alpha_slow = 2.0 / (self.p.slowing + 1.0)
        self._alpha_signal = 2.0 / (self.p.d_period + 1.0)

    def next(self):
        """Compute smoothed %K/%D and emit current oscillator lines."""
        closes = [float(self.data.close[-i]) for i in range(self.p.k_period)]
        highest_close = max(closes)
        lowest_close = min(closes)
        close0 = float(self.data.close[0])
        if highest_close == lowest_close:
            raw_k = 0.0
        else:
            raw_k = 100.0 * (close0 - lowest_close) / (highest_close - lowest_close)

        if self._slow_prev is None:
            slow_val = raw_k
        else:
            slow_val = self._slow_prev + self._alpha_slow * (raw_k - self._slow_prev)

        if self._signal_prev is None:
            signal_val = slow_val
        else:
            signal_val = self._signal_prev + self._alpha_signal * (slow_val - self._signal_prev)

        self.lines.main[0] = slow_val
        self.lines.signal[0] = signal_val
        self._slow_prev = slow_val
        self._signal_prev = signal_val
