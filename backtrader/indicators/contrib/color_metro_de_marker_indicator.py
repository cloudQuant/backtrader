#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    DeMarkerIndicator,
    Indicator,
)

__all__ = [
    "ColorMetroDeMarkerIndicator",
]


class ColorMetroDeMarkerIndicator(Indicator):
    """Colour Metro DeMarker indicator: derives fast/slow adaptive trend lines from the DeM oscillator."""

    lines = ("fast_line", "slow_line", "demarker")
    params = (
        ("period_demarker", 7),
        ("step_size_fast", 5),
        ("step_size_slow", 15),
    )

    def __init__(self):
        """Initialize DeMarker instance, set minperiod, reset channel tracking vars."""
        self.dem = DeMarkerIndicator(self.data, period=int(self.p.period_demarker))
        self.addminperiod(int(self.p.period_demarker) + 3)
        self._fmin1 = 999999.0
        self._fmax1 = -999999.0
        self._smin1 = 999999.0
        self._smax1 = -999999.0
        self._ftrend = 0
        self._strend = 0

    def next(self):
        """Compute fast_line, slow_line and demarker from DeM value using step-based channel logic."""
        dem0 = float(self.dem[0]) * 100.0
        fmax0 = dem0 + 2.0 * float(self.p.step_size_fast)
        fmin0 = dem0 - 2.0 * float(self.p.step_size_fast)
        if dem0 > self._fmax1:
            self._ftrend = 1
        if dem0 < self._fmin1:
            self._ftrend = -1
        if self._ftrend > 0 and fmin0 < self._fmin1:
            fmin0 = self._fmin1
        if self._ftrend < 0 and fmax0 > self._fmax1:
            fmax0 = self._fmax1
        smax0 = dem0 + 2.0 * float(self.p.step_size_slow)
        smin0 = dem0 - 2.0 * float(self.p.step_size_slow)
        if dem0 > self._smax1:
            self._strend = 1
        if dem0 < self._smin1:
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
        self.lines.demarker[0] = dem0
        self._fmin1 = fmin0
        self._fmax1 = fmax0
        self._smin1 = smin0
        self._smax1 = smax0
