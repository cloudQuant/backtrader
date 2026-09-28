#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "AtrNormalizeHistogram",
]


class AtrNormalizeHistogram(Indicator):
    """ATR-normalized histogram indicator for multi-timeframe signal generation.

    Computes a normalized ATR value where xdiff is smoothed range ratio,
    colored by threshold crossings (high/middle/low levels).
    """

    lines = ("value", "color")
    params = (
        ("ma_method1", "SMA"),
        ("length1", 14),
        ("phase1", 15),
        ("ma_method2", "SMA"),
        ("length2", 14),
        ("phase2", 15),
        ("high_level", 60),
        ("middle_level", 50),
        ("low_level", 40),
        ("point", 0.01),
    )

    def __init__(self):
        """Initialise indicator state: rolling buffers and prior smoothing values."""
        self._diff_buf = []
        self._range_buf = []
        self._diff_prev = None
        self._range_prev = None
        self.addminperiod(max(int(self.p.length1), int(self.p.length2)) + 5)

    def _smooth(self, raw_value, method, length, phase, buf, prev_attr):
        """Apply SMA, LWMA, or exponential smoothing to a raw value.

        Args:
            raw_value: The raw input value.
            method: Smoothing method ('SMA', 'LWMA', or EMA variant).
            length: Lookback window length.
            phase: Phase parameter for EMA variants (-100 to 100).
            buf: Rolling buffer list.
            prev_attr: Attribute name to store previous smoothed value.

        Returns:
            Smoothed value as float.
        """
        method = str(method).upper()
        length = max(1, int(length))
        if method in ("MODE_SMA_", "SMA"):
            if len(buf) < length:
                return raw_value
            return sum(buf[-length:]) / float(length)
        if method in ("MODE_LWMA_", "LWMA"):
            if len(buf) < length:
                return raw_value
            weights = list(range(1, length + 1))
            values = buf[-length:]
            return sum(v * w for v, w in zip(values, weights)) / float(sum(weights))

        prev = getattr(self, prev_attr)
        phase = max(-100, min(100, int(phase)))
        alpha = 2.0 / (length + 1.0)
        alpha *= 1.0 + 0.35 * (phase / 100.0)
        alpha = max(0.01, min(0.99, alpha))
        if prev is None or not math.isfinite(prev):
            smooth = raw_value
        else:
            smooth = prev + alpha * (raw_value - prev)
        setattr(self, prev_attr, smooth)
        return smooth

    def next(self):
        """Compute per-bar normalized ATR value and color classification."""
        prev_close = float(self.data.close[-1]) if len(self.data) > 1 else float(self.data.close[0])
        diff = float(self.data.close[0]) - float(self.data.low[0])
        range_value = max(float(self.data.high[0]), prev_close) - min(
            float(self.data.low[0]), prev_close
        )
        self._diff_buf.append(diff)
        self._range_buf.append(range_value)
        xdiff = self._smooth(
            diff, self.p.ma_method1, self.p.length1, self.p.phase1, self._diff_buf, "_diff_prev"
        )
        xrange = self._smooth(
            range_value,
            self.p.ma_method2,
            self.p.length2,
            self.p.phase2,
            self._range_buf,
            "_range_prev",
        )
        xrange = max(xrange, float(self.p.point))
        value = 100.0 * xdiff / xrange
        if value > float(self.p.high_level):
            color = 0.0
        elif value > float(self.p.middle_level):
            color = 1.0
        elif value < float(self.p.low_level):
            color = 4.0
        elif value < float(self.p.middle_level):
            color = 3.0
        else:
            color = 2.0
        self.lines.value[0] = value
        self.lines.color[0] = color
