#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "XCCIHistogramVolDirectIndicator",
]


class XCCIHistogramVolDirectIndicator(Indicator):
    """Direct XCCI histogram indicator producing smoothed value and color state."""

    lines = ("color_state", "value")
    params = (
        ("cci_period", 14),
        ("ma_length", 12),
    )

    def __init__(self):
        """Initialize rolling scaled-history buffers and minimum periods."""
        self._scaled_history = []
        self.addminperiod(max(self.p.cci_period, self.p.ma_length) + 3)

    def next(self):
        """Compute CCI*volume histogram value and binary color transition."""
        typical_prices = []
        for idx in range(self.p.cci_period):
            typical_prices.append(
                (
                    float(self.data.high[-idx])
                    + float(self.data.low[-idx])
                    + float(self.data.close[-idx])
                )
                / 3.0
            )
        tp_now = typical_prices[0]
        tp_sma = sum(typical_prices) / float(len(typical_prices))
        mean_dev = sum(abs(tp - tp_sma) for tp in typical_prices) / float(len(typical_prices))
        if mean_dev <= 1e-12:
            cci_value = 0.0
        else:
            cci_value = (tp_now - tp_sma) / (0.015 * mean_dev)
        raw = cci_value * float(self.data.volume[0])
        self._scaled_history.append(raw)
        if len(self._scaled_history) > self.p.ma_length:
            self._scaled_history.pop(0)
        current = sum(self._scaled_history) / float(len(self._scaled_history))
        previous = self.lines.value[-1] if len(self) else 0.0
        color = 0.0 if current >= previous else 1.0
        self.lines.value[0] = current
        self.lines.color_state[0] = color
