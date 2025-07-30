#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import Indicator, MovAv

# 三重指数移动平均斜率
class Trix(Indicator):
    '''
    Defined by Jack Hutson in the 80s and shows the Rate of Change (%) or slope
    of a triple exponentially smoothed moving average

    Formula:
      - ema1 = EMA(data, period)
      - ema2 = EMA(ema1, period)
      - ema3 = EMA(ema2, period)
      - trix = 100 * (ema3 - ema3(-1)) / ema3(-1)

      The final formula can be simplified to: 100 * (ema3 / ema3(-1) - 1)

    The moving average used is the one originally defined by Wilder,
    the SmoothedMovingAverage

    See:
      - https://en.wikipedia.org/wiki/Trix_(technical_analysis)
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:trix
    '''
    alias = ('TRIX',)
    lines = ('trix',)
    params = (('period', 15), ('_rocperiod', 1), ('_movav', MovAv.EMA),)

    plotinfo = dict(plothlines=[0.0])

    def _plotlabel(self):
        plabels = [self.p.period]
        plabels += [self.p._rocperiod] * self.p.notdefault('_rocperiod')
        plabels += [self.p._movav] * self.p.notdefault('_movav')
        return plabels

    def __init__(self):

        ema1 = self.p._movav(self.data, period=self.p.period)
        ema2 = self.p._movav(ema1, period=self.p.period)
        ema3 = self.p._movav(ema2, period=self.p.period)

        # 1 period Percentage Rate of Change
        self.lines.trix = 100.0 * (ema3 / ema3(-self.p._rocperiod) - 1.0)

        super(Trix, self).__init__()


class TrixSignal(Trix):
    '''
    Extension of Trix with a signal line (ala MACD)

    Formula:
      - trix = Trix(data, period)
      - signal = EMA(trix, sigperiod)

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:trix
    '''
    lines = ('signal',)
    params = (('sigperiod', 9),)

    def __init__(self):
        super(TrixSignal, self).__init__()

        self.l.signal = self.p._movav(self.lines[0], period=self.p.sigperiod)
