#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)


from . import MovingAverageBase, MovAv


# Inherits from MovingAverageBase to auto-register as MovingAverage type
# HullMovingAverage指标
class HullMovingAverage(MovingAverageBase):
    '''By Alan Hull

    The Hull Moving Average solves the age old dilemma of making a moving
    average more responsive to current price activity whilst maintaining curve
    smoothness. In fact the HMA almost eliminates lag altogether and manages to
    improve smoothing at the same time.

    Formula:
      - hma = wma(2 * wma(data, period // 2) - wma(data, period), sqrt(period))

    See also:
      - http://alanhull.com/hull-moving-average

    Note:

      - Please note that the final minimum period is not the period passed with
        the parameter ``period``. A final moving average on moving average is
        done in which the period is the *square root* of the original.

        In the default case of ``30`` the final minimum period before the
        moving average produces a non-NAN value is ``34``
    '''
    alias = ('HMA', 'HullMA',)
    lines = ('hma',)

    # param 'period' is inherited from MovingAverageBase
    params = (('_movav', MovAv.WMA),)

    def __init__(self):
        wma = self.p._movav(self.data, period=self.params.period)
        wma2 = 2.0 * self.p._movav(self.data, period=self.params.period // 2)

        sqrtperiod = pow(self.params.period, 0.5)
        self.lines.hma = self.p._movav(wma2 - wma, period=int(sqrtperiod))

        # Done after calc to ensure coop inheritance and composition work
        super(HullMovingAverage, self).__init__()
