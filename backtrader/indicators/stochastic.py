#!/usr/bin/env python
"""Stochastic Indicator Module - Stochastic Oscillator.

This module provides the Stochastic Oscillator indicator developed by
Dr. George Lane in the 1950s for identifying overbought/oversold conditions.

Classes:
    _StochasticBase: Base class for Stochastic indicators.
    StochasticFast: Fast Stochastic oscillator.
    Stochastic: Slow Stochastic oscillator (alias: StochasticSlow).
    StochasticFull: Full Stochastic with all 3 lines.

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.stoch = bt.indicators.Stochastic(self.data, period=14)

        def next(self):
            if self.stoch.percK[0] > self.stoch.percD[0]:
                self.buy()
"""

import math

from . import DivByZero, Highest, Indicator, Lowest, MovAv


class _StochasticBase(Indicator):
    lines = (
        "percK",
        "percD",
    )
    params = (
        ("period", 14),
        ("period_dfast", 3),
        ("movav", MovAv.Simple),
        ("upperband", 80.0),
        ("lowerband", 20.0),
        ("safediv", False),
        ("safezero", 0.0),
    )

    plotlines = dict(percD=dict(_name="%D", ls="--"), percK=dict(_name="%K"))

    def _plotlabel(self):
        plabels = [self.p.period, self.p.period_dfast]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def _plotinit(self):
        self.plotinfo.plotyhlines = [self.p.upperband, self.p.lowerband]

    def __init__(self):
        """Initialize the Stochastic base indicator.

        Creates Highest and Lowest indicators for %K calculation.
        """
        super().__init__()
        self.highesthigh = Highest(self.data.high, period=self.p.period)
        self.lowestlow = Lowest(self.data.low, period=self.p.period)
        knum = self.data.close - self.lowestlow
        kden = self.highesthigh - self.lowestlow
        if self.p.safediv:
            self.k = 100.0 * DivByZero(knum, kden, zero=self.p.safezero)
        else:
            self.k = 100.0 * (knum / kden)
        self.d = self.p.movav(self.k, period=self.p.period_dfast)

    def _calc_k(self):
        """Calculate %K value"""
        hh = self.highesthigh[0]
        ll = self.lowestlow[0]
        close = self.data.close[0]
        knum = close - ll
        kden = hh - ll
        if self.p.safediv and kden == 0:
            return self.p.safezero
        if kden == 0:
            return 0.0
        return 100.0 * (knum / kden)

    def _calc_k_at(self, ago):
        """Calculate raw %K at a relative bar offset."""
        try:
            hh = self.highesthigh[ago]
            ll = self.lowestlow[ago]
            close = self.data.close[ago]
        except (IndexError, TypeError):
            return float("nan")

        if isinstance(hh, float) and math.isnan(hh):
            return float("nan")
        if isinstance(ll, float) and math.isnan(ll):
            return float("nan")

        knum = close - ll
        kden = hh - ll
        if self.p.safediv and kden == 0:
            return self.p.safezero
        if kden == 0:
            return 0.0
        return 100.0 * (knum / kden)

    @staticmethod
    def _mean_or_nan(values):
        """Return the arithmetic mean, or NaN when any component is NaN."""
        total = 0.0
        for value in values:
            if isinstance(value, float) and math.isnan(value):
                return float("nan")
            total += value
        return total / len(values)

    def _fast_d_at(self, ago):
        """Calculate fast %D at a relative bar offset."""
        values = [self._calc_k_at(ago - i) for i in range(self.p.period_dfast)]
        return self._mean_or_nan(values)


class StochasticFast(_StochasticBase):
    """
    By Dr. George Lane in the 50s. It compares a closing price to the price
    range and tries to show convergence if the closing prices are close to the
    extremes

      - It will go up if closing prices are close to the highs
      - It will roughly go down if closing prices are close to the lows

    It shows divergence if the extremes keep on growing, but closing prices
    do not in the same manner (distance to the extremes grows)

    Formula:
      - hh = highest(data.high, period)
      - ll = lowest(data.low, period)
      - knum = data.close - ll
      - kden = hh - ll
      - k = 100 * (knum / kden)
      - d = MovingAverage(k, period_dfast)

    See:
      - http://en.wikipedia.org/wiki/Stochastic_oscillator
    """

    def __init__(self):
        """Initialize the Fast Stochastic indicator.

        Extends base class for fast stochastic calculation.
        """
        super().__init__()
        self.lines.percK = self.k
        self.lines.percD = self.d

    def next(self):
        """Calculate Fast Stochastic for the current bar.

        %K = 100 * (close - lowest) / (highest - lowest)
        %D = SMA(%K, period_dfast)
        """
        pass

    def once(self, start, end):
        """Calculate Fast Stochastic in runonce mode.

        Computes %K and %D values across all bars.
        """
        pass


class Stochastic(_StochasticBase):
    """
    The regular (or slow version) adds an additional moving average layer and
    thus:

      - The percD line of the StochasticFast becomes the percK line
      - percD becomes a moving average of period_dslow of the original percD

    Formula:
      - k = k
      - d = d
      - d = MovingAverage(d, period_dslow)

    See:
      - http://en.wikipedia.org/wiki/Stochastic_oscillator
    """

    alias = ("StochasticSlow",)
    params = (("period_dslow", 3),)

    def _plotlabel(self):
        plabels = [self.p.period, self.p.period_dfast, self.p.period_dslow]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self):
        """Initialize the Slow Stochastic indicator.

        Sets up tracking for fast %D values which become slow %K.
        """
        super().__init__()
        self.lines.percK = self.d
        self.lines.percD = self.p.movav(self.lines.percK, period=self.p.period_dslow)

    def next(self):
        """Calculate Slow Stochastic for the current bar.

        Fast %D becomes Slow %K, then Slow %D is SMA of Slow %K.
        """
        pass

    def once(self, start, end):
        """Calculate Slow Stochastic in runonce mode.

        Computes slow %K and %D values across all bars.
        """
        pass


class StochasticFull(_StochasticBase):
    """
    This version displays the 3 possible lines:

      - percK
      - percD
      - percSlow

    Formula:
      - k = d
      - d = MovingAverage(k, period_dslow)
      - dslow =

    See:
      - http://en.wikipedia.org/wiki/Stochastic_oscillator
    """

    lines = ("percDSlow",)
    params = (("period_dslow", 3),)

    plotlines = dict(percDSlow=dict(_name="%DSlow"))

    def _plotlabel(self):
        plabels = [self.p.period, self.p.period_dfast, self.p.period_dslow]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self):
        """Initialize the Full Stochastic indicator.

        Extends base class with additional %DSlow line.
        """
        super().__init__()
        self.lines.percK = self.k
        self.lines.percD = self.d
        self.lines.percDSlow = self.p.movav(self.lines.percD, period=self.p.period_dslow)

    def next(self):
        """Calculate Full Stochastic for the current bar.

        %K = raw stochastic value
        %D = SMA(%K, period_dfast)
        %DSlow = SMA(%D, period_dslow)
        """
        pass

    def once(self, start, end):
        """Calculate Full Stochastic in runonce mode.

        Computes %K, %D, and %DSlow values across all bars.
        """
        pass
