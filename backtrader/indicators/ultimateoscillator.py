#!/usr/bin/env python
"""Ultimate Oscillator Module - Ultimate Oscillator indicator.

This module provides the Ultimate Oscillator indicator which combines
multiple timeframes to reduce false signals.

Classes:
    UltimateOscillator: Ultimate Oscillator indicator.

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.UltimateOscillator)
"""
import math
from . import Indicator, SumN, TrueLow, TrueRange
class UltimateOscillator(Indicator):
    """
    Formula:
      # Buying Pressure = Close - TrueLow
      BP = Close - Minimum (Low or Prior Close)

      # TrueRange = TrueHigh - TrueLow
      TR = Maximum (High or Prior Close) - Minimum (Low or Prior Close)

      Average7 = (7-period BP Sum) / (7-period TR Sum)
      Average14 = (14-period BP Sum) / (14-period TR Sum)
      Average28 = (28-period BP Sum) / (28-period TR Sum)

      UO = 100 x [(4 x Average7)+(2 x Average14)+Average28]/(4+2+1)

    See:

      - https://en.wikipedia.org/wiki/Ultimate_oscillator
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:ultimate_oscillator
    """

    lines = ("uo",)

    params = (
        ("p1", 7),
        ("p2", 14),
        ("p3", 28),
        ("upperband", 70.0),
        ("lowerband", 30.0),
    )

    def _plotinit(self):
        baseticks = [10.0, 50.0, 90.0]
        hlines = [self.p.upperband, self.p.lowerband]

        # Plot lines at 0 & 100 to make the scale complete + upper/lower/bands
        self.plotinfo.plotyhlines = hlines
        # Plot ticks at "baseticks" + the user specified upper/lower bands
        self.plotinfo.plotyticks = baseticks + hlines

    def __init__(self):
        super().__init__()
        self.truelow = TrueLow(self.data)
        self.truerange = TrueRange(self.data)
        # CRITICAL FIX: TrueRange/TrueLow need 1 extra bar (they use close[-1])
        # Total minperiod = p3 + 1 for the TrueRange dependency
        self.addminperiod(self.p.p3 + 1)

    def next(self):
        p1, p2, p3 = self.p.p1, self.p.p2, self.p.p3
        
        # Calculate BP and TR sums for each period
        bp_sum1 = tr_sum1 = 0.0
        bp_sum2 = tr_sum2 = 0.0
        bp_sum3 = tr_sum3 = 0.0
        
        for i in range(p3):
            bp = self.data.close[-i] - self.truelow[-i]
            tr = self.truerange[-i]
            
            if i < p1:
                bp_sum1 += bp
                tr_sum1 += tr
            if i < p2:
                bp_sum2 += bp
                tr_sum2 += tr
            bp_sum3 += bp
            tr_sum3 += tr
        
        av7 = bp_sum1 / tr_sum1 if tr_sum1 != 0 else 0.0
        av14 = bp_sum2 / tr_sum2 if tr_sum2 != 0 else 0.0
        av28 = bp_sum3 / tr_sum3 if tr_sum3 != 0 else 0.0
        
        factor = 100.0 / 7.0
        self.lines.uo[0] = (4.0 * factor) * av7 + (2.0 * factor) * av14 + factor * av28

    def once(self, start, end):
        close_array = self.data.close.array
        tl_array = self.truelow.lines[0].array
        tr_array = self.truerange.lines[0].array
        larray = self.lines.uo.array
        p1, p2, p3 = self.p.p1, self.p.p2, self.p.p3
        
        while len(larray) < end:
            larray.append(0.0)
        
        for i in range(min(p3 - 1, len(close_array))):
            if i < len(larray):
                larray[i] = float("nan")
        
        for i in range(p3 - 1, min(end, len(close_array), len(tl_array), len(tr_array))):
            bp_sum1 = tr_sum1 = 0.0
            bp_sum2 = tr_sum2 = 0.0
            bp_sum3 = tr_sum3 = 0.0
            
            for j in range(p3):
                idx = i - j
                if idx >= 0 and idx < len(close_array) and idx < len(tl_array) and idx < len(tr_array):
                    bp = close_array[idx] - tl_array[idx]
                    tr = tr_array[idx]
                    
                    if j < p1:
                        bp_sum1 += bp
                        tr_sum1 += tr
                    if j < p2:
                        bp_sum2 += bp
                        tr_sum2 += tr
                    bp_sum3 += bp
                    tr_sum3 += tr
            
            av7 = bp_sum1 / tr_sum1 if tr_sum1 != 0 else 0.0
            av14 = bp_sum2 / tr_sum2 if tr_sum2 != 0 else 0.0
            av28 = bp_sum3 / tr_sum3 if tr_sum3 != 0 else 0.0
            
            factor = 100.0 / 7.0
            larray[i] = (4.0 * factor) * av7 + (2.0 * factor) * av14 + factor * av28
