#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math
from collections import deque

from .. import Indicator

__all__ = [
    "BrainTrend2Indicator",
    "AbsolutelyNoLagLwmaIndicator",
]


class BrainTrend2Indicator(Indicator):
    """ATR-derived trend-state indicator producing a four-state color signal."""

    lines = ("color_state",)
    params = (
        ("atr_period", 7),
        ("point_size", 0.01),
    )

    def __init__(self):
        """Initialize transition state and adaptive ATR window."""
        self._period = max(1, int(self.p.atr_period))
        self._cecf = 0.7
        self._trs = deque(maxlen=self._period)
        self._river = None
        self._emaxtra = None
        self.addminperiod(self._period + 2)

    @staticmethod
    def _finite(value):
        return value is not None and math.isfinite(value)

    def next(self):
        """Update trend river state and emit a color code."""
        prev_close = float(self.data.close[-1]) if len(self.data) > 1 else float(self.data.close[0])
        spread = (
            float(getattr(self.data, "spread")[0]) * self.p.point_size
            if hasattr(self.data, "spread")
            else 0.0
        )
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        open_ = float(self.data.open[0])
        close = float(self.data.close[0])
        tr = spread + high - low
        tr = max(tr, abs(spread + high - prev_close), abs(low - prev_close))
        self._trs.append(tr)
        if len(self._trs) < self._period:
            self.lines.color_state[0] = float("nan")
            return
        weights = list(range(self._period, 0, -1))
        atr = (
            2.0
            * sum(w * v for w, v in zip(weights, reversed(self._trs)))
            / (self._period * (self._period + 1.0))
        )
        widcha = self._cecf * atr
        if self._river is None:
            prev2_close = float(self.data.close[-2]) if len(self.data) > 2 else prev_close
            self._river = prev2_close > prev_close
            self._emaxtra = prev_close
        if self._river and low < self._emaxtra - widcha:
            self._river = False
            self._emaxtra = spread + high
        if (not self._river) and spread + high > self._emaxtra + widcha:
            self._river = True
            self._emaxtra = low
        if self._river and low > self._emaxtra:
            self._emaxtra = low
        if (not self._river) and spread + high < self._emaxtra:
            self._emaxtra = spread + high
        if self._river:
            color = 0.0 if open_ <= close else 1.0
        else:
            color = 4.0 if open_ >= close else 3.0
        self.lines.color_state[0] = color


class AbsolutelyNoLagLwmaIndicator(Indicator):
    """No-lag LWMA indicator with color state transitions."""

    lines = ("line_value", "color_state")
    params = (("length", 7),)

    def __init__(self):
        """Prepare rolling windows for dual-weighted moving average updates."""
        self._length = max(1, int(self.p.length))
        self._price_window = deque(maxlen=self._length)
        self._lwma_window = deque(maxlen=self._length)
        self.addminperiod(self._length * 2)

    def _weighted_ma(self, values):
        weights = list(range(len(values), 0, -1))
        total = sum(weights)
        return sum(w * v for w, v in zip(weights, reversed(values))) / total

    def next(self):
        """Compute smoothed LWMA and directional color for each bar."""
        price = float(self.data.close[0])
        self._price_window.append(price)
        if len(self._price_window) < self._length:
            self.lines.line_value[0] = float("nan")
            self.lines.color_state[0] = float("nan")
            return
        lwma1 = self._weighted_ma(self._price_window)
        self._lwma_window.append(lwma1)
        if len(self._lwma_window) < self._length:
            self.lines.line_value[0] = float("nan")
            self.lines.color_state[0] = float("nan")
            return
        lwma2 = self._weighted_ma(self._lwma_window)
        color = 1.0
        prev = self.lines.line_value[-1] if len(self) > 0 else float("nan")
        if prev == prev:
            if prev < lwma2:
                color = 2.0
            elif prev > lwma2:
                color = 0.0
        self.lines.line_value[0] = lwma2
        self.lines.color_state[0] = color
