#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    ExponentialMovingAverage,
    Indicator,
)

__all__ = [
    "F2aAOIndicator",
]


class F2aAOIndicator(Indicator):
    """F2a_AO arrow indicator from a fast/slow/filter EMA system.

    Builds fast, slow and filter EMAs of a weighted price and emits a ``buy``
    arrow below the bar when the fast-minus-slow spread turns up with filter
    confirmation, or a ``sell`` arrow above the bar on the bearish turn, using an
    internal latch so arrows alternate direction.
    """

    lines = ("sell", "buy")
    params = (
        ("ma_filtr", 3),
        ("ma_fast", 13),
        ("ma_slow", 144),
    )

    def __init__(self):
        """Build the fast/slow/filter EMAs and set the minimum period."""
        series = (
            self.data.close * 5.0 + self.data.open * 2.0 + self.data.high + self.data.low
        ) / 9.0
        self._fast = ExponentialMovingAverage(series, period=max(1, int(self.p.ma_fast)))
        self._slow = ExponentialMovingAverage(series, period=max(1, int(self.p.ma_slow)))
        self._filter = ExponentialMovingAverage(series, period=max(1, int(self.p.ma_filtr)))
        self.addminperiod(max(int(self.p.ma_slow), int(self.p.ma_fast), int(self.p.ma_filtr)) + 20)
        self._trend = 0

    def next(self):
        """Compute buy/sell arrows for the current bar (event-driven mode).

        Detects a confirmed turn in the fast-minus-slow spread and plots a buy
        arrow below the low or a sell arrow above the high, offset by half the
        recent average range, toggling the internal trend latch.
        """
        value1_0 = float(self._fast[0]) - float(self._slow[0])
        value1_1 = float(self._fast[-1]) - float(self._slow[-1])
        value1_2 = float(self._fast[-2]) - float(self._slow[-2])
        current = float(self._filter[0])
        prev = float(self._filter[-1])
        avg_range = 0.0
        for count in range(10):
            avg_range += abs(float(self.data.high[-count]) - float(self.data.low[-count]))
        range_value = avg_range / 10.0
        self.lines.buy[0] = 0.0
        self.lines.sell[0] = 0.0
        if self._trend <= 0:
            if value1_0 > value1_1 and current >= prev and value1_1 <= value1_2:
                self.lines.buy[0] = float(self.data.low[0]) - range_value * 0.5
                self._trend = 1
        if self._trend >= 0:
            if value1_0 < value1_1 and current <= prev and value1_1 >= value1_2:
                self.lines.sell[0] = float(self.data.high[0]) + range_value * 0.5
                self._trend = -1

    def once(self, start, end):
        """Compute buy/sell arrows over a range of bars (vectorized mode).

        Vectorized equivalent of ``next`` used under ``runonce``: iterates the
        arrays from ``start`` to ``end``, detecting confirmed spread turns and
        writing buy/sell arrow values while maintaining the trend latch.

        Args:
            start: First bar index to process.
            end: Stop index (exclusive) for processing.
        """
        fast = self._fast.array
        slow = self._slow.array
        filtr = self._filter.array
        high = self.data.high.array
        low = self.data.low.array
        buy = self.lines.buy.array
        sell = self.lines.sell.array
        trend = 0
        for i in range(start, end):
            buy[i] = 0.0
            sell[i] = 0.0
            if i < 12:
                continue
            value1_0 = float(fast[i]) - float(slow[i])
            value1_1 = float(fast[i - 1]) - float(slow[i - 1])
            value1_2 = float(fast[i - 2]) - float(slow[i - 2])
            current = float(filtr[i])
            prev = float(filtr[i - 1])
            if not all(math.isfinite(v) for v in (value1_0, value1_1, value1_2, current, prev)):
                continue
            avg_range = 0.0
            valid_ranges = 0
            for count in range(10):
                idx = i - count
                bar_range = abs(float(high[idx]) - float(low[idx]))
                if math.isfinite(bar_range):
                    avg_range += bar_range
                    valid_ranges += 1
            range_value = avg_range / valid_ranges if valid_ranges else 0.0
            if trend <= 0 and value1_0 > value1_1 and current >= prev and value1_1 <= value1_2:
                buy[i] = float(low[i]) - range_value * 0.5
                trend = 1
            if trend >= 0 and value1_0 < value1_1 and current <= prev and value1_1 >= value1_2:
                sell[i] = float(high[i]) + range_value * 0.5
                trend = -1
        self._trend = trend
