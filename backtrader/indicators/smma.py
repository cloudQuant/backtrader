#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from . import MovingAverageBase, ExponentialSmoothing


# 指数平滑移动平均线
class SmoothedMovingAverage(MovingAverageBase):
    """
    Smoothing Moving Average used by Wilder in his 1978 book `New Concepts in
    Technical Trading`

    Defined in his book originally as:

      - new_value = (old_value * (period - 1) + new_data) / period

    It Can be expressed as a SmoothingMovingAverage with the following factors:

      - self.smfactor -> 1.0 / period
      - self.smfactor1 -> `1.0 - self.smfactor`

    Formula:
      - movav = prev * (1.0 - smoothfactor) + newdata * smoothfactor

    See also:
      - http://en.wikipedia.org/wiki/Moving_average#Modified_moving_average
    """

    alias = (
        "SMMA",
        "WilderMA",
        "MovingAverageSmoothed",
        "MovingAverageWilder",
        "ModifiedMovingAverage",
    )
    lines = ("smma",)

    def __init__(self):
        # Before super to ensure mixins (right-hand side in subclassing)
        # can see the assignment operation and operate on the line
        self.lines[0] = ExponentialSmoothing(
            self.data, period=self.p.period, alpha=1.0 / self.p.period
        )
        super(SmoothedMovingAverage, self).__init__()
