#!/usr/bin/env python
from . import Indicator, MovAv, StdDev


# 布林带指标
class BollingerBands(Indicator):
    """
    Defined by John Bollinger in the 80s. It measures volatility by defining
    upper and lower bands at distance x standard deviations

    Formula:
      - midband = SimpleMovingAverage(close, period)
      - topband = midband + devfactor * StandardDeviation(data, period)
      - botband = midband - devfactor * StandardDeviation(data, period)

    See:
      - http://en.wikipedia.org/wiki/Bollinger_Bands
    """

    alias = ("BBands",)

    lines = (
        "mid",
        "top",
        "bot",
    )
    params = (
        ("period", 20),
        ("devfactor", 2.0),
        ("movav", MovAv.Simple),
    )

    plotinfo = dict(subplot=False)
    plotlines = dict(
        mid=dict(ls="--"),
        top=dict(_samecolor=True),
        bot=dict(_samecolor=True),
    )

    def _plotlabel(self):
        plabels = [self.p.period, self.p.devfactor]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self):
        self.lines.mid = ma = self.p.movav(self.data, period=self.p.period)
        stddev = self.p.devfactor * StdDev(self.data, ma, period=self.p.period, movav=self.p.movav)
        self.lines.top = ma + stddev
        self.lines.bot = ma - stddev

        super().__init__()


# 布林带百分比指标
class BollingerBandsPct(BollingerBands):
    """
    Extends the Bollinger Bands with a Percentage line
    """

    lines = ("pctb",)
    plotlines = dict(pctb=dict(_name="%B"))  # display the line as %B on chart

    def __init__(self):
        super().__init__()
        self.l.pctb = (self.data - self.l.bot) / (self.l.top - self.l.bot)
