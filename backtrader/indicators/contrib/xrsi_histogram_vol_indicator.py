#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

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
        self._last_source_length = None
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
        source_length = len(self.data)
        scaled_history = list(self._scaled_history)
        volume_history = list(self._volume_history)
        if source_length == self._last_source_length and scaled_history and volume_history:
            scaled_history[-1] = raw
            volume_history[-1] = vol
        else:
            scaled_history.append(raw)
            volume_history.append(vol)
            if len(scaled_history) > self.p.ma_length:
                scaled_history.pop(0)
            if len(volume_history) > self.p.ma_length:
                volume_history.pop(0)
        scaled = sum(scaled_history) / float(len(scaled_history))
        avg_vol = (
            sum(volume_history) / float(len(volume_history))
            if volume_history
            else max(vol, 1.0)
        )
        max_level = self.p.high_level2 * avg_vol
        up_level = self.p.high_level1 * avg_vol
        dn_level = self.p.low_level1 * avg_vol
        min_level = self.p.low_level2 * avg_vol
        if not all(math.isfinite(v) for v in (scaled, max_level, up_level, dn_level, min_level)):
            clr = float("nan")
        elif scaled > max_level:
            clr = 0.0
        elif scaled > up_level:
            clr = 1.0
        elif scaled < min_level:
            clr = 4.0
        elif scaled < dn_level:
            clr = 3.0
        else:
            clr = 2.0
        outputs = (
            (self.lines.value, scaled),
            (self.lines.max_level, max_level),
            (self.lines.up_level, up_level),
            (self.lines.dn_level, dn_level),
            (self.lines.min_level, min_level),
            (self.lines.color_state, clr),
        )
        previous = [(line, line[0]) for line, _ in outputs]
        try:
            for line, value in outputs:
                line[0] = value
        except Exception:
            for line, value in previous:
                try:
                    line[0] = value
                except Exception:
                    pass
            raise
        self._scaled_history = scaled_history
        self._volume_history = volume_history
        self._last_source_length = source_length
