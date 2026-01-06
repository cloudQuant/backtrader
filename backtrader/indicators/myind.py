import math

import numpy as np

from . import SMA, And, If, Indicator, Max, Min

# This file contains some custom indicator algorithms


class MaBetweenHighAndLow(Indicator):
    # Check if moving average is between high and low prices
    lines = ("target",)
    params = (("period", 5),)

    def __init__(self):
        super().__init__()
        self.ma = SMA(self.data.close, period=self.p.period)

    def next(self):
        ma_val = self.ma[0]
        high_val = self.data.high[0]
        low_val = self.data.low[0]
        self.lines.target[0] = 1.0 if (ma_val < high_val and ma_val > low_val) else 0.0

    def once(self, start, end):
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
    # This indicator analyzes the number of bars since the last condition was met
    lines = ("bar_num",)
    params = (("period", 5), ("func", MaBetweenHighAndLow))

    def __init__(self):
        self.target = self.p.func(self.data, period=self.p.period)
        self.num = np.nan

    def next(self):
        if self.target[0]:
            self.num = 0
        self.lines.bar_num[0] = self.num
        self.num = self.num + 1


class NewDiff(Indicator):
    # Indicator based on Guotai Junan alpha factor
    # ：SUM((CLOSE=DELAY(CLOSE,1)?0:CLOSE-(CLOSE>DELAY(CLOSE,1)?MIN(LOW,DELAY(CLOSE,1)):MAX(HIGH,DELAY(CLOSE,1)))),6)
    # - e = MIN(LOW, DELAY(CLOSE, 1))
    # - f = MAX(HIGH, DELAY(CLOSE, 1))
    # - h = CLOSE > DELAY(CLOSE, 1)
    # - b = h?e: f
    # - a = CLOSE = DELAY(CLOSE, 1)?0: CLOSE - b
    # - c = SUM(a, 6)
    lines = ("factor",)
    params = (("period", 5),)

    def __init__(self):
        close = self.data.close
        pre_close = self.data.close(-1)
        e = Min(self.data.low, pre_close)
        f = Max(self.data.high, pre_close)
        b = If(close > pre_close, e, f)
        self.a = If(close == pre_close, 0, close - b)

    def next(self):
        if len(self.a) >= self.p.period:
            self.lines.factor[0] = math.fsum(self.a.get(size=self.p.period))
        else:
            self.lines.factor[0] = np.nan
