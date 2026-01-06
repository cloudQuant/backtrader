#!/usr/bin/env python
import math
from . import Indicator
from .ema import ExponentialMovingAverage


# True Strength Indicator
class TrueStrengthIndicator(Indicator):
    """
    The True Strength Indicators was first introduced in Stocks & Commodities
    Magazine by its author William Blau. It measures momentum with a double
    exponential (default) of the prices.

    It shows divergence if the extremes keep on growign but closing prices
    do not in the same manner (distance to the extremes grows)

    Formula:
      - price_change = close - close(pchange periods ago)
      - sm1_simple = EMA(price_close_change, period1)
      - sm1_double = EMA(sm1_simple, period2)
      - sm2_simple = EMA(abs(price_close_change), period1)
      - sm2_double = EMA(sm2_simple, period2)
      - tsi = 100.0 * sm1_double / sm2_double

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:true_strength_index

    Params

      - ``period1``: the period for the first smoothing
      - ``period2``: the period for the second smoothing
      - ``pchange``: the lookback period for the price change
      - ``_movav``: the moving average to apply for the smoothing
    """

    alias = ("TSI",)
    params = (
        ("period1", 25),
        ("period2", 13),
        ("pchange", 1),
        ("_movav", ExponentialMovingAverage),
    )
    lines = ("tsi",)

    def __init__(self):
        super().__init__()
        # Store sub-indicators for direct calculation
        self.alpha1 = 2.0 / (1.0 + self.p.period1)
        self.alpha1_1 = 1.0 - self.alpha1
        self.alpha2 = 2.0 / (1.0 + self.p.period2)
        self.alpha2_1 = 1.0 - self.alpha2
        
        self._sm1 = 0.0
        self._sm12 = 0.0
        self._sm2 = 0.0
        self._sm22 = 0.0
        
        self.addminperiod(self.p.pchange + self.p.period1 + self.p.period2)

    def nextstart(self):
        pc = self.data[0] - self.data[-self.p.pchange]
        self._sm1 = pc
        self._sm12 = pc
        self._sm2 = abs(pc)
        self._sm22 = abs(pc)
        
        if self._sm22 != 0:
            self.lines.tsi[0] = 100.0 * self._sm12 / self._sm22
        else:
            self.lines.tsi[0] = 0.0

    def next(self):
        pc = self.data[0] - self.data[-self.p.pchange]
        
        self._sm1 = self._sm1 * self.alpha1_1 + pc * self.alpha1
        self._sm12 = self._sm12 * self.alpha2_1 + self._sm1 * self.alpha2
        
        self._sm2 = self._sm2 * self.alpha1_1 + abs(pc) * self.alpha1
        self._sm22 = self._sm22 * self.alpha2_1 + self._sm2 * self.alpha2
        
        if self._sm22 != 0:
            self.lines.tsi[0] = 100.0 * self._sm12 / self._sm22
        else:
            self.lines.tsi[0] = 0.0

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.tsi.array
        pchange = self.p.pchange
        alpha1 = self.alpha1
        alpha1_1 = self.alpha1_1
        alpha2 = self.alpha2
        alpha2_1 = self.alpha2_1
        minperiod = pchange + self.p.period1 + self.p.period2
        
        while len(larray) < end:
            larray.append(0.0)
        
        for i in range(min(minperiod - 1, len(darray))):
            if i < len(larray):
                larray[i] = float("nan")
        
        sm1 = 0.0
        sm12 = 0.0
        sm2 = 0.0
        sm22 = 0.0
        
        for i in range(pchange, min(end, len(darray))):
            pc = darray[i] - darray[i - pchange]
            
            sm1 = sm1 * alpha1_1 + pc * alpha1
            sm12 = sm12 * alpha2_1 + sm1 * alpha2
            sm2 = sm2 * alpha1_1 + abs(pc) * alpha1
            sm22 = sm22 * alpha2_1 + sm2 * alpha2
            
            if i >= minperiod - 1:
                if sm22 != 0:
                    larray[i] = 100.0 * sm12 / sm22
                else:
                    larray[i] = 0.0
