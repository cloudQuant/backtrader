#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from ...linebuffer import _reject_factor_infinity
from .. import Indicator

__all__ = [
    "ThreeCandlesIndicator",
]


class ThreeCandlesIndicator(Indicator):
    """Produce reversal labels, or NaN when required inputs are unavailable."""

    lines = ("signal",)
    params = (
        ("max_bar1", 300),
        ("volume_type", "tick"),
    )

    def __init__(self):
        """Require enough history before the indicator can emit stable signals."""
        self.addminperiod(5)

    def next(self):
        """Evaluate bullish/bearish setups and emit normalized signal codes."""
        current_open = float(self.data.open[0])
        current_close = float(self.data.close[0])
        opens = [float(self.data.open[-i]) for i in (3, 2, 1)]
        closes = [float(self.data.close[-i]) for i in (3, 2, 1)]
        first_high = float(self.data.high[-3])
        first_low = float(self.data.low[-3])
        required = (current_open, current_close, first_high, first_low, *opens, *closes)
        for value in required:
            if math.isinf(value):
                _reject_factor_infinity(self.lines.signal, value)
        if not all(math.isfinite(value) for value in required):
            self.lines.signal[0] = float("nan")
            return

        self.lines.signal[0] = 2.0

        chk_vol = True
        range_points = first_high - first_low
        if math.isinf(range_points):
            _reject_factor_infinity(self.lines.signal, range_points)
        point = float(getattr(self.data, "_point_value", 0.01) or 0.01)
        if point > 0:
            scaled_range = range_points / point
            if math.isinf(scaled_range):
                _reject_factor_infinity(self.lines.signal, scaled_range)
            if scaled_range > float(self.p.max_bar1):
                chk_vol = False

        bullish_setup = (
            opens[0] < closes[0]
            and opens[1] < closes[1]
            and closes[1] < first_high
            and opens[2] > closes[2]
            and closes[2] < opens[1]
        )
        bearish_setup = (
            opens[0] > closes[0]
            and opens[1] > closes[1]
            and closes[1] > first_low
            and opens[2] < closes[2]
            and closes[2] > opens[1]
        )

        volume_ok = True
        if (bullish_setup or bearish_setup) and chk_vol and self.p.volume_type != "none":
            v3, v2, v1 = (float(self.data.volume[-i]) for i in (3, 2, 1))
            for value in (v3, v2, v1):
                if math.isinf(value):
                    _reject_factor_infinity(self.lines.signal, value)
            if not all(math.isfinite(value) for value in (v3, v2, v1)):
                self.lines.signal[0] = float("nan")
                return
            volume_ok = v3 < v2 or v1 > v2 or v1 > v3

        if bullish_setup and volume_ok:
            self.lines.signal[0] = (
                0.0 if current_close < current_open else 1.0
            )
        if bearish_setup and volume_ok:
            self.lines.signal[0] = (
                3.0 if current_close < current_open else 4.0
            )
