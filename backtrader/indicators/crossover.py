#!/usr/bin/env python
"""Crossover Indicator Module - Crossover detection indicators.

This module provides indicators for detecting when two data series cross
each other (upward or downward).

Classes:
    NonZeroDifference: Tracks difference, memorizing last non-zero value (alias: NZD).
    CrossUp: Detects upward crossover.
    CrossDown: Detects downward crossover.
    CrossOver: Detects both directional crossovers.

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.sma_fast = bt.indicators.SMA(self.data, period=10)
            self.sma_slow = bt.indicators.SMA(self.data, period=20)
            self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)

        def next(self):
            if self.crossover[0] > 0:
                self.buy()
            elif self.crossover[0] < 0:
                self.sell()
"""

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
        """Initialize the NonZeroDifference indicator.

        Tracks difference between two data sources.
        """
        super().__init__()

    def nextstart(self):
        """Initialize NZD on first valid bar.

        Sets initial difference value.
        """
        self.l.nzd[0] = self.data0[0] - self.data1[0]

    def next(self):
        """Calculate NZD for the current bar.

        Memorizes last non-zero difference when current difference is zero.
        """
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
        """Initialize the crossover base indicator.

        Creates NonZeroDifference for crossover detection.
        """
        super().__init__()  # CRITICAL: Call parent init first
        self.nzd = NonZeroDifference(self.data0, self.data1)

    def next(self):
        """Detect crossover for the current bar.

        Returns 1.0 if crossover detected, 0.0 otherwise.
        """
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
        """Initialize the CrossOver indicator.

        Sets up minperiod and tracking variables for crossover detection.
        """
        super().__init__()
        # CRITICAL FIX: Inherit minperiod from data sources first
        # This is needed because the framework's automatic inheritance isn't working
        if hasattr(self, "datas") and self.datas:
            data_minperiods = [getattr(d, "_minperiod", 1) for d in self.datas]
            self._minperiod = max([self._minperiod] + data_minperiods)
        # CRITICAL FIX: Add minperiod for lookback requirement (nzd(-1) in master)
        # addminperiod(n) adds n-1 to minperiod, so addminperiod(2) adds 1
        self.addminperiod(2)
        # For next() mode: track last non-zero difference
        self._last_nzd = None
        # CRITICAL FIX: Track owner's data length to detect replay mode
        # In replay mode, we should only calculate crossover when the bar is complete
        # The owner (strategy) has the actual data feed whose length changes when bars complete
        self._last_owner_data_len = 0
        self._owner_data = None  # Will be set to owner's data feed in next()

    def prenext(self):
        """Track difference during warmup period.

        Updates _last_nzd for use in nextstart/next crossover detection.
        """
        # Track difference during warmup period so _last_nzd is available in nextstart
        # This is similar to MACD's prenext that calculates MACD values during warmup
        diff = self.data0[0] - self.data1[0]
        # Update _last_nzd (memorize non-zero)
        if self._last_nzd is None:
            self._last_nzd = diff
        else:
            self._last_nzd = diff if diff != 0.0 else self._last_nzd

    def nextstart(self):
        """Calculate crossover on first valid bar.

        Handles replay mode special case and calculates initial crossover.
        """
        # CRITICAL FIX: In replay mode, the first bar after minperiod doesn't have a valid
        # "previous" bar in the compressed timeframe context. Skip crossover calculation
        # on the first bar ONLY when in replay mode. For normal mode, calculate normally.
        diff = self.data0[0] - self.data1[0]

        # Check if we're in replay mode by checking owner's datas for replaying attribute
        is_replay = False
        if hasattr(self, "_owner") and hasattr(self._owner, "datas"):
            for data in self._owner.datas:
                if hasattr(data, "replaying") and data.replaying > 0:
                    is_replay = True
                    break

        if is_replay:
            # In replay mode, skip crossover on first bar - set to 0 and update _last_nzd
            self.lines.crossover[0] = 0.0
            # Update _last_nzd for next()
            prev_nzd = self._last_nzd if self._last_nzd is not None else diff
            self._last_nzd = diff if diff != 0.0 else prev_nzd
            return

        # Normal mode: calculate crossover normally
        # Get previous non-zero difference (set during prenext)
        prev_nzd = self._last_nzd if self._last_nzd is not None else diff

        # Check for crossover
        up_cross = 1.0 if (prev_nzd < 0.0 and self.data0[0] > self.data1[0]) else 0.0
        down_cross = 1.0 if (prev_nzd > 0.0 and self.data0[0] < self.data1[0]) else 0.0
        self.lines.crossover[0] = up_cross - down_cross

        # Update _last_nzd for next()
        self._last_nzd = diff if diff != 0.0 else prev_nzd

    def next(self):
        """Calculate crossover for the current bar.

        Returns 1.0 for upward cross, -1.0 for downward cross, 0.0 otherwise.
        Handles replay mode correctly by deferring calculation when bars are updating.
        """
        # Current difference
        diff = self.data0[0] - self.data1[0]

        # CRITICAL FIX: In replay mode with runonce, the same bar is updated multiple times.
        # The key insight is that we should only calculate crossover when we're at a NEW bar
        # (idx has advanced), not when we're updating the same bar multiple times.
        # We detect this by checking if idx < len - 1, which means we haven't advanced yet.
        # IMPORTANT: Only apply this logic in replay mode, not in exactbars mode!

        # Check if we're in replay mode
        is_replay = False
        if hasattr(self, "_owner") and hasattr(self._owner, "datas"):
            for data in self._owner.datas:
                if hasattr(data, "replaying") and data.replaying > 0:
                    is_replay = True
                    break

        # Only defer crossover calculation in replay mode
        if is_replay and hasattr(self.lines[0], "idx") and hasattr(self.lines[0], "__len__"):
            current_idx = self.lines[0].idx
            current_len = len(self.lines[0])
            # If idx < len - 1, we're still filling the current bar, not at a new bar yet
            # Defer crossover calculation by updating _last_nzd but setting crossover to 0
            if current_idx < current_len - 1:
                # Still updating current bar - defer crossover calculation
                if self._last_nzd is None:
                    self._last_nzd = diff
                elif diff != 0.0:
                    self._last_nzd = diff
                self.lines.crossover[0] = 0.0
                return

        # At this point, we're at a new bar (idx == len - 1), calculate crossover
        # using the previous bar's difference (stored in _last_nzd or from data[-1])
        try:
            prev_diff = self.data0[-1] - self.data1[-1]
            # Find last non-zero difference by looking at line values
            if prev_diff == 0.0:
                prev_nzd = self._last_nzd if self._last_nzd is not None else diff
            else:
                prev_nzd = prev_diff
        except (IndexError, TypeError):
            # Fall back to cached value
            prev_nzd = self._last_nzd if self._last_nzd is not None else diff

        # Update _last_nzd for next bar
        if self._last_nzd is None:
            self._last_nzd = diff
        elif diff != 0.0:
            self._last_nzd = diff

        # Check for crossover using STRICT inequalities
        # Upward: prev < 0 and now data0 > data1
        up_cross = 1.0 if (prev_nzd < 0.0 and self.data0[0] > self.data1[0]) else 0.0

        # Downward: prev > 0 and now data0 < data1
        down_cross = 1.0 if (prev_nzd > 0.0 and self.data0[0] < self.data1[0]) else 0.0

        # Combine
        self.lines.crossover[0] = up_cross - down_cross

    def once(self, start, end):
        """Calculate crossover in runonce mode.

        Vectorized implementation that processes all bars at once.
        """
        # Vectorized once() implementation matching next() behavior
        d0array = self.data0.array
        d1array = self.data1.array
        crossarray = self.line.array

        # Handle case where data is shorter than minperiod
        if start >= end:
            # No bars to process - initialize all to 0
            while len(crossarray) < len(d0array):
                crossarray.append(0.0)
            return

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

        # CRITICAL FIX: For replay mode, skip crossover on the very first bar.
        # The first bar after minperiod doesn't have a valid "previous" bar in the
        # compressed timeframe context. Defer crossover to the second bar.
        # This prevents false positive crossovers at the start of replay data.
        # ONLY apply this fix when in replay mode.
        is_replay = False
        if hasattr(self, "_owner") and hasattr(self._owner, "datas"):
            for data in self._owner.datas:
                if hasattr(data, "replaying") and data.replaying > 0:
                    is_replay = True
                    break

        first_bar = start if is_replay else -1  # -1 means never skip

        # Process ALL bars from start
        for i in range(start, end):
            d0_val = d0array[i]
            d1_val = d1array[i]
            diff = d0_val - d1_val

            # Skip crossover calculation on first bar ONLY in replay mode
            if i == first_bar:
                crossarray[i] = 0.0
                # Still update prev_nzd for next iteration
                prev_nzd = diff if diff != 0.0 else prev_nzd
                continue

            # Check crossover using prev_nzd (from previous bar)
            up_cross = 1.0 if (prev_nzd < 0.0 and d0_val > d1_val) else 0.0
            down_cross = 1.0 if (prev_nzd > 0.0 and d0_val < d1_val) else 0.0
            crossarray[i] = up_cross - down_cross

            # Update prev_nzd for next iteration (memorize non-zero)
            prev_nzd = diff if diff != 0.0 else prev_nzd
