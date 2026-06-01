#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
)

__all__ = [
    "RDTrendTriggerIndicator",
]


class RDTrendTriggerIndicator(Indicator):
    """Custom indicator that derives normalized range-trend trigger values."""

    lines = ("value",)
    params = (
        ("regress", 15),
        ("t3_length", 5),
        ("t3_phase", 70),
    )

    def __init__(self):
        """Initialize helper buffers and required warmup length."""
        self._ema = ExponentialMovingAverage(self.lines.value, period=max(1, int(self.p.t3_length)))
        self.addminperiod(int(self.p.regress) * 2 + int(self.p.t3_length) + 3)

    def next(self):
        """Compute trend trigger value from rolling high/low comparisons."""
        regress = int(self.p.regress)
        highs_recent = [float(self.data.high[-i]) for i in range(regress)]
        highs_older = [float(self.data.high[-regress - i]) for i in range(regress)]
        lows_recent = [float(self.data.low[-i]) for i in range(regress)]
        lows_older = [float(self.data.low[-regress - i]) for i in range(regress)]
        highest_high_recent = max(highs_recent)
        highest_high_older = max(highs_older)
        lowest_low_recent = min(lows_recent)
        lowest_low_older = min(lows_older)
        buy_power = highest_high_recent - lowest_low_older
        sell_power = highest_high_older - lowest_low_recent
        denom = buy_power + sell_power
        ttf = ((buy_power - sell_power) / (0.5 * denom) * 100.0) if denom else 0.0
        prev = float(self.lines.value[-1]) if len(self) > 0 else ttf
        period = max(1, int(self.p.t3_length))
        alpha = 2.0 / (period + 1.0)
        self.lines.value[0] = alpha * ttf + (1.0 - alpha) * prev
