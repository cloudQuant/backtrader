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
        # CRITICAL FIX: Inherit minperiod from data sources first
        # This is needed because the framework's automatic inheritance isn't working
        if hasattr(self, 'datas') and self.datas:
            data_minperiods = [getattr(d, '_minperiod', 1) for d in self.datas]
            self._minperiod = max([self._minperiod] + data_minperiods)
        # CRITICAL FIX: Add minperiod for lookback requirement (nzd(-1) in master)
        # addminperiod(n) adds n-1 to minperiod, so addminperiod(2) adds 1
        self.addminperiod(2)
        # For next() mode: track last non-zero difference
        self._last_nzd = None

    def prenext(self):
        # Track difference during warmup period so _last_nzd is available in nextstart
        # This is similar to MACD's prenext that calculates MACD values during warmup
        diff = self.data0[0] - self.data1[0]
        # Update _last_nzd (memorize non-zero)
        if self._last_nzd is None:
            self._last_nzd = diff
        else:
            self._last_nzd = diff if diff != 0.0 else self._last_nzd

    def nextstart(self):
        # First bar after minperiod: check for cross using _last_nzd from prenext
        diff = self.data0[0] - self.data1[0]
        
        # Get previous non-zero difference (set during prenext)
        prev_nzd = self._last_nzd if self._last_nzd is not None else diff
        
        # Check for crossover
        up_cross = 1.0 if (prev_nzd < 0.0 and self.data0[0] > self.data1[0]) else 0.0
        down_cross = 1.0 if (prev_nzd > 0.0 and self.data0[0] < self.data1[0]) else 0.0
        self.lines.crossover[0] = up_cross - down_cross
        
        # Update _last_nzd for next()
        self._last_nzd = diff if diff != 0.0 else prev_nzd

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

        # Initialize prev_nzd from prenext period (bar before start)
        # This matches next() which uses _last_nzd set during prenext
        if start > 0 and start - 1 < len(d0array):
            prev_nzd = d0array[start - 1] - d1array[start - 1]
            # Scan backwards to find last non-zero difference (like prenext does)
            for j in range(start - 1, -1, -1):
                diff_j = d0array[j] - d1array[j]
                if diff_j != 0.0:
                    prev_nzd = diff_j
                    break
        else:
            prev_nzd = 0.0

        # Process ALL bars from start (including first bar which may have cross)
        for i in range(start, end):
            d0_val = d0array[i]
            d1_val = d1array[i]
            diff = d0_val - d1_val

            # Check crossover using prev_nzd (from previous bar)
            up_cross = 1.0 if (prev_nzd < 0.0 and d0_val > d1_val) else 0.0
            down_cross = 1.0 if (prev_nzd > 0.0 and d0_val < d1_val) else 0.0
            crossarray[i] = up_cross - down_cross

            # Update prev_nzd for next iteration (memorize non-zero)
            prev_nzd = diff if diff != 0.0 else prev_nzd
