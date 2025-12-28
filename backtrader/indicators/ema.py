#!/usr/bin/env python
import math
from . import MovingAverageBase


# 指数移动平均线
class ExponentialMovingAverage(MovingAverageBase):
    """
    A Moving Average that smoothes data exponentially over time.

    It is a subclass of SmoothingMovingAverage.

      - self.smfactor -> 2 / (1 + period)
      - self.smfactor1 -> `1 - self.smfactor`

    Formula:
      - movav = prev * (1.0 - smoothfactor) + newdata * smoothfactor

    See also:
      - http://en.wikipedia.org/wiki/Moving_average#Exponential_moving_average
    """

    alias = (
        "EMA",
        "MovingAverageExponential",
    )
    lines = ("ema",)

    def __init__(self):
        super().__init__()
        self.alpha = 2.0 / (1.0 + self.p.period)
        self.alpha1 = 1.0 - self.alpha

    def nextstart(self):
        # Seed value: SMA of first period values
        period = self.p.period
        data_sum = 0.0
        for i in range(period):
            data_sum += self.data[-i]
        self.lines[0][0] = data_sum / period

    def next(self):
        # EMA formula: prev * alpha1 + current * alpha
        self.lines[0][0] = self.lines[0][-1] * self.alpha1 + self.data[0] * self.alpha

    def once(self, start, end):
        """Calculate EMA in runonce mode"""
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

        # EMA is recursive - must calculate ALL values from period onwards
        # regardless of the start parameter
        for i in range(period, min(end, len(darray))):
            current_val = float(darray[i])
            prev = prev * alpha1 + current_val * alpha
            larray[i] = prev


EMA = ExponentialMovingAverage
