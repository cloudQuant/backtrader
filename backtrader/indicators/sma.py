#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from .mabase import MovingAverageBase
import math


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
        print(f"SMA.__init__: Creating SMA with period={self.p.period}")
        super(MovingAverageSimple, self).__init__()

    def next(self):
        print(f"SMA.next(): Called at len(data)={len(self.data)}, period={self.p.period}")
        try:
            # Only compute if we have enough data points
            if len(self.data) >= self.p.period:
                # Calculate simple moving average by getting the last period values
                total = 0.0
                for i in range(self.p.period):
                    total += self.data[-i]
                
                avg_value = total / self.p.period
                print(f"SMA.next(): computed avg={avg_value} for data points: {[self.data[-i] for i in range(self.p.period)]}")
                self.lines.sma[0] = avg_value
            else:
                print(f"SMA.next(): Not enough data points ({len(self.data)} < {self.p.period}), setting to NaN")
                self.lines.sma[0] = float('nan')
        except Exception as e:
            print(f"SMA.next(): ERROR: {e}")
            import traceback
            traceback.print_exc()
            self.lines.sma[0] = float('nan')

    def once(self, start, end):
        print(f"SMA.once(): Called with start={start}, end={end}")
        # Let's just raise an exception to force fallback to next() processing
        # This will help us debug if next() is being called properly
        raise NotImplementedError("SMA.once() intentionally not implemented to force next() processing")
