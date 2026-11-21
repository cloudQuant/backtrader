#!/usr/bin/env python
"""TRIX Indicator Module - Triple exponential moving average slope.

This module provides the TRIX indicator developed by Jack Hutson in the
1980s to show the rate of change of a triple smoothed moving average.

Classes:
    Trix: TRIX indicator (alias: TRIX).
    TrixSignal: TRIX with signal line.

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.trix = bt.indicators.TRIX(self.data.close, period=15)

        def next(self):
            if self.trix[0] > 0:
                self.buy()
"""

from . import Indicator
from .ema import EMA


class Trix(Indicator):
    """
    Defined by Jack Hutson in the 80s and shows the Rate of Change (%) or slope
    of a triple exponentially smoothed moving average

    Formula:
      - ema1 = EMA(data, period)
      - ema2 = EMA(ema1, period)
      - ema3 = EMA(ema2, period)
      - trix = 100 * (ema3 - ema3(-1)) / ema3(-1)

      The final formula can be simplified to: 100 * (ema3 / ema3(-1) - 1)

    The moving average used is the one originally defined by Wilder,
    the SmoothedMovingAverage

    See:
      - https://en.wikipedia.org/wiki/Trix_(technical_analysis)
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:trix
    """

    alias = ("TRIX",)
    lines = ("trix",)
    params = (
        ("period", 15),
        ("_rocperiod", 1),
        ("_movav", EMA),
    )

    plotinfo = {"plothlines": [0.0]}

    def _plotlabel(self):
        plabels = [self.p.period]
        plabels += [self.p._rocperiod] * self.p.notdefault("_rocperiod")
        plabels += [self.p._movav] * self.p.notdefault("_movav")
        return plabels

    def __init__(self):
        """Initialize the TRIX indicator.

        Creates triple EMA structure for TRIX calculation.
        """
        super().__init__()
        self.ema1 = self.p._movav(self.data, period=self.p.period)
        self.ema2 = self.p._movav(self.ema1, period=self.p.period)
        self.ema3 = self.p._movav(self.ema2, period=self.p.period)
        # The rate-of-change needs ``rocperiod`` bars beyond the last EMA's
        # first value.  Include an upstream source's minperiod as well as the
        # three EMA stages themselves.
        self._minperiod = max(
            self.ema3._minperiod + self.p._rocperiod,
            3 * self.p.period + self.p._rocperiod - 2,
        )

    def _value_at(self, index, ema3_array):
        """Return one TRIX value using the same zero-denominator rule as next."""
        if index < self._minperiod - 1:
            return float("nan")

        previous_index = index - self.p._rocperiod
        if (
            previous_index < 0
            or previous_index >= len(ema3_array)
            or index >= len(ema3_array)
        ):
            return float("nan")

        ema3_curr = float(ema3_array[index])
        ema3_prev = float(ema3_array[previous_index])
        if ema3_prev != 0:
            return 100.0 * (ema3_curr / ema3_prev - 1.0)
        return 0.0

    def next(self):
        """Calculate TRIX for the current bar.

        Formula: TRIX = 100 * (ema3 / ema3_rocperiod_ago - 1.0)
        """
        rocperiod = self.p._rocperiod
        ema3_curr = self.ema3[0]
        ema3_prev = self.ema3[-rocperiod]
        if ema3_prev != 0:
            self.lines.trix[0] = 100.0 * (ema3_curr / ema3_prev - 1.0)
        else:
            self.lines.trix[0] = 0.0

    def once(self, start, end):
        """Calculate TRIX in runonce mode.

        Computes triple EMA rate of change percentage for ``[start, end)``.
        """
        ema3_array = self.ema3.lines[0].array
        larray = self.lines.trix.array

        if start >= end:
            return

        while len(larray) < end:
            larray.append(float("nan"))

        write_start = max(0, start)
        write_end = min(end, len(ema3_array))

        for i in range(write_start, write_end):
            larray[i] = self._value_at(i, ema3_array)

        for i in range(max(write_start, write_end), end):
            larray[i] = float("nan")


class TrixSignal(Trix):
    """
    Extension of Trix with a signal line (ala MACD)

    Formula:
      - trix = Trix(data, period)
      - signal = EMA(trix, sigperiod)

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:trix
    """

    lines = ("signal",)
    params = (("sigperiod", 9),)

    def __init__(self):
        """Initialize the TRIX Signal indicator.

        Sets up signal line EMA smoothing parameters.
        """
        super().__init__()
        self.signal_alpha = 2.0 / (1.0 + self.p.sigperiod)
        self.signal_alpha1 = 1.0 - self.signal_alpha

    def nextstart(self):
        """Seed TRIX Signal calculation on first valid bar.

        Initializes signal line with TRIX value.
        """
        super().next()
        self.lines.signal[0] = self.lines.trix[0]

    def next(self):
        """Calculate TRIX and signal line for current bar.

        Signal line is EMA of TRIX values.
        """
        super().next()
        self.lines.signal[0] = (
            self.lines.signal[-1] * self.signal_alpha1 + self.lines.trix[0] * self.signal_alpha
        )

    def once(self, start, end):
        """Calculate TRIX Signal in runonce mode.

        Computes signal line as EMA of TRIX values for ``[start, end)``.
        """
        if start >= end:
            return

        super().once(start, end)
        trix_array = self.lines.trix.array
        ema3_array = self.ema3.lines[0].array
        signal_array = self.lines.signal.array
        signal_alpha = self.signal_alpha
        signal_alpha1 = self.signal_alpha1

        while len(signal_array) < end:
            signal_array.append(float("nan"))

        write_end = min(end, len(trix_array))
        write_start = max(0, start)
        write_limit = min(end, len(signal_array))
        seed_idx = self._minperiod - 1
        if seed_idx >= write_end:
            for index in range(write_start, write_limit):
                signal_array[index] = float("nan")
            return

        for index in range(write_start, min(seed_idx, write_end)):
            signal_array[index] = float("nan")

        write_start = max(write_start, seed_idx)
        if write_start >= write_end:
            for index in range(write_start, write_limit):
                signal_array[index] = float("nan")
            return

        prev_signal = self._value_at(seed_idx, ema3_array)

        # Reconstruct the recurrence state without touching the prefix.  This
        # lets runonce call this method for disjoint output ranges.  Use the
        # first TRIX bar as the seed, even when it is NaN, matching nextstart.
        for index in range(seed_idx + 1, write_start):
            trix_value = self._value_at(index, ema3_array)
            prev_signal = (
                prev_signal * signal_alpha1
                + trix_value * signal_alpha
            )

        for index in range(write_start, write_end):
            if index == seed_idx:
                signal_array[index] = prev_signal
                continue

            prev_signal = (
                prev_signal * signal_alpha1
                + float(trix_array[index]) * signal_alpha
            )
            signal_array[index] = prev_signal
