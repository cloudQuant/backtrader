#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "LsmaAngleIndicator",
]


class LsmaAngleIndicator(Indicator):
    """Compute LSMA slope angle and map it to a color-state indicator.

    The indicator evaluates two least-squares MAs at different shifts and uses
    the angle and trend persistence to classify bullish/bearish momentum states.

    Args:
        lsma_period: Look-back window used for each LSMA estimate.
        angle_threshold: Threshold used to classify the angle magnitude.
        start_shift: Shift index for the start LSMA sample.
        end_shift: Shift index for the end LSMA sample.
    """

    lines = ("angle", "color_index")
    params = (
        ("lsma_period", 25),
        ("angle_threshold", 15),
        ("start_shift", 4),
        ("end_shift", 0),
    )

    def __init__(self):
        """Set minimum-history requirement and initialize derived scale factor."""
        needed = (
            int(max(self.p.lsma_period + self.p.start_shift, self.p.lsma_period + self.p.end_shift))
            + 2
        )
        self.addminperiod(needed)
        self._m_factor = None

    def _lsma(self, shift):
        period = int(self.p.lsma_period)
        values = [float(self.data.close[-(shift + i)]) for i in range(period)]
        x = list(range(period))
        x_mean = sum(x) / period
        y_mean = sum(values) / period
        numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, values))
        denominator = sum((xi - x_mean) ** 2 for xi in x)
        slope = numerator / denominator if denominator else 0.0
        intercept = y_mean - slope * x_mean
        return intercept + slope * (period - 1)

    def _ensure_factor(self):
        if self._m_factor is not None:
            return
        point = (
            float(getattr(self.data, "_dataname", None).attrs["point"])
            if hasattr(getattr(self.data, "_dataname", None), "attrs")
            and "point" in self.data._dataname.attrs
            else None
        )
        if point is None or point <= 0:
            close0 = float(self.data.close[0]) if len(self.data) else 0.0
            point = 0.01 if abs(close0) >= 10 and abs(close0) < 1000 else 0.0001
        shift_diff = float(int(self.p.start_shift) - int(self.p.end_shift))
        self._m_factor = (
            1000.0
            if abs(float(self.data.close[0])) >= 10 and abs(float(self.data.close[0])) < 1000
            else 100000.0
        ) / shift_diff

    def next(self):
        """Calculate the current angle and update color index for the next bar."""
        if int(self.p.end_shift) >= int(self.p.start_shift):
            self.lines.angle[0] = 0.0
            self.lines.color_index[0] = 2
            return
        self._ensure_factor()
        end_ma = self._lsma(int(self.p.end_shift))
        start_ma = self._lsma(int(self.p.start_shift))
        angle = self._m_factor * (end_ma - start_ma) / 2.0
        self.lines.angle[0] = angle
        clr = 2
        threshold = float(self.p.angle_threshold)
        prev_angle = (
            float(self.lines.angle[-1])
            if len(self) > 0 and math.isfinite(float(self.lines.angle[-1]))
            else angle
        )
        if angle > threshold:
            if angle > prev_angle:
                clr = 4
            elif angle < prev_angle:
                clr = 3
        if angle < -threshold:
            if angle < prev_angle:
                clr = 0
            elif angle > prev_angle:
                clr = 1
        self.lines.color_index[0] = clr
