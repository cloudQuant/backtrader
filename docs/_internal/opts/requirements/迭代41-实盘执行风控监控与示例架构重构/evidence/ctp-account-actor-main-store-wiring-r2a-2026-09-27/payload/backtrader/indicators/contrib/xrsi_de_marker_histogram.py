#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    RSI,
    DeMarker,
    Indicator,
)

__all__ = [
    "XrsiDeMarkerHistogram",
]


class XrsiDeMarkerHistogram(Indicator):
    """Blend RSI and DeMarker into a smoothed histogram line."""

    lines = ("value",)
    params = (
        ("ind_period", 14),
        ("rsi_price", "close"),
        ("high_level", 60.0),
        ("low_level", 40.0),
        ("xma_method", "SMA"),
        ("x_length", 5),
        ("x_phase", 15),
    )

    def __init__(self):
        """Instantiate RSI and DeMarker and initialize smoothing buffers."""
        self.rsi = RSI(self.data.close, period=self.p.ind_period)
        self.demarker = DeMarker(self.data, period=self.p.ind_period)
        self._raw_buf = []
        self._smooth_prev = None
        self.addminperiod(self.p.ind_period + self.p.x_length + 5)

    def _smooth_value(self, raw_value):
        method = str(self.p.xma_method).upper()
        if method in ("MODE_SMA_", "SMA"):
            period = max(1, int(self.p.x_length))
            if len(self._raw_buf) < period:
                return raw_value
            return sum(self._raw_buf[-period:]) / float(period)

        length = max(1, int(self.p.x_length))
        phase = max(-100, min(100, int(self.p.x_phase)))
        alpha = 2.0 / (length + 1.0)
        alpha *= 1.0 + 0.35 * (phase / 100.0)
        alpha = max(0.01, min(0.99, alpha))
        if self._smooth_prev is None or not math.isfinite(self._smooth_prev):
            smooth = raw_value
        else:
            smooth = self._smooth_prev + alpha * (raw_value - self._smooth_prev)
        self._smooth_prev = smooth
        return smooth

    def next(self):
        """Compute and smooth the combined histogram value."""
        raw_value = (float(self.rsi[0]) + 100.0 * float(self.demarker.demarker[0])) / 2.0
        self._raw_buf.append(raw_value)
        self.lines.value[0] = self._smooth_value(raw_value)
