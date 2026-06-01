#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "XRSIHistogramVolDirectIndicator",
]


class XRSIHistogramVolDirectIndicator(Indicator):
    """Simple direct XRSI histogram indicator that emits color state transitions."""

    lines = ("color_state", "value")
    params = (
        ("rsi_period", 14),
        ("ma_length", 12),
    )

    def __init__(self):
        """Initialize rolling history for smoothed direct RSI histogram."""
        self._scaled_history = []
        self.addminperiod(max(self.p.rsi_period, self.p.ma_length) + 3)

    def next(self):
        """Update scaled RSI values and binary color direction."""
        gains = []
        losses = []
        for idx in range(self.p.rsi_period):
            delta = float(self.data.close[-idx]) - float(self.data.close[-idx - 1])
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))
        avg_gain = sum(gains) / float(len(gains))
        avg_loss = sum(losses) / float(len(losses))
        if avg_loss <= 1e-12:
            rsi_value = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi_value = 100.0 - (100.0 / (1.0 + rs))
        raw = (rsi_value - 50.0) * float(self.data.volume[0])
        self._scaled_history.append(raw)
        if len(self._scaled_history) > self.p.ma_length:
            self._scaled_history.pop(0)
        current = sum(self._scaled_history) / float(len(self._scaled_history))
        previous = self.lines.value[-1] if len(self) else 0.0
        color = 0.0 if current >= previous else 1.0
        self.lines.value[0] = current
        self.lines.color_state[0] = color
