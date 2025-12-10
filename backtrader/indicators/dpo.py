#!/usr/bin/env python
from . import Indicator, MovAv


# 去除趋势后的价格波动
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
        # Create the Moving Average
        ma = self.p.movav(self.data, period=self.p.period)

        # Calculate value (look back period/2 + 1 in MA) and bind to 'dpo' line
        self.lines.dpo = self.data - ma(-self.p.period // 2 + 1)

        super().__init__()
