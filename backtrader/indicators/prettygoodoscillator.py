#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from . import Indicator, MovAv, ATR


# 价格与均线的距离除以ATR的值
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
        movav = self.p._movav(self.data, period=self.p.period)
        atr = ATR(self.data, period=self.p.period)

        self.lines.pgo = (self.data - movav) / atr
        super(PrettyGoodOscillator, self).__init__()
