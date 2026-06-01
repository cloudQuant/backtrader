#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
    SimpleMovingAverage,
)

__all__ = [
    "AccumulationDistributionLine",
    "ChaikinOscillator",
    "LineCCI",
    "CCIDualOnMA",
]


class AccumulationDistributionLine(Indicator):
    """Accumulate the ADL indicator from price and volume progression."""

    lines = ("adl",)

    def next(self):
        """Compute one bar's accumulation/distribution line value."""
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        close = float(self.data.close[0])
        volume = float(self.data.volume[0])
        if high == low:
            money_flow_multiplier = 0.0
        else:
            money_flow_multiplier = ((close - low) - (high - close)) / (high - low)
        previous = float(self.lines.adl[-1]) if len(self) > 1 else 0.0
        self.lines.adl[0] = previous + money_flow_multiplier * volume


class ChaikinOscillator(Indicator):
    """Chaikin oscillator as EMA(short) minus EMA(long) of ADL."""

    lines = ("cho",)
    params = (
        ("fast_period", 3),
        ("slow_period", 10),
    )

    def __init__(self):
        """Initialize fast/slow ADL EMAs."""
        self.adl = AccumulationDistributionLine(self.data)
        fast = ExponentialMovingAverage(self.adl, period=self.p.fast_period)
        slow = ExponentialMovingAverage(self.adl, period=self.p.slow_period)
        self.lines.cho = fast - slow


class LineCCI(Indicator):
    """Custom CCI computation on the selected input data."""

    lines = ("cci",)
    params = (("period", 14),)

    def next(self):
        """Calculate a bar's CCI value with zero-handling for degenerate windows."""
        if len(self.data) < self.p.period:
            self.lines.cci[0] = 0.0
            return
        values = [float(self.data[-i]) for i in range(self.p.period)]
        mean_value = sum(values) / self.p.period
        mean_dev = sum(abs(v - mean_value) for v in values) / self.p.period
        if mean_dev == 0:
            self.lines.cci[0] = 0.0
            return
        self.lines.cci[0] = (float(self.data[0]) - mean_value) / (0.015 * mean_dev)


class CCIDualOnMA(Indicator):
    """Provide fast/slow CCI values computed on a smoothing moving average."""

    lines = ("fast", "slow")
    params = (
        ("ma_period", 12),
        ("fast_period", 14),
        ("slow_period", 50),
    )

    def __init__(self):
        """Initialize smoothed MA and dual CCI lines."""
        self.ma = SimpleMovingAverage(self.data.close, period=self.p.ma_period)
        self.lines.fast = LineCCI(self.ma, period=self.p.fast_period)
        self.lines.slow = LineCCI(self.ma, period=self.p.slow_period)
