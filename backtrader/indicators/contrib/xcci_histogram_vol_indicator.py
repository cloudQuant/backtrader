#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "XCCIHistogramVolIndicator",
]


class XCCIHistogramVolIndicator(Indicator):
    """Compute volume-scaled XCCI histogram levels and color state."""

    lines = ("color_state", "value", "max_level", "up_level", "dn_level", "min_level")
    params = (
        ("cci_period", 14),
        ("high_level2", 100),
        ("high_level1", 80),
        ("low_level1", -80),
        ("low_level2", -100),
        ("ma_length", 12),
    )

    def __init__(self):
        """Initialize rolling CCI and volume histories."""
        self._scaled_history = []
        self._volume_history = []
        self.addminperiod(max(self.p.cci_period, self.p.ma_length) + 3)

    def next(self):
        """Update scaled CCI, levels, and derived color state."""
        vol = float(self.data.volume[0]) if len(self.data.volume) else 0.0
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
        raw = cci_value * vol
        self._scaled_history.append(raw)
        self._volume_history.append(vol)
        if len(self._scaled_history) > self.p.ma_length:
            self._scaled_history.pop(0)
        if len(self._volume_history) > self.p.ma_length:
            self._volume_history.pop(0)
        scaled = sum(self._scaled_history) / float(len(self._scaled_history))
        avg_vol = (
            sum(self._volume_history) / float(len(self._volume_history))
            if self._volume_history
            else max(vol, 1.0)
        )
        max_level = self.p.high_level2 * avg_vol
        up_level = self.p.high_level1 * avg_vol
        dn_level = self.p.low_level1 * avg_vol
        min_level = self.p.low_level2 * avg_vol
        clr = 2.0
        if scaled > max_level:
            clr = 0.0
        elif scaled > up_level:
            clr = 1.0
        elif scaled < min_level:
            clr = 4.0
        elif scaled < dn_level:
            clr = 3.0
        self.lines.value[0] = scaled
        self.lines.max_level[0] = max_level
        self.lines.up_level[0] = up_level
        self.lines.dn_level[0] = dn_level
        self.lines.min_level[0] = min_level
        self.lines.color_state[0] = clr
