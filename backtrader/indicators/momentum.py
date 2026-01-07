#!/usr/bin/env python
"""Momentum Indicator Module - Momentum and Rate of Change.

This module provides momentum-based indicators for measuring the rate
of price change over a given period.

Classes:
    Momentum: Measures price change (difference).
    MomentumOscillator: Momentum as ratio (alias: MomentumOsc).
    RateOfChange: Rate of change indicator (alias: ROC).
    RateOfChange100: ROC with base 100 (alias: ROC100).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.ROC, period=12)
"""
import math
from . import Indicator
class Momentum(Indicator):
    """
    Measures the change in price by calculating the difference between the
    current price and the price from a given period ago


    Formula:
      - momentum = data - data_period

    See:
      - http://en.wikipedia.org/wiki/Momentum_(technical_analysis)
    """

    lines = ("momentum",)
    params = (("period", 12),)
    plotinfo = dict(plothlines=[0.0])

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period + 1)

    def next(self):
        self.lines.momentum[0] = self.data[0] - self.data[-self.p.period]

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.momentum.array
        period = self.p.period
        
        while len(larray) < end:
            larray.append(0.0)
        
        for i in range(period, min(end, len(darray))):
            larray[i] = darray[i] - darray[i - period]


class MomentumOscillator(Indicator):
    """
    Measures the ratio of change in prices over a period

    Formula:
      - mosc = 100 * (data / data_period)

    See:
      - http://ta.mql4.com/indicators/oscillators/momentum
    """

    alias = ("MomentumOsc",)

    # Named output lines
    lines = ("momosc",)

    # Accepted parameters (and defaults)
    params = (("period", 12), ("band", 100.0))

    def _plotlabel(self):
        plabels = [self.p.period]
        return plabels

    def _plotinit(self):
        self.plotinfo.plothlines = [self.p.band]

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period + 1)

    def next(self):
        prev_val = self.data[-self.p.period]
        if prev_val != 0:
            self.lines.momosc[0] = 100.0 * (self.data[0] / prev_val)
        else:
            self.lines.momosc[0] = 0.0

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.momosc.array
        period = self.p.period
        
        while len(larray) < end:
            larray.append(0.0)
        
        for i in range(period, min(end, len(darray))):
            prev_val = darray[i - period]
            if prev_val != 0:
                larray[i] = 100.0 * (darray[i] / prev_val)
            else:
                larray[i] = 0.0


class RateOfChange(Indicator):
    """
    Measures the ratio of change in prices over a period

    Formula:
      - roc = (data - data_period) / data_period

    See:
      - http://en.wikipedia.org/wiki/Momentum_(technical_analysis)
    """

    alias = ("ROC",)

    # Named output lines
    lines = ("roc",)

    # Accepted parameters (and defaults)
    params = (("period", 12),)

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period + 1)

    def next(self):
        prev_val = self.data[-self.p.period]
        if prev_val != 0:
            self.lines.roc[0] = (self.data[0] - prev_val) / prev_val
        else:
            self.lines.roc[0] = 0.0

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.roc.array
        period = self.p.period
        
        while len(larray) < end:
            larray.append(0.0)
        
        for i in range(period, min(end, len(darray))):
            prev_val = darray[i - period]
            if prev_val != 0:
                larray[i] = (darray[i] - prev_val) / prev_val
            else:
                larray[i] = 0.0


class RateOfChange100(Indicator):
    """
    Measures the ratio of change in prices over a period with base 100

    This is, for example, how ROC is defined in stockcharts

    Formula:
      - roc = 100 * (data - data_period) / data_period

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:rate_of_change_roc_and_momentum

    """

    alias = ("ROC100",)

    # Named output lines
    lines = ("roc100",)

    # Accepted parameters (and defaults)
    params = (("period", 12),)

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period + 1)

    def next(self):
        prev_val = self.data[-self.p.period]
        if prev_val != 0:
            self.lines.roc100[0] = 100.0 * (self.data[0] - prev_val) / prev_val
        else:
            self.lines.roc100[0] = 0.0

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.roc100.array
        period = self.p.period
        
        while len(larray) < end:
            larray.append(0.0)
        
        for i in range(period, min(end, len(darray))):
            prev_val = darray[i - period]
            if prev_val != 0:
                larray[i] = 100.0 * (darray[i] - prev_val) / prev_val
            else:
                larray[i] = 0.0


ROC = RateOfChange
ROC100 = RateOfChange100
