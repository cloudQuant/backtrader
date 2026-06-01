#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "XRSIHistogramVolIndicator",
]


class XRSIHistogramVolIndicator(Indicator):
    """Volume-scaled RSI histogram indicator producing directional color states."""

    lines = ("color_state", "value", "max_level", "up_level", "dn_level", "min_level")
    params = (
        ("rsi_period", 14),
        ("high_level2", 17),
        ("high_level1", 5),
        ("low_level1", -5),
        ("low_level2", -17),
        ("ma_length", 12),
    )

    def __init__(self):
        """Prepare rolling RSI and volume histories."""
        self._scaled_history = []
        self._volume_history = []
        self.addminperiod(max(self.p.rsi_period, self.p.ma_length) + 3)

    def next(self):
        """Calculate scaled histogram level and classify it into a color state."""
        vol = float(self.data.volume[0]) if len(self.data.volume) else 0.0
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
        raw = (rsi_value - 50.0) * vol
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
