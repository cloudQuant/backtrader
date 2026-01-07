#!/usr/bin/env python
"""Williams Indicator Module - Williams %R indicator.

This module provides the WilliamsR indicator developed by Larry
Williams to show overbought/oversold conditions.

Classes:
    WilliamsR: Williams %R indicator.

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.WilliamsR, period=14)
"""
import math
from . import Accum, DownDay, Highest, If, Indicator, Lowest, TrueHigh, TrueLow, UpDay
class WilliamsR(Indicator):
    """
    Developed by Larry Williams to show the relation of closing prices to
    the highest-lowest range of a given period.

    Known as Williams %R (but % is not allowed in Python identifiers)

    Formula:
      - num = highest_period - close
      - den = highestg_period - lowest_period
      - percR = (num / den) * -100.0

    See:
      - http://en.wikipedia.org/wiki/Williams_%25R
    """

    lines = ("percR",)
    params = (
        ("period", 14),
        ("upperband", -20.0),
        ("lowerband", -80.0),
    )

    plotinfo = dict(plotname="Williams R%")
    plotlines = dict(percR=dict(_name="R%"))

    def _plotinif(self):
        self.plotinfo.plotyhlines = [self.p.upperband, self.p.lowerband]

    def __init__(self):
        super().__init__()
        self.highest = Highest(self.data.high, period=self.p.period)
        self.lowest = Lowest(self.data.low, period=self.p.period)

    def next(self):
        h = self.highest[0]
        low = self.lowest[0]
        c = self.data.close[0]
        den = h - low
        if den != 0:
            self.lines.percR[0] = -100.0 * (h - c) / den
        else:
            self.lines.percR[0] = 0.0

    def once(self, start, end):
        h_array = self.highest.lines[0].array
        l_array = self.lowest.lines[0].array
        c_array = self.data.close.array
        larray = self.lines.percR.array
        
        while len(larray) < end:
            larray.append(0.0)
        
        for i in range(start, min(end, len(h_array), len(l_array), len(c_array))):
            h = h_array[i] if i < len(h_array) else 0.0
            low = l_array[i] if i < len(l_array) else 0.0
            c = c_array[i] if i < len(c_array) else 0.0
            
            if isinstance(h, float) and math.isnan(h):
                larray[i] = float("nan")
            elif isinstance(low, float) and math.isnan(low):
                larray[i] = float("nan")
            else:
                den = h - low
                if den != 0:
                    larray[i] = -100.0 * (h - c) / den
                else:
                    larray[i] = 0.0


class WilliamsAD(Indicator):
    """
    By Larry Williams. It does cumulatively measure if the price is
    accumulating (upwards) or distributing (downwards) by using the concept of
    UpDays and DownDays.

    Prices can go upwards but do so in a fashion that no longer shows
    accumulation because updays and downdays are canceling out each other,
    creating a divergence.

    See:
    - http://www.metastock.com/Customer/Resources/TAAZ/?p=125
    - http://ta.mql4.com/indicators/trends/williams_accumulation_distribution
    """

    lines = ("ad",)

    def __init__(self):
        super().__init__()
        self.upday = UpDay(self.data.close)
        self.downday = DownDay(self.data.close)
        self.truelow = TrueLow(self.data)
        self.truehigh = TrueHigh(self.data)
        self._accum = 0.0

    def next(self):
        upday_val = self.upday[0]
        downday_val = self.downday[0]
        
        if upday_val > 0:
            adup = self.data.close[0] - self.truelow[0]
        else:
            adup = 0.0
        
        if downday_val > 0:
            addown = self.data.close[0] - self.truehigh[0]
        else:
            addown = 0.0
        
        self._accum += adup + addown
        self.lines.ad[0] = self._accum

    def once(self, start, end):
        upday_array = self.upday.lines[0].array
        downday_array = self.downday.lines[0].array
        truelow_array = self.truelow.lines[0].array
        truehigh_array = self.truehigh.lines[0].array
        c_array = self.data.close.array
        larray = self.lines.ad.array
        
        while len(larray) < end:
            larray.append(0.0)
        
        accum = 0.0
        for i in range(start, min(end, len(upday_array), len(downday_array), len(c_array))):
            upday_val = upday_array[i] if i < len(upday_array) else 0.0
            downday_val = downday_array[i] if i < len(downday_array) else 0.0
            close = c_array[i] if i < len(c_array) else 0.0
            tl = truelow_array[i] if i < len(truelow_array) else 0.0
            th = truehigh_array[i] if i < len(truehigh_array) else 0.0
            
            if upday_val > 0:
                adup = close - tl
            else:
                adup = 0.0
            
            if downday_val > 0:
                addown = close - th
            else:
                addown = 0.0
            
            accum += adup + addown
            larray[i] = accum
