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


def _add_fsum_partial(partials, value):
    """Add a finite float to a non-overlapping exact-sum expansion.

    This is the same error-free high/low decomposition used by ``fsum``.  The
    caller can then remove outgoing rolling-window terms without losing the
    rounded-sum contract of recalculating each window with ``math.fsum``.
    Return false if an intermediate overflow makes the expansion unusable.
    """
    if not math.isfinite(value):
        return False

    index = 0
    for partial in partials:
        if abs(value) < abs(partial):
            value, partial = partial, value

        high = value + partial
        if not math.isfinite(high):
            return False

        low = partial - (high - value)
        if low:
            partials[index] = low
            index += 1
        value = high

    del partials[index:]
    if value:
        partials.append(value)
    return True


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

        if names.intersection(
            {"ExponentialMovingAverage", "EMA", "MovingAverageExponential", "Exponential"}
        ):
            return "exponential"

        return "simple"

    def _finish(self, meansq, mean):
        diff = meansq - mean * mean
        if self.p.safepow:
            diff = abs(diff)
        return math.sqrt(max(0.0, diff))

    def _once_simple_fsum(
        self, actual_end, darray, larray, period, mean_array, nan_val, first_index
    ):
        """Retain the original per-window math.fsum calculation as fallback."""
        for i in range(first_index, actual_end):
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
            meansq = (
                self._meansq_prev * (1.0 - alpha)
                + float(self.data[0]) * float(self.data[0]) * alpha
            )

        if self._use_external_mean:
            mean = float(self.data1[0])
        elif alpha is None or self._mean_prev is None:
            mean = math.fsum(values) / period
        else:
            mean = self._mean_prev * (1.0 - alpha) + float(self.data[0]) * alpha

        self._meansq_prev = meansq
        if not self._use_external_mean:
            self._mean_prev = mean

        # Keep an unavailable external mean missing in incremental mode, just
        # as ``once`` does.  Update the smoothed source state first so a later
        # finite mean resumes from the same price-window history.
        if self._use_external_mean and mean != mean:
            self.lines.stddev[0] = float("nan")
            return

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
            # For larger simple windows, keep exact floating-point expansions
            # for the rolling sum and sum of squares.  This preserves each
            # window's math.fsum result while avoiding a slice and two full
            # scans per bar.  Small windows and unusual values keep the
            # original path, where its lower overhead and edge behavior are
            # preferable.
            if (
                period >= 64
                and mean_array is None
                and actual_end >= period
                and type(self) is _STANDARD_DEVIATION_CLASS
                and getattr(getattr(self, "_finish"), "__func__", None)
                is _STANDARD_DEVIATION_FINISH
            ):
                sum_partials = []
                square_partials = []

                for index in range(period):
                    value = float(darray[index])
                    square = value * value
                    if (
                        not math.isfinite(value)
                        or not math.isfinite(square)
                        or not _add_fsum_partial(sum_partials, value)
                        or not _add_fsum_partial(square_partials, square)
                    ):
                        self._once_simple_fsum(
                            actual_end,
                            darray,
                            larray,
                            period,
                            mean_array,
                            nan_val,
                            period - 1,
                        )
                        return

                try:
                    total_sq = math.fsum(square_partials)
                    total = math.fsum(sum_partials)
                except OverflowError:
                    self._once_simple_fsum(
                        actual_end,
                        darray,
                        larray,
                        period,
                        mean_array,
                        nan_val,
                        period - 1,
                    )
                    return

                for index in range(period - 1, actual_end):
                    if index >= period:
                        outgoing = float(darray[index - period])
                        incoming = float(darray[index])
                        outgoing_sq = outgoing * outgoing
                        incoming_sq = incoming * incoming
                        if (
                            not math.isfinite(outgoing)
                            or not math.isfinite(incoming)
                            or not math.isfinite(outgoing_sq)
                            or not math.isfinite(incoming_sq)
                            or not _add_fsum_partial(sum_partials, -outgoing)
                            or not _add_fsum_partial(sum_partials, incoming)
                            or not _add_fsum_partial(square_partials, -outgoing_sq)
                            or not _add_fsum_partial(square_partials, incoming_sq)
                        ):
                            self._once_simple_fsum(
                                actual_end,
                                darray,
                                larray,
                                period,
                                mean_array,
                                nan_val,
                                index,
                            )
                            return

                        try:
                            total_sq = math.fsum(square_partials)
                            total = math.fsum(sum_partials)
                        except OverflowError:
                            self._once_simple_fsum(
                                actual_end,
                                darray,
                                larray,
                                period,
                                mean_array,
                                nan_val,
                                index,
                            )
                            return

                    larray[index] = self._finish(
                        total_sq / period, total / period
                    )
                return

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
        # Track missing values in the rolling window without rescanning it.
        nan_count = 0
        if actual_end >= period:
            nan_count = sum(value != value for value in darray[0:period])

        for i in range(period - 1, actual_end):
            if i >= period:
                outgoing = darray[i - period]
                incoming = darray[i]
                nan_count -= outgoing != outgoing
                nan_count += incoming != incoming

            if nan_count:
                # next() leaves the smoothed state untouched while a window
                # contains NaN; retain it so recurrence resumes identically.
                larray[i] = nan_val
                continue

            if prev_meansq is None:
                window = darray[i - period + 1 : i + 1]
                if len(window) != period:
                    larray[i] = nan_val
                    continue
                prev_meansq = math.fsum(value * value for value in window) / period
                if mean_array is None:
                    prev_mean = math.fsum(window) / period
            else:
                value = float(darray[i])
                prev_meansq = prev_meansq * (1.0 - alpha) + value * value * alpha
                if mean_array is None:
                    prev_mean = prev_mean * (1.0 - alpha) + value * alpha

            if mean_array is not None:
                if i >= len(mean_array) or mean_array[i] != mean_array[i]:
                    larray[i] = nan_val
                    continue
                mean = mean_array[i]
            else:
                mean = prev_mean

            larray[i] = self._finish(prev_meansq, mean)


# Pin the definitions that were loaded with this module.  Looking up the class
# or method on ``StandardDeviation`` at call time would let a monkeypatch make
# an overridden _finish appear to be the original fast-path contract.
_STANDARD_DEVIATION_CLASS = StandardDeviation
_STANDARD_DEVIATION_FINISH = StandardDeviation._finish


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
