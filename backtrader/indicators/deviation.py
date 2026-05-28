#!/usr/bin/env python
"""Deviation Indicator Module - Standard deviation and mean deviation.

This module provides deviation indicators for measuring data dispersion.

Classes:
    StandardDeviation: Standard deviation indicator (alias: StdDev).
    MeanDeviation: Mean absolute deviation (alias: MeanDev).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=20)
            self.stddev = bt.indicators.StdDev(self.data.close, period=20)
            self.upper_band = self.sma + 2 * self.stddev
            self.lower_band = self.sma - 2 * self.stddev

        def next(self):
            if self.data.close[0] > self.upper_band[0]:
                self.sell()
            elif self.data.close[0] < self.lower_band[0]:
                self.buy()
"""

import math

from . import Indicator, MovAv


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
        """Initialize the Standard Deviation indicator."""
        super().__init__()
        self.addminperiod(self.p.period)
        self._use_external_mean = len(self.datas) > 1
        self._mean_prev = None
        self._meansq_prev = None

    def _movav_kind(self):
        movav = self.p.movav
        names = {getattr(movav, "__name__", "")}
        aliases = getattr(movav, "alias", ())
        if isinstance(aliases, str):
            names.add(aliases)
        else:
            names.update(aliases)

        if names.intersection(
            {
                "SmoothedMovingAverage",
                "SMMA",
                "WilderMA",
                "MovingAverageSmoothed",
                "MovingAverageWilder",
                "ModifiedMovingAverage",
                "Smoothed",
            }
        ):
            return "smoothed"

        if names.intersection({"ExponentialMovingAverage", "EMA", "MovingAverageExponential", "Exponential"}):
            return "exponential"

        return "simple"

    def _finish(self, meansq, mean):
        diff = meansq - mean * mean
        if self.p.safepow:
            diff = abs(diff)
        return math.sqrt(max(0.0, diff))

    def next(self):
        """Calculate standard deviation for the current bar."""
        period = self.p.period
        if len(self) < period:
            self.lines.stddev[0] = float("nan")
            return

        kind = self._movav_kind()
        values = [float(self.data[i]) for i in range(1 - period, 1)]
        if any(value != value for value in values):
            self.lines.stddev[0] = float("nan")
            return

        if kind == "smoothed":
            alpha = 1.0 / period
        elif kind == "exponential":
            alpha = 2.0 / (1.0 + period)
        else:
            alpha = None

        if alpha is None or self._meansq_prev is None:
            meansq = math.fsum(value * value for value in values) / period
        else:
            meansq = self._meansq_prev * (1.0 - alpha) + float(self.data[0]) * float(self.data[0]) * alpha

        if self._use_external_mean:
            mean = float(self.data1[0])
        elif alpha is None or self._mean_prev is None:
            mean = math.fsum(values) / period
        else:
            mean = self._mean_prev * (1.0 - alpha) + float(self.data[0]) * alpha

        self._meansq_prev = meansq
        if not self._use_external_mean:
            self._mean_prev = mean

        self.lines.stddev[0] = self._finish(meansq, mean)

    def once(self, start, end):
        """Calculate standard deviation in runonce mode."""
        darray = self.data.array
        larray = self.lines.stddev.array
        period = self.p.period
        actual_end = min(end, len(darray))
        nan_val = float("nan")

        while len(larray) < end:
            larray.append(nan_val)

        for i in range(min(period - 1, len(larray), actual_end)):
            larray[i] = nan_val

        if self._use_external_mean:
            if hasattr(self.data1, "once"):
                self.data1.once(0, end)
            mean_array = self.data1.array
        else:
            mean_array = None

        kind = self._movav_kind()
        if kind == "smoothed":
            alpha = 1.0 / period
        elif kind == "exponential":
            alpha = 2.0 / (1.0 + period)
        else:
            alpha = None

        if alpha is None:
            for i in range(period - 1, actual_end):
                start_idx = i - period + 1
                end_idx = i + 1
                window = darray[start_idx:end_idx]
                if len(window) != period or any(value != value for value in window):
                    larray[i] = nan_val
                    continue

                meansq = math.fsum(value * value for value in window) / period
                if mean_array is not None:
                    if i >= len(mean_array) or mean_array[i] != mean_array[i]:
                        larray[i] = nan_val
                        continue
                    mean = mean_array[i]
                else:
                    mean = math.fsum(window) / period

                larray[i] = self._finish(meansq, mean)
            return

        prev_mean = None
        prev_meansq = None
        for i in range(period - 1, actual_end):
            if i == period - 1:
                window = darray[0 : period]
                if len(window) != period or any(value != value for value in window):
                    larray[i] = nan_val
                    continue
                prev_meansq = math.fsum(value * value for value in window) / period
                if mean_array is None:
                    prev_mean = math.fsum(window) / period
            else:
                value = float(darray[i])
                if value != value or prev_meansq is None:
                    larray[i] = nan_val
                    continue
                prev_meansq = prev_meansq * (1.0 - alpha) + value * value * alpha
                if mean_array is None:
                    if prev_mean is None:
                        larray[i] = nan_val
                        continue
                    prev_mean = prev_mean * (1.0 - alpha) + value * alpha

            if mean_array is not None:
                if i >= len(mean_array) or mean_array[i] != mean_array[i]:
                    larray[i] = nan_val
                    continue
                mean = mean_array[i]
            else:
                mean = prev_mean

            larray[i] = self._finish(prev_meansq, mean)


# Average deviation
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
        """Initialize the Mean Deviation indicator.

        Creates the mean deviation calculation using either
        external mean or calculated moving average.
        """
        # CRITICAL: Match master branch behavior
        # If 2 datas are provided, the 2nd is considered to be the mean of the first
        if len(self.datas) > 1:
            mean = self.data1
        else:
            mean = self.p.movav(self.data, period=self.p.period)

        absdev = abs(self.data - mean)
        self.lines.meandev = self.p.movav(absdev, period=self.p.period)


StdDev = StandardDeviation
MeanDev = MeanDeviation
