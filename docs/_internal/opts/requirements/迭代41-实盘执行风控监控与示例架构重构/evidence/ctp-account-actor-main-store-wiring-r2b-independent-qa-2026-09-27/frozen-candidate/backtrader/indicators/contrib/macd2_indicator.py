#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    MACD,
    Indicator,
)

__all__ = [
    "Macd2Indicator",
]


class Macd2Indicator(Indicator):
    """MACD-derived indicator carrying cloud and histogram state for MACD-2."""

    lines = ("cloud_a", "cloud_b", "hist", "color")
    params = (
        ("fast_macd", 12),
        ("slow_macd", 26),
        ("signal_macd", 9),
    )

    def __init__(self):
        """Create MACD-based cloud and initialize indicator warmup."""
        self.macd = MACD(
            self.data,
            period_me1=int(self.p.fast_macd),
            period_me2=int(self.p.slow_macd),
            period_signal=int(self.p.signal_macd),
        )
        self.addminperiod(
            int(self.p.signal_macd) + max(int(self.p.fast_macd), int(self.p.slow_macd)) + 2
        )

    def next(self):
        """Populate cloud, histogram, and trend color lines each bar."""
        main = float(self.macd.macd[0])
        signal = float(self.macd.signal[0])
        hist = 3.0 * (main - signal)
        self.lines.cloud_a[0] = main
        self.lines.cloud_b[0] = signal
        self.lines.hist[0] = hist
        color = 2
        if len(self) > 1:
            prev_hist = float(self.lines.hist[-1])
            if hist > 0:
                if hist > prev_hist:
                    color = 4
                elif hist < prev_hist:
                    color = 3
            elif hist < 0:
                if hist < prev_hist:
                    color = 0
                elif hist > prev_hist:
                    color = 1
        self.lines.color[0] = color
