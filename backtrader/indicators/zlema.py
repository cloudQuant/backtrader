#!/usr/bin/env python
import math
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
        super().__init__()
        self.lag = (self.p.period - 1) // 2
        self.alpha = 2.0 / (1.0 + self.p.period)
        self.alpha1 = 1.0 - self.alpha
        self.addminperiod(self.lag + self.p.period)

    def nextstart(self):
        # Seed with SMA of adjusted data
        period = self.p.period
        lag = self.lag
        data_sum = 0.0
        for i in range(period):
            adjusted = 2.0 * self.data[-i] - self.data[-i - lag]
            data_sum += adjusted
        self.lines.zlema[0] = data_sum / period

    def next(self):
        lag = self.lag
        adjusted = 2.0 * self.data[0] - self.data[-lag]
        self.lines.zlema[0] = self.lines.zlema[-1] * self.alpha1 + adjusted * self.alpha

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.zlema.array
        period = self.p.period
        lag = self.lag
        alpha = self.alpha
        alpha1 = self.alpha1
        
        while len(larray) < end:
            larray.append(0.0)
        
        minperiod = lag + period
        for i in range(min(minperiod - 1, len(darray))):
            if i < len(larray):
                larray[i] = float("nan")
        
        # Seed value
        seed_idx = minperiod - 1
        if seed_idx < len(darray) and seed_idx >= lag:
            seed_sum = 0.0
            for j in range(period):
                idx = seed_idx - j
                if idx >= lag and idx < len(darray) and idx - lag >= 0:
                    adjusted = 2.0 * darray[idx] - darray[idx - lag]
                    seed_sum += adjusted
            prev = seed_sum / period
            if seed_idx < len(larray):
                larray[seed_idx] = prev
        else:
            prev = 0.0
        
        # Calculate ZLEMA
        for i in range(minperiod, min(end, len(darray))):
            if i >= lag and i - lag >= 0:
                adjusted = 2.0 * darray[i] - darray[i - lag]
            else:
                adjusted = darray[i]
            
            if i > 0 and i - 1 < len(larray):
                prev_val = larray[i - 1]
                if not (isinstance(prev_val, float) and math.isnan(prev_val)):
                    prev = prev_val
            
            prev = prev * alpha1 + adjusted * alpha
            if i < len(larray):
                larray[i] = prev
