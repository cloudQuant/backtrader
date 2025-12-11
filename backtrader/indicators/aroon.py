#!/usr/bin/env python
from . import FindFirstIndexHighest, FindFirstIndexLowest, Indicator


# 这个文件是设计了几个计算AROON相关指标的类
class _AroonBase(Indicator):
    """
    Base class which does the calculation of the AroonUp/AroonDown values and
    defines the common parameters.

    It uses the class attributes _up and _down (boolean flags) to decide which
    value has to be calculated.

    Values are not assigned to lines but rather stored in the "up" and "down"
    instance variables, which can be used by subclasses to for assignment or
    further calculations
    """

    _up = False
    _down = False

    params = (
        ("period", 14),
        ("upperband", 70),
        ("lowerband", 30),
    )
    plotinfo = dict(plotymargin=0.05, plotyhlines=[0, 100])

    def _plotlabel(self):
        plabels = [self.p.period]
        return plabels

    def _plotinit(self):
        self.plotinfo.plotyhlines += [self.p.lowerband, self.p.upperband]

    def __init__(self):
        # Look backwards period + 1 for current data because the formula mus
        # produce values between 0 and 100 and can only do that if the
        # calculated hhidx/llidx go from 0 to period (hence period + 1 values)
        idxperiod = self.p.period + 1

        if self._up:
            hhidx = FindFirstIndexHighest(self.data.high, period=idxperiod)
            self.up = (100.0 / self.p.period) * (self.p.period - hhidx)

        if self._down:
            llidx = FindFirstIndexLowest(self.data.low, period=idxperiod)
            self.down = (100.0 / self.p.period) * (self.p.period - llidx)

        super().__init__()


class AroonUp(_AroonBase):
    """
    This is the AroonUp from the indicator AroonUpDown developed by Tushar
    Chande in 1995.

    Formula:
      - up = 100 * (period - distance to the highest high) / period

    Note:
      The lines oscillate between 0 and 100. That means that the "distance" to
      the last highest or lowest must go from 0 to period so that the formula
      can yield 0 and 100.

      Hence, the lookback period is period + 1, because the current bar is also
      taken into account.
      And therefore, this indicator needs an effective
      lookback period of period + 1.

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:aroon
    """

    _up = True

    lines = ("aroonup",)

    def __init__(self):
        super().__init__()

        self.lines.aroonup = self.up


class AroonDown(_AroonBase):
    """
    This is the AroonDown from the indicator AroonUpDown developed by Tushar
    Chande in 1995.

    Formula:
      - down = 100 * (period - distance to the lowest low) / period

    Note:
      The lines oscillate between 0 and 100. That means that the "distance" to
      the last highest or lowest must go from 0 to period so that the formula
      can yield 0 and 100.

      Hence, the lookback period is period + 1, because the current bar is also
      taken into account.
      And therefore, this indicator needs an effective
      lookback period of period + 1.

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:aroon
    """

    _down = True

    lines = ("aroondown",)

    def __init__(self):
        super().__init__()

        self.lines.aroondown = self.down


class AroonUpDown(AroonUp, AroonDown):
    """
    Developed by Tushar Chande in 1995.

    It tries to determine if a trend exists or not by calculating how far away
    within a given period the last highs/lows are (AroonUp/AroonDown)

    Formula:
      - up = 100 * (period - distance to the highest high) / period
      - down = 100 * (period - distance to the lowest low) / period

    Note:
      The lines oscillate between 0 and 100. That means that the "distance" to
      the last highest or lowest must go from 0 to period so that the formula
      can yield 0 and 100.

      Hence, the lookback period is period + 1, because the current bar is also
      taken into account.
      And therefore, this indicator needs an effective
      lookback period of period + 1.

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:aroon
    """

    alias = ("AroonIndicator",)


class AroonOscillator(_AroonBase):
    """
    It is a variation of the AroonUpDown indicator which shows the current
    difference between the AroonUp and AroonDown value, trying to present a
    visualization which indicates which is stronger (greater than 0 -> AroonUp
    and less than 0 -> AroonDown)

    Formula:
      - aroonosc = aroonup - aroondown

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:aroon
    """

    _up = True
    _down = True

    alias = ("AroonOsc",)

    lines = ("aroonosc",)

    def _plotinit(self):
        super()._plotinit()

        for yhline in self.plotinfo.plotyhlines[:]:
            self.plotinfo.plotyhlines.append(-yhline)

    def __init__(self):
        super().__init__()

        self.lines.aroonosc = self.up - self.down


class AroonUpDownOscillator(AroonUpDown, AroonOscillator):
    """
    Presents together the indicators AroonUpDown and AroonOsc

    Formula:
      (None uses the aforementioned indicators)

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:aroon
    """

    alias = ("AroonUpDownOsc",)
