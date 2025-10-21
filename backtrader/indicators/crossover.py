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
        self.l.nzd[0] = d if d else self.l.nzd[-1]

    def oncestart(self, start, end):
        self.line.array[start] = self.data0.array[start] - self.data1.array[start]

    def once(self, start, end):
        d0array = self.data0.array
        d1array = self.data1.array
        larray = self.line.array
        
        prev = larray[start - 1] if start > 0 else 0.0
        
        for i in range(start, end):
            d = d0array[i] - d1array[i]
            larray[i] = prev = d if d else prev


class _CrossBase(Indicator):
    _mindatas = 2
    lines = ("cross",)
    plotinfo = dict(plotymargin=0.05, plotyhlines=[0.0, 1.0])

    def __init__(self):
        nzd = NonZeroDifference(self.data0, self.data1)
        
        if hasattr(self, '_crossup'):
            if self._crossup:
                # Upward cross: previous diff <= 0, now data0 > data1
                before = nzd(-1) <= 0.0
                after = self.data0 > self.data1
            else:
                # Downward cross: previous diff >= 0, now data0 < data1
                before = nzd(-1) >= 0.0
                after = self.data0 < self.data1

            self.lines.cross = And(before, after)


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
        # Keep compatibility with existing composition but primary value
        # is computed explicitly in next/once for correctness/performance
        upcross = CrossUp(self.data0, self.data1)
        downcross = CrossDown(self.data0, self.data1)
        self.lines.crossover = upcross - downcross
        super(CrossOver, self).__init__()

    def next(self):
        try:
            d00 = float(self.data0[0])
            d10 = float(self.data1[0])
            d01 = float(self.data0[-1])
            d11 = float(self.data1[-1])
        except Exception:
            self.lines.crossover[0] = 0.0
            return

        if d00 > d10 and d01 <= d11:
            self.lines.crossover[0] = 1.0
        elif d00 < d10 and d01 >= d11:
            self.lines.crossover[0] = -1.0
        else:
            self.lines.crossover[0] = 0.0

    def once(self, start, end):
        d0 = self.data0.array
        d1 = self.data1.array
        out = self.lines.crossover.array

        # Ensure output sized
        while len(out) < end:
            out.append(0.0)

        # Start from max(start,1) because we need previous bar
        i0 = max(start, 1)
        for i in range(i0, end):
            d00 = d0[i]
            d10 = d1[i]
            d01 = d0[i - 1]
            d11 = d1[i - 1]

            if d00 > d10 and d01 <= d11:
                out[i] = 1.0
            elif d00 < d10 and d01 >= d11:
                out[i] = -1.0
            else:
                out[i] = 0.0
