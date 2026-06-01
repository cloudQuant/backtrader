#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "XmaIchimoku",
    "TwoXmaIchimokuOscillator",
]


class XmaIchimoku(Indicator):
    """Calculate a smoothed midpoint of selected high/low ranges."""

    lines = ("value",)

    params = (
        ("up_period", 6),
        ("dn_period", 6),
        ("up_mode", "HIGH"),
        ("dn_mode", "LOW"),
        ("xma_method", "SMA"),
        ("x_length", 25),
        ("x_phase", 15),
        ("price_shift", 0.0),
    )

    def __init__(self):
        """Initialize Ichimoku-like windows and smoothing helpers."""
        self.addminperiod(
            max(int(self.p.up_period), int(self.p.dn_period)) + int(self.p.x_length) + 5
        )
        self._raw_buf = []
        self._smooth_prev = None

    def _series_value(self, mode, ago):
        mode = str(mode).upper()
        if mode == "OPEN":
            return float(self.data.open[ago])
        if mode == "LOW":
            return float(self.data.low[ago])
        if mode == "HIGH":
            return float(self.data.high[ago])
        return float(self.data.close[ago])

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
        """Compute smoothed range midpoint for each bar."""
        up_period = int(self.p.up_period)
        dn_period = int(self.p.dn_period)
        if len(self.data) < max(up_period, dn_period):
            self.lines.value[0] = 0.0
            return

        highs = [self._series_value(self.p.up_mode, -i) for i in range(up_period)]
        lows = [self._series_value(self.p.dn_mode, -i) for i in range(dn_period)]
        ish_up = max(highs)
        ish_dn = min(lows)
        raw_value = (ish_up + ish_dn) / 2.0
        self._raw_buf.append(raw_value)
        smooth = self._smooth_value(raw_value) + float(self.p.price_shift)
        self.lines.value[0] = smooth


class TwoXmaIchimokuOscillator(Indicator):
    """Combine two XMA windows into oscillator value and color channels."""

    lines = (
        "line",
        "color",
    )

    params = (
        ("up_period1", 6),
        ("dn_period1", 6),
        ("up_period2", 9),
        ("dn_period2", 9),
        ("up_mode1", "HIGH"),
        ("dn_mode1", "LOW"),
        ("up_mode2", "HIGH"),
        ("dn_mode2", "LOW"),
        ("xma1_method", "SMA"),
        ("xma2_method", "SMA"),
        ("x_length1", 25),
        ("x_length2", 80),
        ("x_phase", 15),
        ("point", 0.01),
    )

    def __init__(self):
        """Create two :class:`XmaIchimoku` instances and reset color state."""
        self.xma1 = XmaIchimoku(
            self.data,
            up_period=self.p.up_period1,
            dn_period=self.p.dn_period1,
            up_mode=self.p.up_mode1,
            dn_mode=self.p.dn_mode1,
            xma_method=self.p.xma1_method,
            x_length=self.p.x_length1,
            x_phase=self.p.x_phase,
        )
        self.xma2 = XmaIchimoku(
            self.data,
            up_period=self.p.up_period2,
            dn_period=self.p.dn_period2,
            up_mode=self.p.up_mode2,
            dn_mode=self.p.dn_mode2,
            xma_method=self.p.xma2_method,
            x_length=self.p.x_length2,
            x_phase=self.p.x_phase,
        )
        self._prev_color = 2.0

    def next(self):
        """Update oscillator value and derived color trend state."""
        point = float(self.p.point) if float(self.p.point) != 0 else 1.0
        line_value = (float(self.xma1[0]) - float(self.xma2[0])) / point
        self.lines.line[0] = line_value

        if len(self) < 2:
            self.lines.color[0] = 2.0
            self._prev_color = 2.0
            return

        prev_line = float(self.lines.line[-1])
        color = self._prev_color
        if line_value >= 0:
            if line_value > prev_line:
                color = 0.0
            elif line_value < prev_line:
                color = 1.0
        else:
            if line_value < prev_line:
                color = 4.0
            elif line_value > prev_line:
                color = 3.0
        self.lines.color[0] = color
        self._prev_color = color
