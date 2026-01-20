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

import math

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

    plotinfo = dict(plothlines=[0.0])

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
        # minperiod = 3 * period + rocperiod
        self._minperiod = max(self._minperiod, 3 * self.p.period + self.p._rocperiod - 2)

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

        Computes triple EMA rate of change percentage across all bars.
        """
        ema3_array = self.ema3.lines[0].array
        larray = self.lines.trix.array
        rocperiod = self.p._rocperiod
        minperiod = 3 * self.p.period + rocperiod - 2

        while len(larray) < end:
            larray.append(0.0)

        for i in range(min(minperiod, len(ema3_array))):
            if i < len(larray):
                larray[i] = float("nan")

        for i in range(minperiod, min(end, len(ema3_array))):
            ema3_curr = ema3_array[i] if i < len(ema3_array) else 0.0
            ema3_prev = (
                ema3_array[i - rocperiod]
                if i >= rocperiod and i - rocperiod < len(ema3_array)
                else 0.0
            )

            if isinstance(ema3_curr, float) and math.isnan(ema3_curr):
                larray[i] = float("nan")
            elif isinstance(ema3_prev, float) and math.isnan(ema3_prev):
                larray[i] = float("nan")
            elif ema3_prev != 0:
                larray[i] = 100.0 * (ema3_curr / ema3_prev - 1.0)
            else:
                larray[i] = 0.0


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

        Computes signal line as EMA of TRIX values across all bars.
        """
        super().once(start, end)
        trix_array = self.lines.trix.array
        signal_array = self.lines.signal.array
        signal_alpha = self.signal_alpha
        signal_alpha1 = self.signal_alpha1

        while len(signal_array) < end:
            signal_array.append(0.0)

        # Find first valid trix value for seed
        seed_idx = -1
        for i in range(len(trix_array)):
            if i < len(trix_array):
                val = trix_array[i]
                if not (isinstance(val, float) and math.isnan(val)):
                    seed_idx = i
                    break

        if seed_idx >= 0 and seed_idx < len(signal_array):
            prev_signal = trix_array[seed_idx]
            signal_array[seed_idx] = prev_signal

            for i in range(seed_idx + 1, min(end, len(trix_array))):
                trix_val = trix_array[i] if i < len(trix_array) else 0.0
                if isinstance(trix_val, float) and math.isnan(trix_val):
                    signal_array[i] = float("nan")
                else:
                    prev_signal = prev_signal * signal_alpha1 + trix_val * signal_alpha
                    signal_array[i] = prev_signal
