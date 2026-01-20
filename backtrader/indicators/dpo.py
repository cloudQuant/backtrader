#!/usr/bin/env python
"""DPO Indicator Module - Detrended Price Oscillator.

This module provides the DPO (Detrended Price Oscillator) indicator
developed by Joe DiNapoli to identify cycles by removing trend effects.

Classes:
    DetrendedPriceOscillator: DPO indicator (alias: DPO).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.dpo = bt.indicators.DPO(self.data, period=20)

        def next(self):
            if self.dpo[0] > 0:
                self.buy()
"""

import math

from . import Indicator, MovAv


class DetrendedPriceOscillator(Indicator):
    """
    Defined by Joe DiNapoli in his book *"Trading with DiNapoli levels"*

    It measures the price variations against a Moving Average (the trend)
    and therefore removes the "trend" factor from the price.

    Formula:
      - movav = MovingAverage(close, period)
      - dpo = close - movav(shifted period / 2 + 1)

    See:
      - http://en.wikipedia.org/wiki/Detrended_price_oscillator
    """

    # Named alias for invocation
    alias = ("DPO",)

    # Named output lines
    lines = ("dpo",)

    # Accepted parameters (and defaults) -
    # MovAvg also parameter to allow experimentation
    params = (("period", 20), ("movav", MovAv.Simple))

    # Emphasize central 0.0 line in plot
    plotinfo = dict(plothlines=[0.0])

    # Indicator information after the name (in brackets)
    def _plotlabel(self):
        plabels = [self.p.period]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self):
        """Initialize the DPO indicator.

        Creates a moving average and calculates lookback period.
        """
        super().__init__()
        self.ma = self.p.movav(self.data, period=self.p.period)
        self.lookback = self.p.period // 2 - 1

    def next(self):
        """Calculate DPO for the current bar.

        Formula: DPO = price - MA(lookback bars ago)
        """
        self.lines.dpo[0] = self.data[0] - self.ma[-self.lookback]

    def once(self, start, end):
        """Calculate DPO in runonce mode."""
        darray = self.data.array
        ma_array = self.ma.lines[0].array
        larray = self.lines.dpo.array
        lookback = self.lookback

        while len(larray) < end:
            larray.append(0.0)

        for i in range(start, min(end, len(darray), len(ma_array))):
            data_val = darray[i] if i < len(darray) else 0.0
            ma_idx = i - lookback
            if ma_idx >= 0 and ma_idx < len(ma_array):
                ma_val = ma_array[ma_idx]
            else:
                ma_val = float("nan")

            if isinstance(ma_val, float) and math.isnan(ma_val):
                larray[i] = float("nan")
            else:
                larray[i] = data_val - ma_val
