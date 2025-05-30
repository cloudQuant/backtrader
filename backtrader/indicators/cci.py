#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from . import Indicator, Max, MovAv, MeanDev


# CCI指标
class CommodityChannelIndex(Indicator):
    """
    Introduced by Donald Lambert in 1980 to measure variations of the
    "typical price" (see below) from its mean to identify extremes and
    reversals

    Formula:
      - tp = typical_price = (high + low + close) / 3
      - tpmean = MovingAverage(tp, period)
      - deviation = tp - tpmean
      - meandev = MeanDeviation(tp)
      - cci = deviation / (meandeviation * factor)

    See:
      - https://en.wikipedia.org/wiki/Commodity_channel_index
    """

    alias = ("CCI",)

    lines = ("cci",)

    params = (
        ("period", 20),
        ("factor", 0.015),
        ("movav", MovAv.Simple),
        ("upperband", 100.0),
        ("lowerband", -100.0),
    )

    def _plotlabel(self):
        plabels = [self.p.period, self.p.factor]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def _plotinit(self):
        self.plotinfo.plotyhlines = [0.0, self.p.upperband, self.p.lowerband]

    def __init__(self):
        tp = (self.data.high + self.data.low + self.data.close) / 3.0
        tpmean = self.p.movav(tp, period=self.p.period)

        dev = tp - tpmean
        meandev = MeanDev(tp, tpmean, period=self.p.period)

        self.lines.cci = dev / (self.p.factor * meandev)

        super(CommodityChannelIndex, self).__init__()
