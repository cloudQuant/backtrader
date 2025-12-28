#!/usr/bin/env python
import math
from . import Indicator, MovAv


# 计算标准差
class StandardDeviation(Indicator):
    """
    Calculates the standard deviation of the passed data for a given period

    Note:
      - If 2 datas are provided as parameters, the second is considered to be the
        mean of the first

      - ``safepow`` (default: False) If this parameter is True, the standard
        deviation will be calculated as pow (abs(meansq - sqmean), 0.5) to
        safeguard for possible negative results of ``meansq - sqmean`` caused by
        the floating point representation.

    Formula:
      - meansquared = SimpleMovingAverage(pow (data, 2), period)
      - squaredmean = pow(SimpleMovingAverage(data, period), 2)
      - stddev = pow(meansquared - squaredmean, 0.5) # square root

    See:
      - http://en.wikipedia.org/wiki/Standard_deviation
    """

    alias = ("StdDev",)

    lines = ("stddev",)
    params = (
        ("period", 20),
        ("movav", MovAv.Simple),
        ("safepow", True),
    )

    def _plotlabel(self):
        plabels = [self.p.period]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)
        # Store mean indicator if provided as second data
        self._use_external_mean = len(self.datas) > 1

    def next(self):
        period = self.p.period
        data_sum = 0.0
        data_sq_sum = 0.0
        for i in range(period):
            val = self.data[-i]
            data_sum += val
            data_sq_sum += val * val
        
        mean = data_sum / period
        meansq = data_sq_sum / period
        sqmean = mean * mean
        
        diff = meansq - sqmean
        if self.p.safepow:
            diff = abs(diff)
        
        self.lines.stddev[0] = math.sqrt(max(0, diff))

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.stddev.array
        period = self.p.period
        safepow = self.p.safepow
        
        while len(larray) < end:
            larray.append(0.0)
        
        # Pre-fill warmup with NaN
        for i in range(min(period - 1, len(darray))):
            if i < len(larray):
                larray[i] = float("nan")
        
        for i in range(period - 1, min(end, len(darray))):
            data_sum = 0.0
            data_sq_sum = 0.0
            for j in range(period):
                idx = i - j
                if idx >= 0 and idx < len(darray):
                    val = darray[idx]
                    if not (isinstance(val, float) and math.isnan(val)):
                        data_sum += val
                        data_sq_sum += val * val
            
            mean = data_sum / period
            meansq = data_sq_sum / period
            sqmean = mean * mean
            
            diff = meansq - sqmean
            if safepow:
                diff = abs(diff)
            
            if i < len(larray):
                larray[i] = math.sqrt(max(0, diff))


# 平均偏差
class MeanDeviation(Indicator):
    """MeanDeviation (alias MeanDev)

    Calculates the Mean Deviation of the passed data for a given period

    Note:
      - If 2 datas are provided as parameters, the second is considered to be the
        mean of the first

    Formula:
      - mean = MovingAverage(data, period) (or provided mean)
      - absdeviation = abs (data - mean)
      - meandev = MovingAverage(absdeviation, period)

    See:
      - https://en.wikipedia.org/wiki/Average_absolute_deviation
    """

    alias = ("MeanDev",)

    lines = ("meandev",)
    params = (
        ("period", 20),
        ("movav", MovAv.Simple),
    )

    def _plotlabel(self):
        plabels = [self.p.period]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)

    def next(self):
        period = self.p.period
        # Calculate mean (SMA)
        data_sum = sum(self.data[-i] for i in range(period))
        mean = data_sum / period
        # Calculate mean absolute deviation
        absdev_sum = sum(abs(self.data[-i] - mean) for i in range(period))
        self.lines.meandev[0] = absdev_sum / period

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.meandev.array
        period = self.p.period
        
        while len(larray) < end:
            larray.append(0.0)
        
        # Pre-fill warmup with NaN
        for i in range(min(period - 1, len(darray))):
            if i < len(larray):
                larray[i] = float("nan")
        
        for i in range(period - 1, min(end, len(darray))):
            # Calculate mean
            data_sum = 0.0
            for j in range(period):
                idx = i - j
                if idx >= 0 and idx < len(darray):
                    val = darray[idx]
                    if not (isinstance(val, float) and math.isnan(val)):
                        data_sum += val
            mean = data_sum / period
            
            # Calculate mean absolute deviation
            absdev_sum = 0.0
            for j in range(period):
                idx = i - j
                if idx >= 0 and idx < len(darray):
                    val = darray[idx]
                    if not (isinstance(val, float) and math.isnan(val)):
                        absdev_sum += abs(val - mean)
            
            if i < len(larray):
                larray[i] = absdev_sum / period


StdDev = StandardDeviation
MeanDev = MeanDeviation
