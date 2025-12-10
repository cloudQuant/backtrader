#!/usr/bin/env python
from . import SumN, TrueLow, TrueRange, Indicator


# 最终震荡指标
class UltimateOscillator(Indicator):
    """
    Formula:
      # Buying Pressure = Close - TrueLow
      BP = Close - Minimum (Low or Prior Close)

      # TrueRange = TrueHigh - TrueLow
      TR = Maximum (High or Prior Close) - Minimum (Low or Prior Close)

      Average7 = (7-period BP Sum) / (7-period TR Sum)
      Average14 = (14-period BP Sum) / (14-period TR Sum)
      Average28 = (28-period BP Sum) / (28-period TR Sum)

      UO = 100 x [(4 x Average7)+(2 x Average14)+Average28]/(4+2+1)

    See:

      - https://en.wikipedia.org/wiki/Ultimate_oscillator
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:ultimate_oscillator
    """

    lines = ("uo",)

    params = (
        ("p1", 7),
        ("p2", 14),
        ("p3", 28),
        ("upperband", 70.0),
        ("lowerband", 30.0),
    )

    def _plotinit(self):
        baseticks = [10.0, 50.0, 90.0]
        hlines = [self.p.upperband, self.p.lowerband]

        # Plot lines at 0 & 100 to make the scale complete + upper/lower/bands
        self.plotinfo.plotyhlines = hlines
        # Plot ticks at "baseticks" + the user specified upper/lower bands
        self.plotinfo.plotyticks = baseticks + hlines

    def __init__(self):
        bp = self.data.close - TrueLow(self.data)
        tr = TrueRange(self.data)

        av7 = SumN(bp, period=self.p.p1) / SumN(tr, period=self.p.p1)
        av14 = SumN(bp, period=self.p.p2) / SumN(tr, period=self.p.p2)
        av28 = SumN(bp, period=self.p.p3) / SumN(tr, period=self.p.p3)

        # Multiply/divide floats outside of formula to reduce line objects
        factor = 100.0 / (4.0 + 2.0 + 1.0)
        uo = (4.0 * factor) * av7 + (2.0 * factor) * av14 + factor * av28
        self.lines.uo = uo

        super().__init__()
