#!/usr/bin/env python
"""Aroon Indicator Module - Aroon trend indicator.

This module provides the Aroon indicator developed by Tushar Chande in 1995
to identify trend strength and direction.

Classes:
    _AroonBase: Base class for Aroon indicators.
    AroonUp: Aroon Up component.
    AroonDown: Aroon Down component.
    AroonUpDown: Combined Aroon Up and Down (alias: AroonIndicator).
    AroonOscillator: Aroon Oscillator (alias: AroonOsc).
    AroonUpDownOscillator: Combined AroonUpDown and Oscillator (alias: AroonUpDownOsc).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.aroon = bt.indicators.AroonUpDown(self.data, period=14)

        def next(self):
            if self.aroon.aroonup[0] > self.aroon.aroondown[0]:
                self.buy()
            elif self.aroon.aroonup[0] < self.aroon.aroondown[0]:
                self.sell()
"""

from . import FindFirstIndexHighest, FindFirstIndexLowest, Indicator


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
    plotinfo = {"plotymargin": 0.05, "plotyhlines": [0, 100]}

    def _plotlabel(self):
        plabels = [self.p.period]
        return plabels

    def _plotinit(self):
        self.plotinfo.plotyhlines += [self.p.lowerband, self.p.upperband]

    def __init__(self):
        """Initialize the Aroon base indicator.

        Sets up Aroon Up/Down calculations based on _up and _down flags.
        """
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

    @staticmethod
    def _index_since_extreme(source, index, period, highest):
        """Return bars since the most recent extreme in the period+1 window."""
        extreme = source[index]
        bars_ago = 0

        for offset in range(1, period + 1):
            value = source[index - offset]
            is_more_extreme = value > extreme if highest else value < extreme
            if is_more_extreme:
                extreme = value
                bars_ago = offset

        return bars_ago

    @classmethod
    def _once_line(cls, source, destination, start, end, period, highest):
        """Calculate one Aroon component directly from its source line array."""
        while len(destination) < end:
            destination.append(float("nan"))

        for index in range(start, end):
            if index < period or index >= len(source):
                destination[index] = float("nan")
                continue

            bars_ago = cls._index_since_extreme(source, index, period, highest)
            destination[index] = 100.0 * (period - bars_ago) / period


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
        """Initialize the Aroon Up indicator.

        Calculates Aroon Up values using parent class logic.
        """
        super().__init__()

    def next(self):
        """Calculate Aroon Up for the current bar.

        Copies the up value from the parent calculation.
        """
        self.lines.aroonup[0] = self.up[0]

    def once(self, start, end):
        """Calculate Aroon Up in runonce mode.

        Computes each value from the source highs for the complete lookback.
        """
        self._once_line(
            self.data.high.array,
            self.lines.aroonup.array,
            start,
            end,
            self.p.period,
            highest=True,
        )


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
        """Initialize the Aroon Down indicator.

        Calculates Aroon Down values using parent class logic.
        """
        super().__init__()

    def next(self):
        """Calculate Aroon Down for the current bar.

        Copies the down value from the parent calculation.
        """
        self.lines.aroondown[0] = self.down[0]

    def once(self, start, end):
        """Calculate Aroon Down in runonce mode.

        Computes each value from the source lows for the complete lookback.
        """
        self._once_line(
            self.data.low.array,
            self.lines.aroondown.array,
            start,
            end,
            self.p.period,
            highest=False,
        )


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

    def next(self):
        """Calculate each Aroon component exposed by the combined indicator."""
        AroonUp.next(self)
        if "aroondown" in self.lines.getlinealiases():
            self.lines.aroondown[0] = self.down[0]

    def once(self, start, end):
        """Calculate each Aroon component exposed in runonce mode."""
        AroonUp.once(self, start, end)
        if "aroondown" in self.lines.getlinealiases():
            AroonDown.once(self, start, end)


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
        """Initialize the Aroon Oscillator indicator.

        Calculates both up and down values for oscillator calculation.
        """
        super().__init__()

    def next(self):
        """Calculate Aroon Oscillator for the current bar.

        Oscillator = Aroon Up - Aroon Down.
        """
        self.lines.aroonosc[0] = self.up[0] - self.down[0]

    def once(self, start, end):
        """Calculate Aroon Oscillator in runonce mode.

        Computes both components from their source arrays and subtracts them.
        """
        high_array = self.data.high.array
        low_array = self.data.low.array
        aroonosc_array = self.lines.aroonosc.array

        while len(aroonosc_array) < end:
            aroonosc_array.append(float("nan"))

        period = self.p.period
        for index in range(start, end):
            if index < period or index >= len(high_array) or index >= len(low_array):
                aroonosc_array[index] = float("nan")
                continue

            up_bars_ago = self._index_since_extreme(
                high_array, index, period, highest=True
            )
            down_bars_ago = self._index_since_extreme(
                low_array, index, period, highest=False
            )
            up_value = 100.0 * (period - up_bars_ago) / period
            down_value = 100.0 * (period - down_bars_ago) / period
            aroonosc_array[index] = up_value - down_value


class AroonUpDownOscillator(AroonUpDown, AroonOscillator):
    """
    Presents together the indicators AroonUpDown and AroonOsc

    Formula:
      (None uses the aforementioned indicators)

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:aroon
    """

    alias = ("AroonUpDownOsc",)

    def next(self):
        """Calculate all Aroon outputs currently exposed by the combined class."""
        AroonUpDown.next(self)
        if "aroonosc" in self.lines.getlinealiases():
            self.lines.aroonosc[0] = self.up[0] - self.down[0]

    def once(self, start, end):
        """Calculate all Aroon outputs currently exposed in runonce mode."""
        AroonUpDown.once(self, start, end)
        if "aroonosc" in self.lines.getlinealiases():
            AroonOscillator.once(self, start, end)
