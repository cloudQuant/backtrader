#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "RenkoLineBreak",
]


class RenkoLineBreak(Indicator):
    """Indicator that models renko-like box transitions."""

    lines = ("upper", "lower", "boxes")
    params = (
        ("min_box_size", 500),
        ("point", 0.01),
    )

    def __init__(self):
        """Initialize box size and state."""
        box_size = float(self.p.min_box_size)
        if box_size < 0:
            box_size = 300.0
        self._box_size = box_size * float(self.p.point)
        self._seed_close = None
        self._initialized = False
        self._up = False
        self._last_valid = None
        self._bar_len = None
        self._bar_snapshot = None
        self.addminperiod(1)

    def _write(self, upper, lower, boxes, index):
        if index is None:
            self.lines.upper[0] = upper
            self.lines.lower[0] = lower
            self.lines.boxes[0] = boxes
        else:
            self.lines.upper.array[index] = upper
            self.lines.lower.array[index] = lower
            self.lines.boxes.array[index] = boxes

    def _emit(self, upper, lower, boxes, index):
        self._write(upper, lower, boxes, index)
        self._last_valid = (upper, lower, boxes)

    def next(self):
        """Update Renko upper/lower/box count states each bar."""
        self._update(float(self.data.close[0]), len(self.data), None)

    def once(self, start, end):
        """Evaluate the same transitions against absolute source positions."""
        if (
            type(self) is not RenkoLineBreak
            or getattr(self.next, "__func__", None) is not _NATIVE_NEXT
        ):
            return self.once_via_next(start, end)
        source = self.data.close
        for index in range(start, end):
            self._update(float(source.getzeroval(index)), index + 1, index)

    def _update(self, price, current_len, index):
        if current_len != self._bar_len:
            self._bar_len = current_len
            self._bar_snapshot = (self._seed_close, self._initialized, self._up, self._last_valid)
        else:
            self._seed_close, self._initialized, self._up, self._last_valid = self._bar_snapshot
        if math.isnan(price):
            self._write(float("nan"), float("nan"), float("nan"), index)
            return
        if self._seed_close is None:
            self._seed_close = price
            self._emit(0.0, 0.0, 0.0, index)
            return

        if not self._initialized:
            if abs(price - self._seed_close) < self._box_size:
                self._emit(0.0, 0.0, 0.0, index)
                return
            if price > self._seed_close:
                self._emit(price, self._seed_close, 1.0, index)
                self._up = True
            else:
                self._emit(self._seed_close, price, -1.0, index)
                self._up = False
            self._initialized = True
            return

        if index is None:
            prev_up = float(self.lines.upper[-1])
            prev_dn = float(self.lines.lower[-1])
            prev_boxes = float(self.lines.boxes[-1])
        else:
            prev_up = float(self.lines.upper.array[index - 1])
            prev_dn = float(self.lines.lower.array[index - 1])
            prev_boxes = float(self.lines.boxes.array[index - 1])
        if any(math.isnan(value) for value in (prev_up, prev_dn, prev_boxes)):
            if self._bar_snapshot[3] is None:
                self._write(float("nan"), float("nan"), float("nan"), index)
                return
            prev_up, prev_dn, prev_boxes = self._bar_snapshot[3]
            self._up = self._bar_snapshot[2]

        if price >= prev_up + self._box_size:
            if self._up:
                self._emit(price, prev_up, prev_boxes + 1.0, index)
            else:
                self._up = True
                self._emit(price, prev_up, 1.0, index)
            return

        if price <= prev_dn - self._box_size:
            if self._up:
                self._up = False
                self._emit(prev_dn, price, -1.0, index)
            else:
                self._emit(prev_dn, price, prev_boxes - 1.0, index)
            return

        self._emit(prev_up, prev_dn, prev_boxes, index)


_NATIVE_NEXT = RenkoLineBreak.next
