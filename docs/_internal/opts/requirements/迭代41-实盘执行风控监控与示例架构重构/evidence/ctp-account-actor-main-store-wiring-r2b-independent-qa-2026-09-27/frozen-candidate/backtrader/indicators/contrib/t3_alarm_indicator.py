#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
    SimpleMovingAverage,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "T3AlarmIndicator",
]


class T3AlarmIndicator(Indicator):
    """Double-smoothed MA slope indicator emitting direction and reversal alarms."""

    lines = ("ma2", "direction", "buy_sig", "sell_sig")
    params = (
        ("ma_period", 19),
        ("ma_shift", 0),
        ("ma_method", "ema"),
        ("ma_price", "close"),
    )

    def __init__(self):
        """Build the twice-applied moving average and reset the prior direction."""
        price = self._price_line(self.p.ma_price)
        ma_cls = self._ma_class(self.p.ma_method)
        ma1 = ma_cls(price, period=self.p.ma_period)
        self.lines.ma2 = ma_cls(ma1, period=self.p.ma_period)
        self._ma_shift = int(self.p.ma_shift)
        self._prev_direction = 0

    def next(self):
        """Update the direction line and raise buy/sell alarms on slope flips."""
        shift = self._ma_shift
        ma2_curr = self.lines.ma2[-shift] if shift > 0 else self.lines.ma2[0]
        ma2_prev = self.lines.ma2[-(shift + 1)] if True else self.lines.ma2[-1]

        if ma2_curr > ma2_prev:
            direction = 1
        elif ma2_curr < ma2_prev:
            direction = -1
        else:
            direction = self._prev_direction

        prev_dir = self._prev_direction
        self._prev_direction = direction
        self.lines.direction[0] = float(direction)
        self.lines.buy_sig[0] = 1.0 if (direction == 1 and prev_dir == -1) else 0.0
        self.lines.sell_sig[0] = 1.0 if (direction == -1 and prev_dir == 1) else 0.0

    def once(self, start, end):
        """Vectorised batch evaluation of direction and alarm lines.

        Args:
            start: Inclusive start index of the range to fill.
            end: Exclusive end index of the range to fill.
        """
        ma2 = self.lines.ma2.array
        direction_line = self.lines.direction.array
        buy_line = self.lines.buy_sig.array
        sell_line = self.lines.sell_sig.array
        for line in (direction_line, buy_line, sell_line):
            while len(line) < end:
                line.append(float("nan"))

        shift = self._ma_shift
        prev_direction = 0
        actual_end = min(end, len(ma2))
        for i in range(start, actual_end):
            curr_idx = i - shift if shift > 0 else i
            prev_idx = i - shift - 1
            if curr_idx < 0 or prev_idx < 0:
                direction = prev_direction
            else:
                ma2_curr = ma2[curr_idx]
                ma2_prev = ma2[prev_idx]
                if ma2_curr > ma2_prev:
                    direction = 1
                elif ma2_curr < ma2_prev:
                    direction = -1
                else:
                    direction = prev_direction

            prev_dir = prev_direction
            prev_direction = direction
            direction_line[i] = float(direction)
            buy_line[i] = 1.0 if (direction == 1 and prev_dir == -1) else 0.0
            sell_line[i] = 1.0 if (direction == -1 and prev_dir == 1) else 0.0
        self._prev_direction = prev_direction

    def _ma_class(self, method):
        name = str(method).lower()
        mapping = {
            "sma": SimpleMovingAverage,
            "ema": ExponentialMovingAverage,
            "smma": SmoothedMovingAverage,
            "lwma": WeightedMovingAverage,
            "wma": WeightedMovingAverage,
        }
        return mapping.get(name, ExponentialMovingAverage)

    def _price_line(self, price_name):
        name = str(price_name).lower()
        if name == "open":
            return self.data.open
        if name == "high":
            return self.data.high
        if name == "low":
            return self.data.low
        if name == "median":
            return (self.data.high + self.data.low) / 2.0
        if name == "typical":
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if name == "weighted":
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        return self.data.close
