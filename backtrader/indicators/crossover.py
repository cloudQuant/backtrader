#!/usr/bin/env python
from . import Indicator


class NonZeroDifference(Indicator):
    """
    Keeps track of the difference between two data inputs, memorizing
    the last non-zero value if the current difference is zero
    """

    _mindatas = 2
    alias = ("NZD",)
    lines = ("nzd",)

    def __init__(self):
        super().__init__()

    def nextstart(self):
        self.l.nzd[0] = self.data0[0] - self.data1[0]

    def next(self):
        d = self.data0[0] - self.data1[0]
        # Memorize last non-zero value
        new_val = d if d else self.l.nzd[-1]
        self.l.nzd[0] = new_val

    # Don't override once() - let framework call next() for each bar


class _CrossBase(Indicator):
    _mindatas = 2
    lines = ("cross",)
    plotinfo = dict(plotymargin=0.05, plotyhlines=[0.0, 1.0])

    def __init__(self):
        super().__init__()  # CRITICAL: Call parent init first
        self.nzd = NonZeroDifference(self.data0, self.data1)

    def next(self):
        # Check for crossover
        if hasattr(self, "_crossup"):
            if self._crossup:
                # Upward cross: previous diff < 0 (strictly), now data0 > data1
                before = self.nzd(-1) < 0.0  # STRICT inequality
                after = self.data0[0] > self.data1[0]
            else:
                # Downward cross: previous diff > 0 (strictly), now data0 < data1
                before = self.nzd(-1) > 0.0  # STRICT inequality
                after = self.data0[0] < self.data1[0]

            self.lines.cross[0] = 1.0 if (before and after) else 0.0
        else:
            self.lines.cross[0] = 0.0

    # Don't override once() - let framework call next() for each bar


class CrossUp(_CrossBase):
    """Upward cross indicator"""

    _crossup = True


class CrossDown(_CrossBase):
    """Downward cross indicator"""

    _crossup = False


class CrossOver(Indicator):
    """
    Gives signal for data crossover:
    1.0 for upward cross, -1.0 for downward cross, 0.0 otherwise
    """

    _mindatas = 2
    lines = ("crossover",)
    plotinfo = dict(plotymargin=0.05, plotyhlines=[-1.0, 1.0])

    def __init__(self):
        super().__init__()
        # For next() mode: track last non-zero difference
        self._last_nzd = None

    def nextstart(self):
        # First bar: initialize and no cross
        diff = self.data0[0] - self.data1[0]
        self._last_nzd = diff
        self.lines.crossover[0] = 0.0

    def next(self):
        # Current difference
        diff = self.data0[0] - self.data1[0]

        # Get previous non-zero difference
        prev_nzd = self._last_nzd if self._last_nzd is not None else diff

        # Update last_nzd (memorize non-zero)
        self._last_nzd = diff if diff != 0.0 else prev_nzd

        # Check for crossover using STRICT inequalities
        # Upward: prev < 0 and now data0 > data1
        up_cross = 1.0 if (prev_nzd < 0.0 and self.data0[0] > self.data1[0]) else 0.0

        # Downward: prev > 0 and now data0 < data1
        down_cross = 1.0 if (prev_nzd > 0.0 and self.data0[0] < self.data1[0]) else 0.0

        # Combine
        self.lines.crossover[0] = up_cross - down_cross

    def once(self, start, end):
        # Vectorized once() implementation matching next() behavior
        d0array = self.data0.array
        d1array = self.data1.array
        crossarray = self.line.array

        # Ensure array is large enough
        while len(crossarray) < end:
            crossarray.append(0.0)

        # Initialize: first bar has no cross, set _last_nzd
        if start < len(d0array):
            crossarray[start] = 0.0
            prev_nzd = d0array[start] - d1array[start]
        else:
            prev_nzd = 0.0

        # Process remaining bars (same logic as next())
        for i in range(start + 1, end):
            d0_val = d0array[i]
            d1_val = d1array[i]
            diff = d0_val - d1_val

            # Check crossover using prev_nzd (from previous bar)
            up_cross = 1.0 if (prev_nzd < 0.0 and d0_val > d1_val) else 0.0
            down_cross = 1.0 if (prev_nzd > 0.0 and d0_val < d1_val) else 0.0
            crossarray[i] = up_cross - down_cross

            # Update prev_nzd for next iteration (memorize non-zero)
            prev_nzd = diff if diff != 0.0 else prev_nzd
