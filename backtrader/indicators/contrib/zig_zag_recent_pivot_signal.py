#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "ZigZagRecentPivotSignal",
]


class ZigZagRecentPivotSignal(Indicator):
    """Custom indicator tracking local pivot age and pivot price breakout channels.

    Lines:
        signal (Line): Pivot direction signal line (1 for high, -1 for low).
        pivot_age (Line): Age of the confirmed pivot in bars.
        pivot_price (Line): Confirmed pivot price level.
    """

    lines = ("signal", "pivot_age", "pivot_price")
    params = (
        ("depth", 17),
        ("deviation", 7),
        ("backstep", 5),
        ("point", 0.01),
    )

    def __init__(self):
        """Initialize indicator buffers and establish minimum warmup period."""
        self.addminperiod(self.p.depth + self.p.backstep + 2)
        self._last_pivot_type = 0
        self._last_pivot_price = None
        self._latest_signal = 0
        self._latest_age = 999999
        self._latest_pivot_price = 0.0

    def next(self):
        """Calculate local ZigZag pivot high and low levels on each new bar."""
        self.lines.signal[0] = 0
        self.lines.pivot_age[0] = self._latest_age if self._latest_age < 999999 else 999999
        self.lines.pivot_price[0] = self._latest_pivot_price

        if len(self.data) <= self.p.depth + self.p.backstep:
            return

        shift = self.p.backstep
        candidate_high = float(self.data.high[-shift])
        candidate_low = float(self.data.low[-shift])
        high_window = [float(self.data.high[-shift - i]) for i in range(self.p.depth)]
        low_window = [float(self.data.low[-shift - i]) for i in range(self.p.depth)]
        deviation_abs = self.p.deviation * self.p.point

        pivot_type = 0
        pivot_price = None
        if candidate_high >= max(high_window):
            pivot_type = 1
            pivot_price = candidate_high
        elif candidate_low <= min(low_window):
            pivot_type = -1
            pivot_price = candidate_low

        if pivot_type != 0 and pivot_price is not None:
            is_new_pivot = False
            if (
                self._last_pivot_price is None
                or pivot_type != self._last_pivot_type
                and abs(pivot_price - self._last_pivot_price) >= deviation_abs
            ):
                is_new_pivot = True
            elif pivot_type == self._last_pivot_type:
                if pivot_type == 1 and pivot_price > self._last_pivot_price:
                    is_new_pivot = True
                if pivot_type == -1 and pivot_price < self._last_pivot_price:
                    is_new_pivot = True
            if is_new_pivot:
                self._last_pivot_type = pivot_type
                self._last_pivot_price = pivot_price
                self._latest_signal = 1 if pivot_type == 1 else -1
                self._latest_age = 0
                self._latest_pivot_price = pivot_price

        if self._latest_age < 999999:
            self.lines.signal[0] = self._latest_signal
            self.lines.pivot_age[0] = self._latest_age
            self.lines.pivot_price[0] = self._latest_pivot_price
            self._latest_age += 1
