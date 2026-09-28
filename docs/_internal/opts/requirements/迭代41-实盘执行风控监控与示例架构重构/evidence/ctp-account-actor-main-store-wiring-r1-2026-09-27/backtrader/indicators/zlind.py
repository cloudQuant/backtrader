#!/usr/bin/env python
"""Zero Lag Indicator Module - Zero-lag error correction.

This module provides the ZeroLagIndicator developed by John Ehlers
and Ric Way to reduce lag in moving averages.

Classes:
    ZeroLagIndicator: Zero-lag indicator with error correction.

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.zlind = bt.indicators.ZeroLagIndicator(self.data.close, period=20, gainlimit=50)

        def next(self):
            # Price above ZeroLagIndicator indicates uptrend
            if self.data.close[0] > self.zlind[0]:
                self.buy()
            # Price below ZeroLagIndicator indicates downtrend
            elif self.data.close[0] < self.zlind[0]:
                self.sell()
"""

from backtrader.utils.py3 import MAXINT

from . import MovingAverageBase
from .ema import EMA


class ZeroLagIndicator(MovingAverageBase):
    """By John Ehlers and Ric Way

    The zero-lag indicator (ZLIndicator) is a variation of the EMA
    which modifies the EMA by trying to minimize the error (distance price -
    error correction) and thus reduce the lag

    Formula:
      - EMA(data, period)

      - For each iteration calculate a best-error-correction of the ema (see
        the paper and/or the code) iterating over ``-bestgain`` ->
        ``+bestgain`` for the error correction factor (both incl.)

      - The default moving average is EMA, but can be changed with the
        parameter ``_movav``

        ::note:: the passed moving average must calculate alpha (and 1 -
                  alpha) and make them available as attributes ``alpha`` and
                  ``alpha1`` in the instance

    See also:
      - http://www.mesasoftware.com/papers/ZeroLag.pdf

    """

    alias = (
        "ZLIndicator",
        "ZLInd",
        "EC",
        "ErrorCorrecting",
    )
    lines = ("ec",)
    params = (
        ("gainlimit", 50),
        ("_movav", EMA),
    )

    def _plotlabel(self):
        plabels = [self.p.period, self.p.gainlimit]
        plabels += [self.p._movav] * self.p.notdefault("_movav")
        return plabels

    def __init__(self):
        """Initialize the Zero Lag Indicator.

        Creates EMA and sets up gain limits for error correction.
        """
        self.ema = self.p._movav(period=self.p.period)
        self.limits = [-self.p.gainlimit, self.p.gainlimit + 1]

        # To make mixins work - super at the end for cooperative inheritance
        super().__init__()

    def next(self):
        """Calculate zero lag indicator for the current bar.

        Iterates over gain values to find the error correction that
        minimizes the difference between price and corrected EMA.
        """
        leasterror = MAXINT  # 1000000 in original code
        bestec = ema = self.ema[0]  # seed value 1st time for ec
        price = self.data[0]
        ec1 = self.lines.ec[-1]
        alpha, alpha1 = self.ema.alpha, self.ema.alpha1

        for value1 in range(*self.limits):
            gain = value1 / 10
            ec = alpha * (ema + gain * (price - ec1)) + alpha1 * ec1
            error = abs(price - ec)
            if error < leasterror:
                leasterror = error
                bestec = ec

        self.lines.ec[0] = bestec
