#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math
from collections import deque

from .. import (
    DeMarker,
    Indicator,
)

__all__ = [
    "ColorSchaffDeMarkerTrendCycle",
]


class ColorSchaffDeMarkerTrendCycle(Indicator):
    """Schaff Trend Cycle of DeMarker oscillators with a discrete color line."""

    lines = ("stc", "color")
    params = (
        ("fast_demarker", 23),
        ("slow_demarker", 50),
        ("cycle", 10),
        ("high_level", 60),
        ("low_level", -60),
    )

    def __init__(self):
        """Build the fast/slow DeMarkers and initialize the STC smoothing state."""
        self.addminperiod(
            3 * max(int(self.p.fast_demarker), int(self.p.slow_demarker)) + int(self.p.cycle) + 5
        )
        self.fast_demarker = DeMarker(self.data, period=int(self.p.fast_demarker))
        self.slow_demarker = DeMarker(self.data, period=int(self.p.slow_demarker))
        self.factor = 2.0 / (1.0 + float(self.p.cycle))
        self.macd_window = deque(maxlen=int(self.p.cycle))
        self.st_window = deque(maxlen=int(self.p.cycle))
        self.prev_st = None
        self.prev_stc = None

    def _normalize(self, value, window, scale):
        if not window:
            return 0.0
        llv = min(window)
        hhv = max(window)
        if hhv - llv == 0:
            return None
        return ((value - llv) / (hhv - llv)) * scale

    def next(self):
        """Compute the STC value and discrete color code for the current bar."""
        fast = float(self.fast_demarker[0]) if math.isfinite(float(self.fast_demarker[0])) else 0.0
        slow = float(self.slow_demarker[0]) if math.isfinite(float(self.slow_demarker[0])) else 0.0
        macd = fast - slow
        self.macd_window.append(macd)
        st_raw = self._normalize(macd, self.macd_window, 100.0)
        if st_raw is None:
            st_value = self.prev_st if self.prev_st is not None else 0.0
        else:
            st_value = st_raw
        if self.prev_st is not None:
            st_value = self.factor * (st_value - self.prev_st) + self.prev_st
        self.prev_st = st_value
        self.st_window.append(st_value)
        stc_raw = self._normalize(st_value, self.st_window, 200.0)
        if stc_raw is None:
            stc_value = self.prev_stc if self.prev_stc is not None else 0.0
        else:
            stc_value = stc_raw - 100.0
        if self.prev_stc is not None:
            stc_value = self.factor * (stc_value - self.prev_stc) + self.prev_stc
        prev = self.prev_stc if self.prev_stc is not None else stc_value
        self.prev_stc = stc_value
        d_sts = stc_value - prev
        clr = 2
        if stc_value > 0:
            if stc_value > float(self.p.high_level):
                clr = 7 if d_sts >= 0 else 6
            else:
                clr = 5 if d_sts >= 0 else 4
        elif stc_value < 0:
            if stc_value < float(self.p.low_level):
                clr = 0 if d_sts < 0 else 1
            else:
                clr = 2 if d_sts < 0 else 3
        self.lines.stc[0] = stc_value
        self.lines.color[0] = clr
