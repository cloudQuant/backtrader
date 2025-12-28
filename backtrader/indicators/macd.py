#!/usr/bin/env python
from . import Indicator, MovAv


# macd相关的指标
class MACD(Indicator):
    """
    Moving Average Convergence Divergence. Defined by Gerald Appel in the 70s.

    It measures the distance of a short and a long term moving average to
    try to identify the trend.

    A second lagging moving average over the convergence-divergence should
    provide a "signal" upon being crossed by the macd

    Formula:
      - macd = ema(data, me1_period) - ema(data, me2_period)
      - signal = ema(macd, signal_period)

    See:
      - http://en.wikipedia.org/wiki/MACD
    """

    lines = (
        "macd",
        "signal",
    )
    params = (
        ("period_me1", 12),
        ("period_me2", 26),
        ("period_signal", 9),
        ("movav", MovAv.Exponential),
    )

    plotinfo = dict(plothlines=[0.0])
    plotlines = dict(signal=dict(ls="--"))

    def _plotlabel(self):
        plabels = super()._plotlabel()
        if self.p.isdefault("movav"):
            plabels.remove(self.p.movav)
        return plabels

    def __init__(self):
        super().__init__()
        me1 = self.p.movav(self.data, period=self.p.period_me1)
        me2 = self.p.movav(self.data, period=self.p.period_me2)
        self.lines.macd = me1 - me2
        signal_ema = self.p.movav(self.lines.macd, period=self.p.period_signal)
        self.lines.signal = signal_ema
        
        # CRITICAL FIX: Calculate correct minperiod for MACD
        # The signal line requires max(me1, me2) + signal_period - 1 bars
        # macd_minperiod = max(period_me1, period_me2)
        # signal_minperiod = macd_minperiod + period_signal - 1
        signal_minperiod = max(self.p.period_me1, self.p.period_me2) + self.p.period_signal - 1
        self._minperiod = max(self._minperiod, signal_minperiod)
        # Also update the signal line's minperiod
        if hasattr(self.lines.signal, 'updateminperiod'):
            self.lines.signal.updateminperiod(signal_minperiod)


class MACDHisto(MACD):
    """
    Subclass of MACD which adds a "histogram" of the difference between the
    macd and signal lines

    Formula:
      - histo = macd - signal

    See:
      - http://en.wikipedia.org/wiki/MACD
    """

    alias = ("MACDHistogram",)

    lines = ("histo",)
    plotlines = dict(histo=dict(_method="bar", alpha=0.50, width=1.0))

    def __init__(self):
        super().__init__()
        self.lines.histo = self.lines.macd - self.lines.signal
