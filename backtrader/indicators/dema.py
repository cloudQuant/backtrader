#!/usr/bin/env python
from . import MovingAverageBase
from .ema import EMA


# 双指数平均值
class DoubleExponentialMovingAverage(MovingAverageBase):
    """
    DEMA was first time introduced in 1994, in the article "Smoothing Data with
    Faster-Moving Averages" by Patrick G. Mulloy in "Technical Analysis of
    Stocks & Commodities" magazine.

    It attempts to reduce the inherent lag associated with Moving Averages

    Formula:
      - dema = (2.0 - ema(data, period) - ema(ema(data, period), period)

    See:
      (None)
    """

    alias = (
        "DEMA",
        "MovingAverageDoubleExponential",
    )

    lines = ("dema",)
    params = (("_movav", EMA),)

    def __init__(self):
        ema = self.p._movav(self.data, period=self.p.period)
        ema2 = self.p._movav(ema, period=self.p.period)
        self.lines.dema = 2.0 * ema - ema2

        super().__init__()


# 三重指数平均值
class TripleExponentialMovingAverage(MovingAverageBase):
    """
    TEMA was first time introduced in 1994, in the article "Smoothing Data with
    Faster-Moving Averages" by Patrick G. Mulloy in "Technical Analysis of
    Stocks & Commodities" magazine.

    It attempts to reduce the inherent lag associated with Moving Averages

    Formula:
      - ema1 = ema(data, period)
      - ema2 = ema(ema1, period)
      - ema3 = ema(ema2, period)
      - tema = 3 * ema1 - 3 * ema2 + ema3

    See:
      (None)
    """

    alias = (
        "TEMA",
        "MovingAverageTripleExponential",
    )

    lines = ("tema",)
    params = (("_movav", EMA),)

    def __init__(self):
        ema1 = self.p._movav(self.data, period=self.p.period)
        ema2 = self.p._movav(ema1, period=self.p.period)
        ema3 = self.p._movav(ema2, period=self.p.period)

        self.lines.tema = 3.0 * ema1 - 3.0 * ema2 + ema3
        super().__init__()
