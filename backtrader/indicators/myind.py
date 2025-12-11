import math

import numpy as np

from . import SMA, And, If, Indicator, Max, Min

# 这个文件中保存一些自定义的指标算法


class MaBetweenHighAndLow(Indicator):
    # 判断均线是否在最高价和最低价之间
    lines = ("target",)
    params = (("period", 5),)

    def __init__(self):
        self.ma = SMA(self.data.close, period=self.p.period)
        self.high = self.data.high
        self.low = self.data.low
        self.ma_less_high = self.ma < self.high
        self.ma_more_low = self.ma > self.low
        self.lines.target = And(self.ma_more_low, self.ma_less_high)


class BarsLast(Indicator):
    # 这个指标用于分析最近一次满足条件之后到现在的bar的个数
    lines = ("bar_num",)
    params = (("period", 5), ("func", MaBetweenHighAndLow))

    def __init__(self):
        self.target = self.p.func(self.data, period=self.p.period)
        self.num = np.NaN

    def next(self):
        if self.target[0]:
            self.num = 0
        self.lines.bar_num[0] = self.num
        self.num = self.num + 1


class NewDiff(Indicator):
    # 根据国泰君安alpha因子编写的指标
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
