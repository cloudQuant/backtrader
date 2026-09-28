#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
    SimpleMovingAverage,
    Stochastic,
)

__all__ = [
    "ColorMetroStochasticIndicator",
]


class ColorMetroStochasticIndicator(Indicator):
    """Indicator producing adaptive fast/slow ColorMETRO stochastic levels."""

    lines = ("fast_line", "slow_line", "stochastic")
    params = (
        ("k_period", 5),
        ("d_period", 3),
        ("slowing", 3),
        ("ma_method", "simple"),
        ("step_size_fast", 5),
        ("step_size_slow", 15),
    )

    def __init__(self):
        """Initialize Stochastic source and internal trend tracking state."""
        self.stoch = Stochastic(
            self.data,
            period=int(self.p.k_period),
            period_dfast=int(self.p.slowing),
            period_dslow=int(self.p.d_period),
            movav=(
                SimpleMovingAverage
                if str(self.p.ma_method).lower() == "simple"
                else ExponentialMovingAverage
            ),
        )
        self.addminperiod(int(self.p.k_period) + int(self.p.d_period) + int(self.p.slowing) + 3)
        self._fmin1 = 999999.0
        self._fmax1 = -999999.0
        self._smin1 = 999999.0
        self._smax1 = -999999.0
        self._ftrend = 0
        self._strend = 0

    def next(self):
        """Update fast/slow adaptive lines and push current values."""
        stoch0 = float(self.stoch.percD[0])
        fmax0 = stoch0 + 2.0 * float(self.p.step_size_fast)
        fmin0 = stoch0 - 2.0 * float(self.p.step_size_fast)
        if stoch0 > self._fmax1:
            self._ftrend = 1
        if stoch0 < self._fmin1:
            self._ftrend = -1
        if self._ftrend > 0 and fmin0 < self._fmin1:
            fmin0 = self._fmin1
        if self._ftrend < 0 and fmax0 > self._fmax1:
            fmax0 = self._fmax1
        smax0 = stoch0 + 2.0 * float(self.p.step_size_slow)
        smin0 = stoch0 - 2.0 * float(self.p.step_size_slow)
        if stoch0 > self._smax1:
            self._strend = 1
        if stoch0 < self._smin1:
            self._strend = -1
        if self._strend > 0 and smin0 < self._smin1:
            smin0 = self._smin1
        if self._strend < 0 and smax0 > self._smax1:
            smax0 = self._smax1
        fast_line = (
            fmin0 + float(self.p.step_size_fast)
            if self._ftrend > 0
            else fmax0 - float(self.p.step_size_fast)
        )
        slow_line = (
            smin0 + float(self.p.step_size_slow)
            if self._strend > 0
            else smax0 - float(self.p.step_size_slow)
        )
        self.lines.fast_line[0] = fast_line
        self.lines.slow_line[0] = slow_line
        self.lines.stochastic[0] = stoch0
        self._fmin1 = fmin0
        self._fmax1 = fmax0
        self._smin1 = smin0
        self._smax1 = smax0
