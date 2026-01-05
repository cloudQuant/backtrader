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
        super().__init__()
        # CCI needs 2*period-1 bars for proper warmup
        self.addminperiod(2 * self.p.period - 1)

    def next(self):
        period = self.p.period
        factor = self.p.factor
        
        # Calculate typical price
        tp = (self.data.high[0] + self.data.low[0] + self.data.close[0]) / 3.0
        
        # Calculate SMA of typical price
        tp_sum = tp
        for i in range(1, period):
            tp_sum += (self.data.high[-i] + self.data.low[-i] + self.data.close[-i]) / 3.0
        tpmean = tp_sum / period
        
        # Calculate deviation
        dev = tp - tpmean
        
        # Calculate mean deviation
        absdev_sum = abs(tp - tpmean)
        for i in range(1, period):
            tp_i = (self.data.high[-i] + self.data.low[-i] + self.data.close[-i]) / 3.0
            absdev_sum += abs(tp_i - tpmean)
        meandev = absdev_sum / period
        
        # Calculate CCI
        if meandev != 0:
            self.lines.cci[0] = dev / (factor * meandev)
        else:
            self.lines.cci[0] = 0.0

    def once(self, start, end):
        high_array = self.data.high.array
        low_array = self.data.low.array
        close_array = self.data.close.array
        larray = self.lines.cci.array
        period = self.p.period
        factor = self.p.factor
        minperiod = 2 * period - 1  # Match __init__
        
        while len(larray) < end:
            larray.append(0.0)
        
        # Pre-fill warmup with NaN
        for i in range(min(minperiod - 1, len(high_array))):
            if i < len(larray):
                larray[i] = float("nan")
        
        for i in range(minperiod - 1, min(end, len(high_array), len(low_array), len(close_array))):
            # Calculate typical price
            tp = (high_array[i] + low_array[i] + close_array[i]) / 3.0
            
            # Calculate SMA of typical price
            tp_sum = 0.0
            for j in range(period):
                idx = i - j
                if idx >= 0:
                    tp_sum += (high_array[idx] + low_array[idx] + close_array[idx]) / 3.0
            tpmean = tp_sum / period
            
            # Calculate deviation
            dev = tp - tpmean
            
            # Calculate mean deviation
            absdev_sum = 0.0
            for j in range(period):
                idx = i - j
                if idx >= 0:
                    tp_j = (high_array[idx] + low_array[idx] + close_array[idx]) / 3.0
                    absdev_sum += abs(tp_j - tpmean)
            meandev = absdev_sum / period
            
            # Calculate CCI
            if meandev != 0:
                larray[i] = dev / (factor * meandev)
            else:
                larray[i] = 0.0
