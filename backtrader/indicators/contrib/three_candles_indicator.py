#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "ThreeCandlesIndicator",
]


class ThreeCandlesIndicator(Indicator):
    """Indicator producing three-candle reversal signal labels."""

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
        self.lines.signal[0] = 2.0

        chk_vol = True
        range_points = float(self.data.high[-3] - self.data.low[-3])
        point = float(getattr(self.data, "_point_value", 0.01) or 0.01)
        if point > 0 and range_points / point > float(self.p.max_bar1):
            chk_vol = False

        bullish_setup = (
            float(self.data.open[-3]) < float(self.data.close[-3])
            and float(self.data.open[-2]) < float(self.data.close[-2])
            and float(self.data.close[-2]) < float(self.data.high[-3])
            and float(self.data.open[-1]) > float(self.data.close[-1])
            and float(self.data.close[-1]) < float(self.data.open[-2])
        )
        bearish_setup = (
            float(self.data.open[-3]) > float(self.data.close[-3])
            and float(self.data.open[-2]) > float(self.data.close[-2])
            and float(self.data.close[-2]) > float(self.data.low[-3])
            and float(self.data.open[-1]) < float(self.data.close[-1])
            and float(self.data.close[-1]) > float(self.data.open[-2])
        )

        vol_series = self.data.volume

        def volume_filter_ok():
            if not chk_vol or self.p.volume_type == "none":
                return True
            v3 = float(vol_series[-3])
            v2 = float(vol_series[-2])
            v1 = float(vol_series[-1])
            return v3 < v2 or v1 > v2 or v1 > v3

        if bullish_setup and volume_filter_ok():
            self.lines.signal[0] = (
                0.0 if float(self.data.close[0]) < float(self.data.open[0]) else 1.0
            )
        if bearish_setup and volume_filter_ok():
            self.lines.signal[0] = (
                3.0 if float(self.data.close[0]) < float(self.data.open[0]) else 4.0
            )
