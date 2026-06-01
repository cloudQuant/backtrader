#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "FatlFilter",
    "JFatlApprox",
    "JFatlCandleApprox",
]


class FatlFilter(Indicator):
    """Finite impulse response filter approximation used by JFatl indicators."""

    lines = ("fatl",)
    coeffs = (
        0.4360409450,
        0.3658689069,
        0.2460452079,
        0.1104506886,
        -0.0054034585,
        -0.0760367731,
        -0.0933058722,
        -0.0670110374,
        -0.0190795053,
        0.0259609206,
        0.0502044896,
        0.0477818607,
        0.0249252327,
        -0.0047706151,
        -0.0272432537,
        -0.0338917071,
        -0.0244141482,
        -0.0055774838,
        0.0128149838,
        0.0226522218,
        0.0208778257,
        0.0100299086,
        -0.0036771622,
        -0.0136744850,
        -0.0160483392,
        -0.0108597376,
        -0.0016060704,
        0.0069480557,
        0.0110573605,
        0.0095711419,
        0.0040444064,
        -0.0023824623,
        -0.0067093714,
        -0.0072003400,
        -0.0047717710,
        0.0005541115,
        0.0007860160,
        0.0130129076,
        0.0040364019,
    )

    def __init__(self):
        """Initialize the indicator with its required minimum period."""
        self.addminperiod(len(self.coeffs))

    def next(self):
        """Compute the FIR-style filtered value for the active bar."""
        total = 0.0
        for idx, coef in enumerate(self.coeffs):
            total += coef * float(self.data[-idx])
        self.lines.fatl[0] = total


class JFatlApprox(Indicator):
    """Double-smoothed approximation indicator built from JFatl coefficients."""

    lines = ("jfatl",)
    params = (
        ("length", 5),
        ("phase", 100),
    )

    def __init__(self):
        """Initialize smoothing state, limits, and minimum period."""
        self._length = max(2, int(self.p.length))
        self._phase = max(-100, min(100, int(self.p.phase)))
        self._coeffs = FatlFilter.coeffs
        base_alpha = 2.0 / (self._length + 1.0)
        self._alpha = max(0.01, min(0.95, base_alpha * (1.0 + self._phase / 200.0)))
        self._phase_gain = self._phase / 200.0
        self._ema1 = None
        self._ema2 = None
        self.addminperiod(len(self._coeffs))

    def next(self):
        """Update smoothed output from incoming raw weighted observations."""
        raw = 0.0
        for idx, coef in enumerate(self._coeffs):
            raw += coef * float(self.data[-idx])
        if self._ema1 is None:
            self._ema1 = raw
            self._ema2 = raw
        else:
            self._ema1 = self._ema1 + self._alpha * (raw - self._ema1)
            self._ema2 = self._ema2 + self._alpha * (self._ema1 - self._ema2)
        self.lines.jfatl[0] = self._ema1 + self._phase_gain * (self._ema1 - self._ema2)


class JFatlCandleApprox(Indicator):
    """Reconstruct candle-like open/high/low/close and color state from JFatl."""

    lines = ("open_value", "high_value", "low_value", "close_value", "color_state")
    params = (
        ("length", 5),
        ("phase", 100),
    )

    def __init__(self):
        """Initialize per-field smoothing states and min-period requirements."""
        self._coeffs = FatlFilter.coeffs
        self._length = max(2, int(self.p.length))
        self._phase = max(-100, min(100, int(self.p.phase)))
        base_alpha = 2.0 / (self._length + 1.0)
        self._alpha = max(0.01, min(0.95, base_alpha * (1.0 + self._phase / 200.0)))
        self._phase_gain = self._phase / 200.0
        self._states = {
            "open": {"ema1": None, "ema2": None},
            "high": {"ema1": None, "ema2": None},
            "low": {"ema1": None, "ema2": None},
            "close": {"ema1": None, "ema2": None},
        }
        self.addminperiod(len(self._coeffs))

    @staticmethod
    def _finite(value):
        return value is not None and math.isfinite(value)

    def _raw_fatl(self, line):
        total = 0.0
        for idx, coef in enumerate(self._coeffs):
            total += coef * float(line[-idx])
        return total

    def _smooth(self, key, raw):
        state = self._states[key]
        if state["ema1"] is None:
            state["ema1"] = raw
            state["ema2"] = raw
        else:
            state["ema1"] = state["ema1"] + self._alpha * (raw - state["ema1"])
            state["ema2"] = state["ema2"] + self._alpha * (state["ema1"] - state["ema2"])
        return state["ema1"] + self._phase_gain * (state["ema1"] - state["ema2"])

    def next(self):
        """Generate smoothed OHLC and direction color values for the current bar."""
        open_value = self._smooth("open", self._raw_fatl(self.data.open))
        high_value = self._smooth("high", self._raw_fatl(self.data.high))
        low_value = self._smooth("low", self._raw_fatl(self.data.low))
        close_value = self._smooth("close", self._raw_fatl(self.data.close))
        if not all(self._finite(v) for v in (open_value, high_value, low_value, close_value)):
            self.lines.open_value[0] = float("nan")
            self.lines.high_value[0] = float("nan")
            self.lines.low_value[0] = float("nan")
            self.lines.close_value[0] = float("nan")
            self.lines.color_state[0] = float("nan")
            return
        max_value = max(open_value, close_value)
        min_value = min(open_value, close_value)
        high_value = max(max_value, high_value)
        low_value = min(min_value, low_value)
        color_state = 2.0 if open_value < close_value else 0.0 if open_value > close_value else 1.0
        self.lines.open_value[0] = open_value
        self.lines.high_value[0] = high_value
        self.lines.low_value[0] = low_value
        self.lines.close_value[0] = close_value
        self.lines.color_state[0] = color_state
