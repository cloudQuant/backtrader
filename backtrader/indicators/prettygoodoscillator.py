#!/usr/bin/env python
"""Pretty Good Oscillator Module - PGO indicator.

This module provides the Pretty Good Oscillator (PGO) developed
by Mark Johnson for measuring price distance from moving average
in terms of ATR.

Classes:
    PrettyGoodOscillator: PGO indicator (aliases: PGO, PrettyGoodOsc).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.PGO, period=14)
"""
import math
from . import ATR, Indicator, MovAv
class PrettyGoodOscillator(Indicator):
    """
    The "Pretty Good Oscillator" (PGO) by Mark Johnson measures the distance of
    the current close from its simple moving average of period
    Average), expressed in terms of an average true range (see Average True
    Range) over a similar period.

    So for instance a PGO value of +2.5 would mean the current close is 2.5
    average days' range above the SMA.

    Johnson's approach was to use it as a breakout system for longer term
    trades. If the PGO rises above 3.0 then go long, or below -3.0 then go
    short, and in both cases exit on returning to zero (which is a close back
    at the SMA).

    Formula:
      - pgo = (data.close - sma(data, period)) / atr(data, period)

    See also:
      - http://user42.tuxfamily.org/chart/manual/Pretty-Good-Oscillator.html

    """

    alias = (
        "PGO",
        "PrettyGoodOsc",
    )
    lines = ("pgo",)

    params = (
        ("period", 14),
        ("_movav", MovAv.Simple),
    )

    def __init__(self):
        super().__init__()
        self.movav = self.p._movav(self.data, period=self.p.period)
        self.atr = ATR(self.data, period=self.p.period)

    def next(self):
        atr_val = self.atr[0]
        if atr_val != 0:
            self.lines.pgo[0] = (self.data[0] - self.movav[0]) / atr_val
        else:
            self.lines.pgo[0] = 0.0

    def once(self, start, end):
        darray = self.data.array
        ma_array = self.movav.lines[0].array
        atr_array = self.atr.lines[0].array
        larray = self.lines.pgo.array
        
        while len(larray) < end:
            larray.append(0.0)
        
        for i in range(start, min(end, len(darray), len(ma_array), len(atr_array))):
            data_val = darray[i] if i < len(darray) else 0.0
            ma_val = ma_array[i] if i < len(ma_array) else 0.0
            atr_val = atr_array[i] if i < len(atr_array) else 0.0
            
            if isinstance(ma_val, float) and math.isnan(ma_val):
                larray[i] = float("nan")
            elif isinstance(atr_val, float) and math.isnan(atr_val):
                larray[i] = float("nan")
            elif atr_val != 0:
                larray[i] = (data_val - ma_val) / atr_val
            else:
                larray[i] = 0.0
