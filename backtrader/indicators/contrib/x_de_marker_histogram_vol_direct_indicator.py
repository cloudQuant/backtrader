#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math
from collections import deque

from .. import Indicator

__all__ = [
    "XDeMarkerHistogramVolDirectIndicator",
]


class XDeMarkerHistogramVolDirectIndicator(Indicator):
    """Indicator that calculates DeMarker histogram zone and direct trend color."""

    lines = ("value", "color_zone", "color_direct", "upper2", "upper1", "lower1", "lower2")
    params = (
        ("de_marker_period", 14),
        ("volume_type", "tick"),
        ("high_level2", 20),
        ("high_level1", 15),
        ("low_level1", -15),
        ("low_level2", -20),
        ("ma_method", "MODE_SMA_"),
        ("ma_length", 12),
        ("ma_phase", 15),
    )

    def __init__(self):
        """Initialize de_marker state deques and warm-up period."""
        self._demax = deque(maxlen=max(1, int(self.p.de_marker_period)))
        self._demin = deque(maxlen=max(1, int(self.p.de_marker_period)))
        self._raw = deque(maxlen=max(1, int(self.p.ma_length)))
        self._vol = deque(maxlen=max(1, int(self.p.ma_length)))
        self.addminperiod(max(int(self.p.de_marker_period), int(self.p.ma_length)) + 2)

    @staticmethod
    def _nan():
        return float("nan")

    @staticmethod
    def _finite(value):
        return value is not None and math.isfinite(value)

    def _bar_volume(self):
        volume_type = str(self.p.volume_type).lower()
        if volume_type in {"real", "volume_real", "volume"}:
            raw = float(self.data.openinterest[0])
            if math.isfinite(raw) and raw > 0:
                return raw
        raw = float(self.data.volume[0])
        return raw if math.isfinite(raw) else 0.0

    def next(self):
        """Compute de_marker-derived raw value, smoothing, and colors."""
        if len(self.data) < 2:
            for line in self.lines:
                line[0] = self._nan()
            return

        high_now = float(self.data.high[0])
        high_prev = float(self.data.high[-1])
        low_now = float(self.data.low[0])
        low_prev = float(self.data.low[-1])
        vol_now = self._bar_volume()

        self._demax.append(max(high_now - high_prev, 0.0))
        self._demin.append(max(low_prev - low_now, 0.0))

        value = self._nan()
        color_zone = self._nan()
        color_direct = (
            self.lines.color_direct[-1]
            if len(self) > 1 and self._finite(self.lines.color_direct[-1])
            else self._nan()
        )
        upper2 = self._nan()
        upper1 = self._nan()
        lower1 = self._nan()
        lower2 = self._nan()

        if len(self._demax) >= int(self.p.de_marker_period) and len(self._demin) >= int(
            self.p.de_marker_period
        ):
            sum_max = sum(self._demax)
            sum_min = sum(self._demin)
            denom = sum_max + sum_min
            demarker = (sum_max / denom) if denom > 0 else 0.5
            raw = ((demarker * 100.0) - 50.0) * vol_now
            self._raw.append(raw)
            self._vol.append(vol_now)

            if len(self._raw) >= int(self.p.ma_length) and len(self._vol) >= int(self.p.ma_length):
                if str(self.p.ma_method).upper() != "MODE_SMA_":
                    raise ValueError(
                        "Current backtrader migration only supports MODE_SMA_ for XDeMarker_Histogram_Vol_Direct"
                    )
                value = sum(self._raw) / len(self._raw)
                avg_vol = sum(self._vol) / len(self._vol)
                upper2 = self.p.high_level2 * avg_vol
                upper1 = self.p.high_level1 * avg_vol
                lower1 = self.p.low_level1 * avg_vol
                lower2 = self.p.low_level2 * avg_vol
                if value > upper2:
                    color_zone = 0.0
                elif value > upper1:
                    color_zone = 1.0
                elif value < lower2:
                    color_zone = 4.0
                elif value < lower1:
                    color_zone = 3.0
                else:
                    color_zone = 2.0

                prev_value = (
                    self.lines.value[-1]
                    if len(self) > 1 and self._finite(self.lines.value[-1])
                    else self._nan()
                )
                prev_direct = (
                    self.lines.color_direct[-1]
                    if len(self) > 1 and self._finite(self.lines.color_direct[-1])
                    else 1.0
                )
                if not self._finite(prev_value):
                    color_direct = prev_direct
                elif value > prev_value:
                    color_direct = 0.0
                elif value < prev_value:
                    color_direct = 1.0
                else:
                    color_direct = prev_direct

        self.lines.value[0] = value
        self.lines.color_zone[0] = color_zone
        self.lines.color_direct[0] = color_direct
        self.lines.upper2[0] = upper2
        self.lines.upper1[0] = upper1
        self.lines.lower1[0] = lower1
        self.lines.lower2[0] = lower2
