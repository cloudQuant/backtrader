#!/usr/bin/env python
"""Spread Indicator Module - two-leg spread and its rolling z-score.

Classes:
    SpreadZScore: spread of two data feeds plus rolling mean and z-score.

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.z = bt.indicators.SpreadZScore(self.data0, self.data1, period=60)

        def next(self):
            if self.z.l.zscore[0] > 2.0:
                self.sell(data=self.data0)
                self.buy(data=self.data1)

Note:
    When the spread is perfectly stable the standard deviation is zero and the
    z-score is undefined (NaN under floating-point division). Consumers should
    treat NaN as "no deviation from the mean", not as a signal.
"""

from ..functions import Max
from . import Indicator, MovAv
from .deviation import StandardDeviation


class SpreadZScore(Indicator):
    """Rolling z-score of ``data0.close - data1.close``.

    Formula:
      - spread = data0.close - data1.close
      - mean = MovingAverage(spread, period)
      - zscore = (spread - mean) / StdDev(spread, period)

    The denominator is floored at a tiny epsilon: a perfectly stable spread
    yields ``spread == mean`` and therefore a z-score of exactly 0.0 (no
    deviation from the mean) instead of a division-by-zero crash.
    """

    lines = ("spread", "mean", "zscore")
    params = (("period", 60), ("movav", MovAv.Simple))

    plotinfo = dict(subplot=True)  # noqa: C408

    def __init__(self):
        """Compose the spread, its rolling mean and z-score."""
        super().__init__()
        spread = self.data0.close - self.data1.close
        mean = self.p.movav(spread, period=self.p.period)
        std = StandardDeviation(spread, period=self.p.period, movav=self.p.movav)
        self.lines.spread = spread
        self.lines.mean = mean
        self.lines.zscore = (spread - mean) / Max(std, 1e-12)
