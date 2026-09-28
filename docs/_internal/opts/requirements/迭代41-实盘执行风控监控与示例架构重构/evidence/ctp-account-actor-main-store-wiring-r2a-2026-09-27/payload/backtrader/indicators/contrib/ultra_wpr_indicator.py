#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math
from collections import deque

from .. import (
    Indicator,
    WilliamsR,
)

__all__ = [
    "UltraWPRIndicator",
]


class CountSmoother:
    """Incremental moving-average smoother supporting several MA methods.

    Maintains rolling state so each ``update`` call returns the smoothed value
    for one of the SMA, LWMA/JJMA, SMMA, or EMA methods.
    """

    def __init__(self, method, period):
        """Initialize the smoother.

        Args:
            method: Smoothing method name (e.g. ``sma``, ``lwma``, ``smma``).
            period: Smoothing window length (clamped to at least 1).
        """
        self.method = str(method).lower()
        self.period = max(1, int(period))
        self.values = deque(maxlen=self.period)
        self.state = None

    def update(self, value):
        """Add a new sample and return the updated smoothed value.

        Args:
            value: The new raw value to incorporate.

        Returns:
            The smoothed value after including ``value``.
        """
        value = float(value)
        if self.method in {"sma", "mode_sma"}:
            self.values.append(value)
            return sum(self.values) / len(self.values)
        if self.method in {"lwma", "mode_lwma", "jjma", "mode_jjma"}:
            self.values.append(value)
            weights = list(range(1, len(self.values) + 1))
            return sum(v * w for v, w in zip(self.values, weights)) / sum(weights)
        if self.method in {"smma", "mode_smma"}:
            if self.state is None:
                self.state = value
            else:
                self.state = ((self.period - 1) * self.state + value) / self.period
            return self.state
        alpha = 2.0 / (self.period + 1.0)
        if self.state is None:
            self.state = value
        else:
            self.state = self.state + alpha * (value - self.state)
        return self.state


class UltraWPRIndicator(Indicator):
    """Ultra Williams %R oscillator emitting bulls and bears strength lines."""

    lines = (
        "bulls",
        "bears",
    )
    params = (
        ("wpr_period", 13),
        ("w_method", "jjma"),
        ("start_length", 3),
        ("w_phase", 100),
        ("xstep", 5),
        ("xsteps_total", 10),
        ("smooth_method", "jjma"),
        ("smooth_length", 3),
        ("smooth_phase", 100),
    )

    def __init__(self):
        """Build the WPR fan, per-length smoothers, and output smoothers."""
        self._periods = [
            int(self.p.start_length + self.p.xstep * i) for i in range(int(self.p.xsteps_total) + 1)
        ]
        self._wpr_indicators = [
            WilliamsR(self.data, period=self.p.wpr_period) for _ in self._periods
        ]
        self._smoothers = [CountSmoother(self.p.w_method, period) for period in self._periods]
        self._prev_values = [None for _ in self._periods]
        self._bull_smoother = CountSmoother(self.p.smooth_method, self.p.smooth_length)
        self._bear_smoother = CountSmoother(self.p.smooth_method, self.p.smooth_length)
        self.addminperiod(self.p.wpr_period + max(self._periods) + self.p.smooth_length + 5)

    def next(self):
        """Count rising vs falling smoothed WPR lines and emit bulls/bears."""
        upsch = 0.0
        dnsch = 0.0
        current_values = []
        base_wpr = float(self._wpr_indicators[0][0])
        if math.isnan(base_wpr):
            self.lines.bulls[0] = float("nan")
            self.lines.bears[0] = float("nan")
            return
        for index, smoother in enumerate(self._smoothers):
            value = smoother.update(base_wpr)
            current_values.append(value)
            prev = self._prev_values[index]
            if prev is None:
                continue
            if value > prev:
                upsch += 1.0
            else:
                dnsch += 1.0
        self.lines.bulls[0] = self._bull_smoother.update(upsch)
        self.lines.bears[0] = self._bear_smoother.update(dnsch)
        self._prev_values = current_values

    def once(self, start, end):
        """Vectorized batch computation of bulls/bears over a bar range.

        Args:
            start: Index of the first bar to compute (inclusive).
            end: Index just past the last bar to compute (exclusive).
        """
        base_wpr_array = self._wpr_indicators[0].lines[0].array
        bulls_line = self.lines.bulls.array
        bears_line = self.lines.bears.array
        for line in (bulls_line, bears_line):
            while len(line) < end:
                line.append(float("nan"))

        smoothers = [CountSmoother(self.p.w_method, period) for period in self._periods]
        prev_values = [None for _ in self._periods]
        bull_smoother = CountSmoother(self.p.smooth_method, self.p.smooth_length)
        bear_smoother = CountSmoother(self.p.smooth_method, self.p.smooth_length)
        actual_end = min(end, len(base_wpr_array))
        for i in range(start, actual_end):
            upsch = 0.0
            dnsch = 0.0
            current_values = []
            base_wpr = float(base_wpr_array[i])
            if math.isnan(base_wpr):
                bulls_line[i] = float("nan")
                bears_line[i] = float("nan")
                continue
            for index, smoother in enumerate(smoothers):
                value = smoother.update(base_wpr)
                current_values.append(value)
                prev = prev_values[index]
                if prev is None:
                    continue
                if value > prev:
                    upsch += 1.0
                else:
                    dnsch += 1.0
            bulls_line[i] = bull_smoother.update(upsch)
            bears_line[i] = bear_smoother.update(dnsch)
            prev_values = current_values

        self._smoothers = smoothers
        self._prev_values = prev_values
        self._bull_smoother = bull_smoother
        self._bear_smoother = bear_smoother
