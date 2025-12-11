#!/usr/bin/env python
from . import ExponentialSmoothing, MovingAverageBase


# 指数移动平均线
class ExponentialMovingAverage(MovingAverageBase):
    """
    A Moving Average that smoothes data exponentially over time.

    It is a subclass of SmoothingMovingAverage.

      - self.smfactor -> 2 / (1 + period)
      - self.smfactor1 -> `1 - self.smfactor`

    Formula:
      - movav = prev * (1.0 - smoothfactor) + newdata * smoothfactor

    See also:
      - http://en.wikipedia.org/wiki/Moving_average#Exponential_moving_average
    """

    alias = (
        "EMA",
        "MovingAverageExponential",
    )
    lines = ("ema",)

    def __init__(self):
        # CRITICAL FIX: Call super().__init__() first to ensure self.data is set
        super().__init__()

        # Now we can safely use self.data
        # Create ExponentialSmoothing indicator
        es = ExponentialSmoothing(
            self.data, period=self.p.period, alpha=2.0 / (1.0 + self.p.period)
        )

        # CRITICAL FIX: Add ExponentialSmoothing as a sub-indicator so it gets processed
        # This ensures its once() method is called in runonce mode
        from ..lineiterator import LineIterator

        if hasattr(self, "_lineiterators"):
            self._lineiterators[LineIterator.IndType].append(es)
            es._owner = self

        # Set lines[0] to the ExponentialSmoothing indicator
        self.lines[0] = es
        self.alpha, self.alpha1 = es.alpha, es.alpha1


EMA = ExponentialMovingAverage
