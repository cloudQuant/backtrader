#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import Indicator


__all__ = ['PercentChange', 'PctChange']

# 变动百分比
class PercentChange(Indicator):
    '''
      Measures the perccentage change of the current value with respect to that
      of period bars ago
    '''
    alias = ('PctChange',)
    lines = ('pctchange',)

    # Fancy plotting name
    plotlines = dict(pctchange=dict(_name='%change'))

    # update value to standard for Moving Averages
    params = (('period', 30),)

    def __init__(self):
        self.lines.pctchange = self.data / self.data(-self.p.period) - 1.0
        super(PercentChange, self).__init__()
