#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

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
        self.addminperiod(1)

    def next(self):
        """Update Renko upper/lower/box count states each bar."""
        price = float(self.data.close[0])

        if self._seed_close is None:
            self._seed_close = price
            self.lines.upper[0] = 0.0
            self.lines.lower[0] = 0.0
            self.lines.boxes[0] = 0.0
            return

        if not self._initialized:
            if abs(price - self._seed_close) < self._box_size:
                self.lines.upper[0] = 0.0
                self.lines.lower[0] = 0.0
                self.lines.boxes[0] = 0.0
                return
            if price > self._seed_close:
                self.lines.upper[0] = price
                self.lines.lower[0] = self._seed_close
                self.lines.boxes[0] = 1.0
                self._up = True
            else:
                self.lines.upper[0] = self._seed_close
                self.lines.lower[0] = price
                self.lines.boxes[0] = -1.0
                self._up = False
            self._initialized = True
            return

        prev_up = float(self.lines.upper[-1])
        prev_dn = float(self.lines.lower[-1])
        prev_boxes = float(self.lines.boxes[-1])

        if price >= prev_up + self._box_size:
            self.lines.upper[0] = price
            self.lines.lower[0] = prev_up
            if self._up:
                self.lines.boxes[0] = prev_boxes + 1.0
            else:
                self._up = True
                self.lines.boxes[0] = 1.0
            return

        if price <= prev_dn - self._box_size:
            self.lines.upper[0] = prev_dn
            self.lines.lower[0] = price
            if self._up:
                self._up = False
                self.lines.boxes[0] = -1.0
            else:
                self.lines.boxes[0] = prev_boxes - 1.0
            return

        self.lines.upper[0] = prev_up
        self.lines.lower[0] = prev_dn
        self.lines.boxes[0] = prev_boxes
