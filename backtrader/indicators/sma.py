#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from .mabase import MovingAverageBase


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
        super(MovingAverageSimple, self).__init__()

    def next(self):
        """Optimized next() method for single-value calculation"""
        if len(self.data) >= self.p.period:
            # Efficient calculation using slice and sum
            period_data = [self.data[-i] for i in range(self.p.period)]
            self.lines.sma[0] = sum(period_data) / self.p.period
        else:
            self.lines.sma[0] = float('nan')

    def once(self, start, end):
        """Optimized batch calculation method"""
        try:
            data_array = self.data.array
            sma_array = self.lines.sma.array
            period = self.p.period
            
            # Ensure we have arrays to work with
            if not hasattr(data_array, '__len__') or not hasattr(sma_array, '__len__'):
                # Fallback to next() processing if arrays aren't available
                for i in range(start, end):
                    self._next()
                return
            
            # Vectorized calculation for better performance
            for i in range(max(start, period - 1), end):
                if i >= period - 1:
                    # Calculate SMA using array slice
                    window_sum = sum(data_array[i - period + 1:i + 1])
                    sma_array[i] = window_sum / period
                else:
                    sma_array[i] = float('nan')
                    
        except Exception:
            # Fallback to next() processing if once() fails
            for i in range(start, end):
                self._next()
