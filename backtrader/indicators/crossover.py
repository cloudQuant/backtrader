#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from . import Indicator, And


class NonZeroDifference(Indicator):
    """
    Keeps track of the difference between two data inputs, memorizing
    the last non-zero value if the current difference is zero
    """

    _mindatas = 2
    alias = ("NZD",)
    lines = ("nzd",)

    def __init__(self):
        super(NonZeroDifference, self).__init__()

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
        super(_CrossBase, self).__init__()  # CRITICAL: Call parent init first
        self.nzd = NonZeroDifference(self.data0, self.data1)

    def next(self):
        # Check for crossover
        if hasattr(self, '_crossup'):
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
        super(CrossOver, self).__init__()
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

    def oncestart(self, start, end):
        # Seed: first bar has no cross
        self.line.array[start] = 0.0

    def once(self, start, end):
        # Get arrays for fast access
        d0array = self.data0.array
        d1array = self.data1.array
        crossarray = self.line.array  # Use self.line for single line indicator

        # CRITICAL: Ensure array is large enough
        while len(crossarray) < end:
            crossarray.append(0.0)

        # Track last non-zero difference
        prev_nzd = d0array[start] - d1array[start] if start > 0 else 0.0

        for i in range(start + 1, end):
            # Current values
            d0_val = d0array[i]
            d1_val = d1array[i]
            diff = d0_val - d1_val

            # Update nzd (memorize non-zero)
            current_nzd = diff if diff != 0.0 else prev_nzd

            # Check for crossover using STRICT inequalities
            # Upward: prev < 0 and now d0 > d1
            up_cross = 1.0 if (prev_nzd < 0.0 and d0_val > d1_val) else 0.0

            # Downward: prev > 0 and now d0 < d1
            down_cross = 1.0 if (prev_nzd > 0.0 and d0_val < d1_val) else 0.0

            # Store result
            result = up_cross - down_cross
            crossarray[i] = result

            # Update prev_nzd for next iteration
            prev_nzd = current_nzd
