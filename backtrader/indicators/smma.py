#!/usr/bin/env python
"""SMMA Indicator Module - Smoothed Moving Average.

This module provides the SMMA (Smoothed Moving Average) indicator used
by J. Welles Wilder in his 1978 book.

Classes:
    SmoothedMovingAverage: SMMA indicator (aliases: SMMA, WilderMA,
        MovingAverageSmoothed, MovingAverageWilder, ModifiedMovingAverage).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.SMMA, period=14)
"""
import math
from . import MovingAverageBase
class SmoothedMovingAverage(MovingAverageBase):
    """
    Smoothing Moving Average used by Wilder in his 1978 book `New Concepts in
    Technical Trading`

    Defined in his book originally as:

      - new_value = (old_value * (period - 1) + new_data) / period

    It Can be expressed as a SmoothingMovingAverage with the following factors:

      - self.smfactor -> 1.0 / period
      - self.smfactor1 -> `1.0 - self.smfactor`

    Formula:
      - movav = prev * (1.0 - smoothfactor) + newdata * smoothfactor

    See also:
      - http://en.wikipedia.org/wiki/Moving_average#Modified_moving_average
    """

    alias = (
        "SMMA",
        "WilderMA",
        "MovingAverageSmoothed",
        "MovingAverageWilder",
        "ModifiedMovingAverage",
    )
    lines = ("smma",)

    def __init__(self):
        """Initialize the SMMA indicator.

        Calculates alpha and alpha1 smoothing factors for the
        smoothed moving average calculation.
        """
        super().__init__()
        self.alpha = 1.0 / self.p.period
        self.alpha1 = 1.0 - self.alpha

    def nextstart(self):
        """Seed SMMA calculation with SMA on first valid bar.

        Initializes with simple moving average of the first period values.
        """
        # Seed value: SMA of first period values
        period = self.p.period
        data_sum = 0.0
        for i in range(period):
            data_sum += self.data[-i]
        self.lines[0][0] = data_sum / period

    def next(self):
        """Calculate SMMA for the current bar.

        Formula: SMMA = prev_SMMMA * alpha1 + current_price * alpha
        where alpha = 1/period and alpha1 = 1 - alpha.
        """
        # SMMA formula: prev * alpha1 + current * alpha
        self.lines[0][0] = self.lines[0][-1] * self.alpha1 + self.data[0] * self.alpha

    def once(self, start, end):
        """Calculate SMMA in runonce mode"""
        darray = self.data.array
        larray = self.lines[0].array
        alpha = self.alpha
        alpha1 = self.alpha1
        period = self.p.period

        # Ensure output array is properly sized
        while len(larray) < end:
            larray.append(0.0)

        # Pre-fill warmup period with NaN
        for i in range(min(period - 1, len(darray))):
            larray[i] = float("nan")

        # Calculate seed value (SMA of first period values)
        seed_idx = period - 1
        if seed_idx < len(darray):
            seed_sum = sum(darray[0:seed_idx + 1])
            prev = seed_sum / period
            larray[seed_idx] = prev
        else:
            return  # Not enough data

        # SMMA is recursive - must calculate ALL values from period onwards
        for i in range(period, min(end, len(darray))):
            current_val = float(darray[i])
            prev = prev * alpha1 + current_val * alpha
            larray[i] = prev
