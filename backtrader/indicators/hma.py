#!/usr/bin/env python
"""HMA Indicator Module - Hull Moving Average.

This module provides the HMA (Hull Moving Average) indicator developed
by Alan Hull to reduce lag while maintaining smoothness.

Classes:
    HullMovingAverage: HMA indicator (aliases: HMA, HullMA).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.hma = bt.indicators.HMA(self.data.close, period=30)

        def next(self):
            if self.data.close[0] > self.hma[0]:
                self.buy()
"""
import math

from . import MovingAverageBase
from .wma import WMA


class HullMovingAverage(MovingAverageBase):
    """By Alan Hull

    The Hull Moving Average solves the age-old dilemma of making a moving
    average more responsive to current price activity whilst maintaining curve
    smoothness. In fact, the HMA almost eliminates lag altogether and manages to
    improve smoothing at the same time.

    Formula:
      - hma = wma(2 * wma(data, period // 2) - wma(data, period), sqrt(period))

    See also:
      - http://alanhull.com/hull-moving-average

    Note:

      - Please note that the final minimum period is not the period passed with
        the parameter `period`. A final moving average on moving average is
        done in which the period is the *square root* of the original.

        In the default case of `30`, the final minimum period before the
        moving average produces a non-NAN value is ``34``
    """

    alias = (
        "HMA",
        "HullMA",
    )
    lines = ("hma",)

    # param 'period' is inherited from MovingAverageBase
    params = (("_movav", WMA),)

    def __init__(self):
        """Initialize the Hull Moving Average.

        Creates full-period and half-period WMAs for the HMA calculation.
        """
        super().__init__()
        self.wma_full = self.p._movav(self.data, period=self.p.period)
        self.wma_half = self.p._movav(self.data, period=self.p.period // 2)
        self.sqrtperiod = int(pow(self.p.period, 0.5))
        # minperiod calculation
        self._minperiod = max(self._minperiod, self.p.period + self.sqrtperiod - 1)

    def _calc_wma(self, values, period):
        """Calculate WMA for a list of values.

        Args:
            values: List of values to average.
            period: Period for WMA calculation.

        Returns:
            float: Weighted moving average value.
        """
        if len(values) < period:
            return float("nan")
        coef = 2.0 / (period * (period + 1.0))
        weights = tuple(float(x) for x in range(1, period + 1))
        weighted_sum = 0.0
        for i in range(period):
            weighted_sum += weights[period - 1 - i] * values[-(i + 1)]
        return coef * weighted_sum

    def next(self):
        """Calculate HMA for the current bar.

        Formula: HMA = WMA(2*WMA(n/2) - WMA(n), sqrt(n))
        """
        # Get raw values for final WMA calculation
        sqrtperiod = self.sqrtperiod
        raw_values = []
        for i in range(sqrtperiod):
            wma2_val = 2.0 * self.wma_half[-i]
            wma_val = self.wma_full[-i]
            raw_values.append(wma2_val - wma_val)
        raw_values.reverse()

        self.lines.hma[0] = self._calc_wma(raw_values, sqrtperiod)

    def once(self, start, end):
        """Calculate HMA in runonce mode."""
        wma_full_array = self.wma_full.lines[0].array
        wma_half_array = self.wma_half.lines[0].array
        larray = self.lines.hma.array
        period = self.p.period
        sqrtperiod = self.sqrtperiod

        while len(larray) < end:
            larray.append(0.0)

        minperiod = period + sqrtperiod - 1
        for i in range(min(minperiod - 1, len(wma_full_array))):
            if i < len(larray):
                larray[i] = float("nan")

        # WMA coefficient
        coef = 2.0 / (sqrtperiod * (sqrtperiod + 1.0))
        weights = tuple(float(x) for x in range(1, sqrtperiod + 1))

        for i in range(minperiod - 1, min(end, len(wma_full_array), len(wma_half_array))):
            # Calculate raw = 2 * wma_half - wma_full for last sqrtperiod values
            weighted_sum = 0.0
            valid = True
            for j in range(sqrtperiod):
                idx = i - j
                if idx >= 0 and idx < len(wma_full_array) and idx < len(wma_half_array):
                    wma_full_val = wma_full_array[idx]
                    wma_half_val = wma_half_array[idx]
                    if isinstance(wma_full_val, float) and math.isnan(wma_full_val):
                        valid = False
                        break
                    if isinstance(wma_half_val, float) and math.isnan(wma_half_val):
                        valid = False
                        break
                    raw = 2.0 * wma_half_val - wma_full_val
                    weighted_sum += weights[sqrtperiod - 1 - j] * raw
                else:
                    valid = False
                    break

            if valid and i < len(larray):
                larray[i] = coef * weighted_sum
            elif i < len(larray):
                larray[i] = float("nan")


HMA = HullMovingAverage
