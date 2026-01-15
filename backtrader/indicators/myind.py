#!/usr/bin/env python
"""Custom Indicators Module - User-defined indicators.

This module contains custom indicator algorithms including:
- MaBetweenHighAndLow: Check if MA is within price range
- BarsLast: Count bars since condition was met
- NewDiff: Guotai Junan alpha factor indicator
"""
import math

import numpy as np

from . import SMA, If, Indicator, Max, Min

# This file contains some custom indicator algorithms


class MaBetweenHighAndLow(Indicator):
    """Check if moving average is between high and low prices.

    Returns 1.0 when SMA is within the bar's high-low range,
    0.0 otherwise.
    """

    # Check if moving average is between high and low prices
    lines = ("target",)
    params = (("period", 5),)

    def __init__(self):
        """Initialize the MA Between High and Low indicator.

        Creates SMA for comparison with high/low range.
        """
        super().__init__()
        self.ma = SMA(self.data.close, period=self.p.period)

    def next(self):
        """Check if MA is between high and low for current bar.

        Returns 1.0 if MA is within range, 0.0 otherwise.
        """
        ma_val = self.ma[0]
        high_val = self.data.high[0]
        low_val = self.data.low[0]
        self.lines.target[0] = 1.0 if (ma_val < high_val and ma_val > low_val) else 0.0

    def once(self, start, end):
        """Check MA against high/low range in runonce mode.

        Returns 1.0 where MA is within range, 0.0 otherwise.
        """
        ma_array = self.ma.lines[0].array
        high_array = self.data.high.array
        low_array = self.data.low.array
        larray = self.lines.target.array

        while len(larray) < end:
            larray.append(0.0)

        for i in range(start, min(end, len(ma_array), len(high_array), len(low_array))):
            ma_val = ma_array[i] if i < len(ma_array) else 0.0
            high_val = high_array[i] if i < len(high_array) else 0.0
            low_val = low_array[i] if i < len(low_array) else 0.0

            if isinstance(ma_val, float) and math.isnan(ma_val):
                larray[i] = float("nan")
            else:
                larray[i] = 1.0 if (ma_val < high_val and ma_val > low_val) else 0.0


class BarsLast(Indicator):
    """Count bars since condition was last met.

    Tracks the number of bars that have passed since a specified
    condition (default: MaBetweenHighAndLow) was last true.
    """

    # This indicator analyzes the number of bars since the last condition was met
    lines = ("bar_num",)
    params = (("period", 5), ("func", MaBetweenHighAndLow))

    def __init__(self):
        """Initialize the Bars Last indicator.

        Creates target function for condition checking.
        """
        self.target = self.p.func(self.data, period=self.p.period)
        self.num = np.nan

    def next(self):
        """Count bars since condition was last met.

        Resets to 0 when condition is true, increments otherwise.
        """
        if self.target[0]:
            self.num = 0
        self.lines.bar_num[0] = self.num
        self.num = self.num + 1


class NewDiff(Indicator):
    """Guotai Junan alpha factor indicator.

    Calculates a proprietary alpha factor based on price movement
    relative to previous close and the high/low range.

    Formula:
        SUM((CLOSE==DELAY(CLOSE,1)?0:CLOSE-(CLOSE>DELAY(CLOSE,1)?
        MIN(LOW,DELAY(CLOSE,1)):MAX(HIGH,DELAY(CLOSE,1)))), period)
    """

    # Indicator based on Guotai Junan alpha factor
    # : SUM((CLOSE=DELAY(CLOSE,1)?0:CLOSE-(CLOSE>DELAY(CLOSE,1)?MIN(LOW,DELAY(CLOSE,1)):MAX(HIGH,DELAY(CLOSE,1)))),6)
    # - e = MIN(LOW, DELAY(CLOSE, 1))
    # - f = MAX(HIGH, DELAY(CLOSE, 1))
    # - h = CLOSE > DELAY(CLOSE, 1)
    # - b = h?e: f
    # - a = CLOSE = DELAY(CLOSE, 1)?0: CLOSE - b
    # - c = SUM(a, 6)
    lines = ("factor",)
    params = (("period", 5),)

    def __init__(self):
        """Initialize the NewDiff indicator.

        Sets up alpha factor calculation based on Guotai Junan formula.
        """
        close = self.data.close
        pre_close = self.data.close(-1)
        e = Min(self.data.low, pre_close)
        f = Max(self.data.high, pre_close)
        b = If(close > pre_close, e, f)
        self.a = If(close == pre_close, 0, close - b)

    def next(self):
        """Calculate NewDiff factor for the current bar.

        Sums adjusted price differences over the period.
        """
        if len(self.a) >= self.p.period:
            self.lines.factor[0] = math.fsum(self.a.get(size=self.p.period))
        else:
            self.lines.factor[0] = np.nan
