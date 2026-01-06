#!/usr/bin/env python
import math
from . import Indicator, MeanDev, MovAv


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
        # CRITICAL: Use line objects to match master branch behavior
        # tp = typical price
        tp = (self.data.high + self.data.low + self.data.close) / 3.0

        # tpmean = SMA of tp
        tpmean = self.p.movav(tp, period=self.p.period)

        # dev = tp - tpmean
        dev = tp - tpmean

        # meandev = MeanDev using tp and tpmean as two data sources
        # This matches master branch's behavior: SMA(|tp - tpmean|) where tpmean varies
        meandev = MeanDev(tp, tpmean, period=self.p.period)

        # cci = dev / (factor * meandev)
        self.lines.cci = dev / (self.p.factor * meandev)

