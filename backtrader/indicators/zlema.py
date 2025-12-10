#!/usr/bin/env python
from . import MovingAverageBase
from .ema import EMA


# 零滞后指数移动平均线
class ZeroLagExponentialMovingAverage(MovingAverageBase):
    """
    The zero-lag exponential moving average (ZLEMA) is a variation of the EMA
    which adds a momentum term aiming to reduce lag in the average to
    track current prices more closely.

    Formula:
      - lag = (period - 1) / 2
      - zlema = ema(2 * data - data(-lag))

    See also:
      - http://user42.tuxfamily.org/chart/manual/Zero_002dLag-Exponential-Moving-Average.html

    """

    alias = (
        "ZLEMA",
        "ZeroLagEma",
    )
    lines = ("zlema",)
    params = (("_movav", EMA),)

    def __init__(self):
        lag = (self.p.period - 1) // 2
        data = 2 * self.data - self.data(-lag)
        self.lines.zlema = self.p._movav(data, period=self.p.period)

        super().__init__()
