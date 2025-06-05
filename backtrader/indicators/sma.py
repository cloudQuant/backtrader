#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from . import MovingAverageBase, Average


# 移动平均线指标
class MovingAverageSimple(MovingAverageBase):
    """
    Non-weighted average of the last n periods

    Formula:
      - movav = Sum(data, period) / period

    See also:
      - http://en.wikipedia.org/wiki/Moving_average#Simple_moving_average
    """

    alias = (
        "SMA",
        "SimpleMovingAverage",
    )
    lines = ("sma",)

    def __init__(self):
        # Before super to ensure mixins (right-hand side in subclassing)
        # can see the assignment operation and operate on the line
        print(f"SMA.__init__: Starting for {self.__class__.__name__}")
        print(f"SMA.__init__: MRO = {[cls.__name__ for cls in self.__class__.__mro__]}")
        
        self.lines[0] = Average(self.data, period=self.p.period)

        print(f"SMA.__init__: About to call super()")
        super(MovingAverageSimple, self).__init__()
        print(f"SMA.__init__: super() call completed")
