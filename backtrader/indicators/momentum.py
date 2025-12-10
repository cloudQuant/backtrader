#!/usr/bin/env python
from . import Indicator


# 动量指标，动量震荡指标，ROC指标，ROC指标乘以100
class Momentum(Indicator):
    """
    Measures the change in price by calculating the difference between the
    current price and the price from a given period ago


    Formula:
      - momentum = data - data_period

    See:
      - http://en.wikipedia.org/wiki/Momentum_(technical_analysis)
    """

    lines = ("momentum",)
    params = (("period", 12),)
    plotinfo = dict(plothlines=[0.0])

    def __init__(self):
        self.l.momentum = self.data - self.data(-self.p.period)
        super().__init__()


class MomentumOscillator(Indicator):
    """
    Measures the ratio of change in prices over a period

    Formula:
      - mosc = 100 * (data / data_period)

    See:
      - http://ta.mql4.com/indicators/oscillators/momentum
    """

    alias = ("MomentumOsc",)

    # Named output lines
    lines = ("momosc",)

    # Accepted parameters (and defaults)
    params = (("period", 12), ("band", 100.0))

    def _plotlabel(self):
        plabels = [self.p.period]
        return plabels

    def _plotinit(self):
        self.plotinfo.plothlines = [self.p.band]

    def __init__(self):
        self.l.momosc = 100.0 * (self.data / self.data(-self.p.period))
        super().__init__()


class RateOfChange(Indicator):
    """
    Measures the ratio of change in prices over a period

    Formula:
      - roc = (data - data_period) / data_period

    See:
      - http://en.wikipedia.org/wiki/Momentum_(technical_analysis)
    """

    alias = ("ROC",)

    # Named output lines
    lines = ("roc",)

    # Accepted parameters (and defaults)
    params = (("period", 12),)

    def __init__(self):
        dperiod = self.data(-self.p.period)
        self.l.roc = (self.data - dperiod) / dperiod
        super().__init__()


class RateOfChange100(Indicator):
    """
    Measures the ratio of change in prices over a period with base 100

    This is, for example, how ROC is defined in stockcharts

    Formula:
      - roc = 100 * (data - data_period) / data_period

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:rate_of_change_roc_and_momentum

    """

    alias = ("ROC100",)

    # Named output lines
    lines = ("roc100",)

    # Accepted parameters (and defaults)
    params = (("period", 12),)

    def __init__(self):
        # CRITICAL FIX: Call super().__init__() first to ensure self.data is set
        super().__init__()
        self.l.roc100 = 100.0 * ROC(self.data, period=self.p.period)


ROC = RateOfChange
ROC100 = RateOfChange100
