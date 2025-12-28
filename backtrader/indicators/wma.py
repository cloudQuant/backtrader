#!/usr/bin/env python
import math
from ..utils.py3 import range
from . import MovingAverageBase


# 加权平均均线
class WeightedMovingAverage(MovingAverageBase):
    """
    A Moving Average which gives an arithmetic weighting to values with the
    newest having the more weight

    Formula:
      - weights = range(1, period + 1)
      - coef = 2 / (period * (period + 1))
      - movav = coef * Sum(weight[i] * data[period - i] for i in range(period))

    See also:
      - http://en.wikipedia.org/wiki/Moving_average#Weighted_moving_average
    """

    alias = (
        "WMA",
        "MovingAverageWeighted",
    )
    lines = ("wma",)

    def __init__(self):
        super().__init__()
        self.coef = 2.0 / (self.p.period * (self.p.period + 1.0))
        self.weights = tuple(float(x) for x in range(1, self.p.period + 1))

    def next(self):
        period = self.p.period
        coef = self.coef
        weights = self.weights
        
        weighted_sum = 0.0
        for i in range(period):
            weighted_sum += weights[period - 1 - i] * self.data[-i]
        
        self.lines.wma[0] = coef * weighted_sum

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.wma.array
        period = self.p.period
        coef = self.coef
        weights = self.weights
        
        while len(larray) < end:
            larray.append(0.0)
        
        # Pre-fill warmup with NaN
        for i in range(min(period - 1, len(darray))):
            if i < len(larray):
                larray[i] = float("nan")
        
        for i in range(period - 1, min(end, len(darray))):
            weighted_sum = 0.0
            for j in range(period):
                idx = i - j
                if idx >= 0 and idx < len(darray):
                    val = darray[idx]
                    if not (isinstance(val, float) and math.isnan(val)):
                        weighted_sum += weights[period - 1 - j] * val
            
            if i < len(larray):
                larray[i] = coef * weighted_sum


WMA = WeightedMovingAverage
