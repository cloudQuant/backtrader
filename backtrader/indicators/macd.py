#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import Indicator, MovAv

# macd相关的指标
class MACD(Indicator):
    '''
    Moving Average Convergence Divergence. Defined by Gerald Appel in the 70s.

    It measures the distance of a short and a long term moving average to
    try to identify the trend.

    A second lagging moving average over the convergence-divergence should
    provide a "signal" upon being crossed by the macd

    Formula:
      - macd = ema(data, me1_period) - ema(data, me2_period)
      - signal = ema(macd, signal_period)

    See:
      - http://en.wikipedia.org/wiki/MACD
    '''
    lines = ('macd', 'signal',)
    params = (('period_me1', 12), ('period_me2', 26), ('period_signal', 9),
              ('movav', MovAv.Exponential),)

    plotinfo = dict(plothlines=[0.0])
    plotlines = dict(signal=dict(ls='--'))

    def _plotlabel(self):
        plabels = super(MACD, self)._plotlabel()
        if self.p.isdefault('movav'):
            plabels.remove(self.p.movav)
        return plabels

    def __init__(self):
        super(MACD, self).__init__()
        me1 = self.p.movav(self.data, period=self.p.period_me1)
        me2 = self.p.movav(self.data, period=self.p.period_me2)
        self.lines.me1 = me1
        self.lines.me2 = me2
        self.lines.macd = me1 - me2
        self.lines.signal = self.p.movav(self.lines.macd,
                                         period=self.p.period_signal)


class MACDHisto(MACD):
    '''
    Subclass of MACD which adds a "histogram" of the difference between the
    macd and signal lines

    Formula:
      - histo = macd - signal

    See:
      - http://en.wikipedia.org/wiki/MACD
    '''
    alias = ('MACDHistogram',)

    lines = ('histo',)
    plotlines = dict(histo=dict(_method='bar', alpha=0.50, width=1.0))

    def __init__(self):
        super(MACDHisto, self).__init__()
        self.lines.histo = self.lines.macd - self.lines.signal
