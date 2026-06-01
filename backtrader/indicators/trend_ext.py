#!/usr/bin/env python
"""Trend indicator extensions migrated from functional tests."""

from . import Indicator
from .smma import SmoothedMovingAverage

__all__ = ["AlligatorIndicator", "VortexIndicator", "VortexSystemIndicator"]


class AlligatorIndicator(Indicator):
    """Bill Williams Alligator lines used by functional strategies.

    The historical functional-test variants accepted shift/ma_method
    parameters but did not apply the shift or switch the MA method. Those
    parameters are kept for API compatibility and the original SMMA behavior is
    preserved.
    """

    lines = ("jaw", "teeth", "lips")
    params = (
        ("jaw_period", 13),
        ("teeth_period", 8),
        ("lips_period", 5),
        ("jaw_shift", 8),
        ("teeth_shift", 5),
        ("lips_shift", 3),
        ("ma_method", "smma"),
        ("applied_price", "close"),
    )

    def __init__(self):
        if self.p.applied_price == "median":
            src = (self.data.high + self.data.low) / 2.0
        else:
            src = self.data.close

        self.lines.jaw = SmoothedMovingAverage(src, period=self.p.jaw_period)
        self.lines.teeth = SmoothedMovingAverage(src, period=self.p.teeth_period)
        self.lines.lips = SmoothedMovingAverage(src, period=self.p.lips_period)


class VortexIndicator(Indicator):
    """Vortex Indicator with both historical line naming conventions."""

    lines = ("vi_plus", "vi_minus", "plus_vi", "minus_vi")
    params = (("period", 14),)

    def next(self):
        p = int(self.p.period)
        if len(self.data) < p + 2:
            for line in self.lines:
                line[0] = 0.0
            return

        vm_plus_sum = 0.0
        vm_minus_sum = 0.0
        tr_sum = 0.0
        for i in range(p):
            idx = -i
            idx_prev = idx - 1
            h = float(self.data.high[idx])
            low_price = float(self.data.low[idx])
            h_prev = float(self.data.high[idx_prev])
            l_prev = float(self.data.low[idx_prev])
            c_prev = float(self.data.close[idx_prev])
            vm_plus_sum += abs(h - l_prev)
            vm_minus_sum += abs(low_price - h_prev)
            tr_sum += max(h - low_price, abs(h - c_prev), abs(low_price - c_prev))

        if tr_sum > 0:
            plus = vm_plus_sum / tr_sum
            minus = vm_minus_sum / tr_sum
        else:
            plus = 0.0
            minus = 0.0

        self.lines.vi_plus[0] = plus
        self.lines.plus_vi[0] = plus
        self.lines.vi_minus[0] = minus
        self.lines.minus_vi[0] = minus


class VortexSystemIndicator(VortexIndicator):
    """Vortex variant preserving the historical strategy-system warm-up."""

    def __init__(self):
        self.addminperiod(int(self.p.period) + 1)
