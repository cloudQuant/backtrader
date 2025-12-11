#!/usr/bin/env python
from . import ExponentialSmoothingDynamic, MovingAverageBase, SumN


# 自适应均线
class AdaptiveMovingAverage(MovingAverageBase):
    """
    Defined by Perry Kaufman in his book `"Smarter Trading"`.

    It is A Moving Average with a continuously scaled smoothing factor by
    taking into account market direction and volatility. The smoothing factor
    is calculated from 2 ExponetialMovingAverage smoothing factors, a fast one
    and slow one.

    If the market trends, the value will tend to the fast ema smoothing
    period. If the market doesn't trend, it will move towards the slow EMA
    smoothing period.

    It is a subclass of SmoothingMovingAverage, overriding once to account for
    the live nature of the smoothing factor

    Formula:
      - direction = close - close_period
      - volatility = sumN(abs (close - close_n), period)
      - effiency_ratio = abs (direction / volatility)
      - fast = 2 / (fast_period + 1)
      - slow = 2 / (slow_period + 1)

      - Smfactor = squared(efficienty_ratio * (fast - slow) + slow)
      - smfactor1 = 1.0 - smfactor

      - The initial seed value is a SimpleMovingAverage

    See also:
      - http://fxcodebase.com/wiki/index.php/Kaufman's_Adaptive_Moving_Average_(KAMA)
      - http://www.metatrader5.com/en/terminal/help/analytics/indicators/trend_indicators/ama
      - http://help.cqg.com/cqgic/default.htm#!Documents/adaptivemovingaverag2.htm
    """

    alias = (
        "KAMA",
        "MovingAverageAdaptive",
    )
    lines = ("kama",)
    params = (("fast", 2), ("slow", 30))

    def __init__(self):
        # Before super to ensure mixins (right-hand side in subclassing)
        # can see the assignment operation and operate on the line
        direction = self.data - self.data(-self.p.period)
        volatility = SumN(abs(self.data - self.data(-1)), period=self.p.period)

        er = abs(direction / volatility)  # efficiency ratio

        fast = 2.0 / (self.p.fast + 1.0)  # fast ema smoothing factor
        slow = 2.0 / (self.p.slow + 1.0)  # slow ema smoothing factor

        sc = pow((er * (fast - slow)) + slow, 2)  # scalable constant

        self.lines[0] = ExponentialSmoothingDynamic(self.data, period=self.p.period, alpha=sc)

        super().__init__()
