#!/usr/bin/env python
"""WMA Indicator Module - Weighted Moving Average.

This module provides the WMA (Weighted Moving Average) indicator
which gives more weight to recent prices.

Classes:
    WeightedMovingAverage: WMA indicator (alias: WMA).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.wma = bt.indicators.WMA(self.data.close, period=20)

        def next(self):
            # Price above WMA indicates uptrend
            if self.data.close[0] > self.wma[0]:
                self.buy()
            # Price below WMA indicates downtrend
            elif self.data.close[0] < self.wma[0]:
                self.sell()
"""

import math

from ..utils.py3 import range
from . import MovingAverageBase


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
        """Initialize the WMA indicator.

        Calculates weights and coefficient for weighted moving average.
        """
        super().__init__()
        self.coef = 2.0 / (self.p.period * (self.p.period + 1.0))
        self.weights = tuple(float(x) for x in range(1, self.p.period + 1))

    def next(self):
        """Calculate WMA for the current bar.

        Applies arithmetic weighting with newest values having more weight.
        Uses math.fsum over chronological (oldest-first) order to match the
        framework's WeightedAverage accumulation exactly and avoid 1-ULP
        drift between runonce and event modes.
        """
        period = self.p.period
        coef = self.coef
        weights = self.weights

        # data oldest-first: data[-(period-1)] .. data[0]
        data = [self.data[-(period - 1 - i)] for i in range(period)]
        self.lines.wma[0] = coef * math.fsum(
            weights[i] * data[i] for i in range(period)
        )

    def once(self, start, end):
        """Calculate WMA in runonce mode.

        Applies weighted average calculation across all bars. Uses math.fsum
        over the chronological window (oldest-first) so results match the
        framework's WeightedAverage and the event-mode next() bit-for-bit.
        """
        darray = self.data.array
        larray = self.lines.wma.array
        period = self.p.period
        coef = self.coef
        weights = self.weights

        while len(larray) < end:
            larray.append(float("nan"))

        # Pre-fill warmup with NaN
        for i in range(min(period - 1, len(darray))):
            if i < len(larray):
                larray[i] = float("nan")

        darray_len = len(darray)
        for i in range(period - 1, min(end, darray_len)):
            window = darray[i - period + 1 : i + 1]
            # window is oldest-first; weights[0]=1.0 weights the oldest value.
            larray[i] = coef * math.fsum(
                weights[j] * window[j] for j in range(period)
            )


WMA = WeightedMovingAverage
