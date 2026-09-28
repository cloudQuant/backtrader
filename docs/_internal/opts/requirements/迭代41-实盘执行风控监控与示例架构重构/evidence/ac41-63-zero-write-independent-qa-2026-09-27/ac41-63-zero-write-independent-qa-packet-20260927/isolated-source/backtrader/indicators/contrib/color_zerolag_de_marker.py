#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    DeMarkerRollingIndicator,
    Indicator,
)

__all__ = [
    "ColorZerolagDeMarker",
]


class ColorZerolagDeMarker(Indicator):
    """Blend five weighted DeMarker oscillators into fast and slow trend lines."""

    lines = ("fast", "slow")
    params = (
        ("smoothing", 15),
        ("factor1", 0.05),
        ("demarker_period1", 8),
        ("factor2", 0.1),
        ("demarker_period2", 21),
        ("factor3", 0.16),
        ("demarker_period3", 34),
        ("factor4", 0.26),
        ("demarker_period4", 55),
        ("factor5", 0.43),
        ("demarker_period5", 89),
    )

    def __init__(self):
        """Build the five DeMarker sub-indicators and smoothing constants."""
        periods = [
            int(self.p.demarker_period1),
            int(self.p.demarker_period2),
            int(self.p.demarker_period3),
            int(self.p.demarker_period4),
            int(self.p.demarker_period5),
        ]
        self.addminperiod(3 * max(periods) + 5)
        self.dem1 = DeMarkerRollingIndicator(self.data, period=int(self.p.demarker_period1))
        self.dem2 = DeMarkerRollingIndicator(self.data, period=int(self.p.demarker_period2))
        self.dem3 = DeMarkerRollingIndicator(self.data, period=int(self.p.demarker_period3))
        self.dem4 = DeMarkerRollingIndicator(self.data, period=int(self.p.demarker_period4))
        self.dem5 = DeMarkerRollingIndicator(self.data, period=int(self.p.demarker_period5))
        self.smooth_const = (float(self.p.smoothing) - 1.0) / float(self.p.smoothing)
        self._initialized = False

    def next(self):
        """Weight DeMarker values into a fast trend and smoothed slow trend."""
        values = [
            float(self.dem1[0]),
            float(self.dem2[0]),
            float(self.dem3[0]),
            float(self.dem4[0]),
            float(self.dem5[0]),
        ]
        if any(not math.isfinite(value) for value in values):
            self.lines.fast[0] = float("nan")
            self.lines.slow[0] = float("nan")
            return
        osc1 = float(self.p.factor1) * values[0]
        osc2 = float(self.p.factor2) * values[1]
        osc3 = float(self.p.factor3) * values[2]
        osc4 = float(self.p.factor4) * values[3]
        osc5 = float(self.p.factor5) * values[4]
        fast_trend = osc1 + osc2 + osc3 + osc4 + osc5
        if not self._initialized:
            slow_trend = fast_trend / float(self.p.smoothing)
            self._initialized = True
        else:
            slow_trend = (
                fast_trend / float(self.p.smoothing)
                + float(self.lines.slow[-1]) * self.smooth_const
            )
        self.lines.fast[0] = fast_trend
        self.lines.slow[0] = slow_trend
