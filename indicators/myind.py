from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import backtrader as bt
import numpy as np


# 这个文件中保存一些自定义的指标算法

class MaBetweenHighAndLow(bt.Indicator):
    # 判断均线是否在最高价和最低价之间
    lines = ('target',)
    params = (('period', 5),)

    def __init__(self):
        self.ma = bt.indicators.SMA(self.data.close, period=self.p.period)
        self.high = self.data.high
        self.low = self.data.low
        self.ma_less_high = self.ma < self.high
        self.ma_more_low = self.ma > self.low
        self.lines.target = bt.And(self.ma_more_low, self.ma_less_high)


class BarsLast(bt.Indicator):
    # 这个指标用于分析最近一次满足条件之后到现在的bar的个数
    lines = ('bar_num',)
    params = (
        ('period', 5),
        ("func", MaBetweenHighAndLow)
    )

    def __init__(self):
        self.target = self.p.func(self.data, period=self.p.period)
        self.num = np.NaN

    def next(self):
        if self.target[0]:
            self.num = 0
        self.lines.bar_num[0] = self.num
        self.num = self.num + 1
