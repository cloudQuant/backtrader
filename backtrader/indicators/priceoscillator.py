#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import Indicator, Max, MovAv

# 两均线差
class _PriceOscBase(Indicator):
    params = (('period1', 12), ('period2', 26),
              ('_movav', MovAv.Exponential),)

    plotinfo = dict(plothlines=[0.0])

    def __init__(self):
        self.ma1 = self.p._movav(self.data, period=self.p.period1)
        self.ma2 = self.p._movav(self.data, period=self.p.period2)
        self.lines[0] = self.ma1 - self.ma2

        super(_PriceOscBase, self).__init__()

# 均线差
class PriceOscillator(_PriceOscBase):
    '''
    Shows the difference between a short and long exponential moving
    averages expressed in points.

    Formula:
      - po = ema(short) - ema(long)

    See:
      - http://www.metastock.com/Customer/Resources/TAAZ/?c=3&p=94
    '''
    alias = ('PriceOsc', 'AbsolutePriceOscillator', 'APO', 'AbsPriceOsc',)
    lines = ('po',)

# 类似于macd的一个指标，以百分比形式表达
class PercentagePriceOscillator(_PriceOscBase):
    '''
    Shows the difference between a short and long exponential moving
    averages expressed in percentage. The MACD does the same but expressed in
    absolute points.

    Expressing the difference in percentage allows to compare the indicator at
    different points in time when the underlying value has significatnly
    different values.

    Formula:
      - po = 100 * (ema(short) - ema(long)) / ema(long)

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:price_oscillators_ppo
    '''
    _long = True

    alias = ('PPO', 'PercPriceOsc',)

    lines = ('ppo', 'signal', 'histo')
    params = (('period_signal', 9),)

    plotlines = dict(histo=dict(_method='bar', alpha=0.50, width=1.0))

    def __init__(self):
        super(PercentagePriceOscillator, self).__init__()

        den = self.ma2 if self._long else self.ma1

        self.lines.ppo = 100.0 * self.lines[0] / den
        self.l.signal = self.p._movav(self.l.ppo, period=self.p.period_signal)
        self.lines.histo = self.lines.ppo - self.lines.signal


class PercentagePriceOscillatorShort(PercentagePriceOscillator):
    '''
    Shows the difference between a short and long exponential moving
    averages expressed in percentage. The MACD does the same but expressed in
    absolute points.

    Expressing the difference in percentage allows to compare the indicator at
    different points in time when the underlying value has significatnly
    different values.

    Most on-line literature shows the percentage calculation having the long
    exponential moving average as the denominator. Some sources like MetaStock
    use the short one.

    Formula:
      - po = 100 * (ema(short) - ema(long)) / ema(short)

    See:
      - http://www.metastock.com/Customer/Resources/TAAZ/?c=3&p=94
    '''
    _long = False
    alias = ('PPOShort', 'PercPriceOscShort',)
