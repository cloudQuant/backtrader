#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "DarvasBoxesSystem",
]


class DarvasBoxesSystem(Indicator):
    """Indicator that emits Darvas box color states from high/low progression."""

    lines = ("color",)
    params = (
        ("symmetry", True),
        ("shift", 2),
    )

    def __init__(self):
        """Initialize the indicator state and ensure required warmup bars."""
        self.addminperiod(int(self.p.shift) + 8)
        self.state = 0
        self.box_top = None
        self.box_bottom = None

    def next(self):
        """Update the running Darvas box and emit the discrete color signal."""
        if self.box_top is None:
            self.box_top = float(self.data.high[-1])
            self.box_bottom = float(self.data.low[-1])
            self.state = 1
        bar_high = float(self.data.high[0])
        bar_low = float(self.data.low[0])
        if self.state == 1:
            self.box_top = bar_high
            if self.p.symmetry:
                self.box_bottom = bar_low
        elif self.state == 2:
            if self.box_top <= bar_high:
                self.box_top = bar_high
        elif self.state == 3:
            if self.box_top > bar_high:
                self.box_bottom = bar_low
            else:
                self.box_top = bar_high
        elif self.state == 4:
            if self.box_top > bar_high:
                if self.box_bottom >= bar_low:
                    self.box_bottom = bar_low
            else:
                self.box_top = bar_high
        elif self.state == 5:
            if self.box_top > bar_high:
                if self.box_bottom >= bar_low:
                    self.box_bottom = bar_low
            else:
                self.box_top = bar_high
            self.state = 0
        self.state += 1
        shift = int(self.p.shift)
        close = float(self.data.close[0])
        open_ = float(self.data.open[0])
        color = 2.0
        if len(self.data) > shift and close > self.box_top:
            color = 4.0 if open_ < close else 3.0
        if len(self.data) > shift and close < self.box_bottom:
            color = 0.0 if open_ > close else 1.0
        self.lines.color[0] = color
