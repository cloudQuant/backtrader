#!/usr/bin/env python
"""RSI Indicator Module - Relative Strength Index.

This module provides the RSI (Relative Strength Index) indicator
developed by J. Welles Wilder, Jr.

Classes:
    RSI: RSI indicator.
    UpDay/DownDay: Helper classes for RSI calculation.

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.rsi = bt.indicators.RSI(self.data.close, period=14)

        def next(self):
            # RSI above 70 indicates overbought
            if self.rsi.rsi[0] > 70:
                self.sell()
            # RSI below 30 indicates oversold
            elif self.rsi.rsi[0] < 30:
                self.buy()
"""
import math

from . import Indicator, MovAv


# Calculate RSI indicator
class UpDay(Indicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"* for the RSI

    Records days which have been "up", i.e.: the close price has been
    higher than the day before.

    Formula:
      - upday = max (close - close_prev, 0)

    See:
      - http://en.wikipedia.org/wiki/Relative_strength_index
    """

    lines = ("upday",)
    params = (("period", 1),)

    def __init__(self):
        """Initialize the UpDay indicator.

        Sets minimum period for up day calculation.
        """
        super().__init__()
        self.addminperiod(self.p.period + 1)

    def next(self):
        """Calculate up day value for the current bar.

        Returns max(close - close_period_ago, 0).
        """
        diff = self.data[0] - self.data[-self.p.period]
        self.lines.upday[0] = max(diff, 0.0)

    def once(self, start, end):
        """Calculate up day values in runonce mode.

        Returns max(price_change, 0) for each bar.
        """
        darray = self.data.array
        larray = self.lines.upday.array
        period = self.p.period

        while len(larray) < end:
            larray.append(0.0)

        for i in range(period, min(end, len(darray))):
            diff = darray[i] - darray[i - period]
            larray[i] = max(diff, 0.0)


class DownDay(Indicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"* for the RSI

    Records days which have been "down", i.e.: the close price has been
    lower than the day before.

    Formula:
      - downday = max(close_prev - close, 0)

    See:
      - http://en.wikipedia.org/wiki/Relative_strength_index
    """

    lines = ("downday",)
    params = (("period", 1),)

    def __init__(self):
        """Initialize the DownDay indicator.

        Sets minimum period for down day calculation.
        """
        super().__init__()
        self.addminperiod(self.p.period + 1)

    def next(self):
        """Calculate down day value for the current bar.

        Returns max(close_period_ago - close, 0).
        """
        diff = self.data[-self.p.period] - self.data[0]
        self.lines.downday[0] = max(diff, 0.0)

    def once(self, start, end):
        """Calculate down day values in runonce mode.

        Returns max(-price_change, 0) for each bar.
        """
        darray = self.data.array
        larray = self.lines.downday.array
        period = self.p.period

        while len(larray) < end:
            larray.append(0.0)

        for i in range(period, min(end, len(darray))):
            diff = darray[i - period] - darray[i]
            larray[i] = max(diff, 0.0)


class UpDayBool(Indicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"* for the RSI

    Records days which have been "up", i.e.: the close price has been
    higher than the day before.

    Note:
      - This version returns a bool rather than the difference

    Formula:
      - upday = close > close_prev

    See:
      - http://en.wikipedia.org/wiki/Relative_strength_index
    """

    lines = ("upday",)
    params = (("period", 1),)

    def __init__(self):
        """Initialize the UpDay Bool indicator.

        Sets minimum period for boolean up day calculation.
        """
        super().__init__()
        self.addminperiod(self.p.period + 1)

    def next(self):
        """Check if current bar is an up day.

        Returns 1.0 if close > close_period_ago, 0.0 otherwise.
        """
        self.lines.upday[0] = 1.0 if self.data[0] > self.data[-self.p.period] else 0.0

    def once(self, start, end):
        """Check for up days in runonce mode.

        Returns 1.0 where price increased, 0.0 otherwise.
        """
        darray = self.data.array
        larray = self.lines.upday.array
        period = self.p.period

        while len(larray) < end:
            larray.append(0.0)

        for i in range(period, min(end, len(darray))):
            larray[i] = 1.0 if darray[i] > darray[i - period] else 0.0


class DownDayBool(Indicator):
    """
    Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"* for the RSI

    Records days which have been "down", i.e.: the close price has been
    lower than the day before.

    Note:
      - This version returns a bool rather than the difference

    Formula:
      - downday = close_prev > close

    See:
      - http://en.wikipedia.org/wiki/Relative_strength_index
    """

    lines = ("downday",)
    params = (("period", 1),)

    def __init__(self):
        """Initialize the DownDay Bool indicator.

        Sets minimum period for boolean down day calculation.
        """
        super().__init__()
        self.addminperiod(self.p.period + 1)

    def next(self):
        """Check if current bar is a down day.

        Returns 1.0 if close_period_ago > close, 0.0 otherwise.
        """
        self.lines.downday[0] = 1.0 if self.data[-self.p.period] > self.data[0] else 0.0

    def once(self, start, end):
        """Check for down days in runonce mode.

        Returns 1.0 where price decreased, 0.0 otherwise.
        """
        darray = self.data.array
        larray = self.lines.downday.array
        period = self.p.period

        while len(larray) < end:
            larray.append(0.0)

        for i in range(period, min(end, len(darray))):
            larray[i] = 1.0 if darray[i - period] > darray[i] else 0.0


class RelativeStrengthIndex(Indicator):
    """Defined by J. Welles Wilder, Jr. in 1978 in his book *"New Concepts in
    Technical Trading Systems"*.

    It measures momentum by calculating the ration of higher closes and
    lower closes after having been smoothed by an average, normalizing
    the result between 0 and 100

    Formula:
      - up = upday(data)
      - down = downday(data)
      - maup = movingaverage(up, period)
      - madown = movingaverage(down, period)
      - rs = maup / madown
      - rsi = 100 - 100 / (1 + rs)

    The moving average used is the one originally defined by Wilder,
    the SmoothedMovingAverage

    See:
      - http://en.wikipedia.org/wiki/Relative_strength_index

    Notes:
      - ``safediv`` (default: False) If this parameter is True, the division
        rs = maup / madown will be checked for the special cases in which a
        ``0 / 0`` or ``x / 0`` division will happen

      - ``safehigh`` (default: 100.0) will be used as RSI value for the
        ``x / 0`` case

      - ``safelow`` (default: 50.0) will be used as RSI value for the
        ``0 / 0`` case
    """

    alias = (
        "RSI",
        "RSI_SMMA",
        "RSI_Wilder",
    )

    lines = ("rsi",)
    params = (
        ("period", 14),
        ("movav", MovAv.Smoothed),
        ("upperband", 70.0),
        ("lowerband", 30.0),
        ("safediv", False),
        ("safehigh", 100.0),
        ("safelow", 50.0),
        ("lookback", 1),
    )

    def _plotlabel(self):
        plabels = [self.p.period]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        plabels += [self.p.lookback] * self.p.notdefault("lookback")
        return plabels

    def _plotinit(self):
        self.plotinfo.plotyhlines = [self.p.upperband, self.p.lowerband]

    def __init__(self):
        """Initialize the RSI indicator.

        Creates up/down day indicators and their moving averages.
        """
        super().__init__()
        self.upday = UpDay(self.data, period=self.p.lookback)
        self.downday = DownDay(self.data, period=self.p.lookback)
        self.maup = self.p.movav(self.upday, period=self.p.period)
        self.madown = self.p.movav(self.downday, period=self.p.period)

    def _rscalc(self, rsi):
        """Calculate relative strength from RSI value."""
        try:
            rs = (-100.0 / (rsi - 100.0)) - 1.0
        except ZeroDivisionError:
            return float("inf")
        return rs

    def _calc_rsi(self, maup_val, madown_val):
        """Calculate RSI from maup and madown values.

        Args:
            maup_val: Moving average of up days.
            madown_val: Moving average of down days.

        Returns:
            RSI value between 0 and 100.
        """
        if self.p.safediv:
            if madown_val == 0.0:
                if maup_val == 0.0:
                    return self.p.safelow  # 0/0 case
                else:
                    return self.p.safehigh  # x/0 case

        if madown_val == 0.0:
            return 100.0  # Avoid division by zero

        rs = maup_val / madown_val
        return 100.0 - 100.0 / (1.0 + rs)

    def next(self):
        """Calculate RSI for the current bar.

        RSI = 100 - 100 / (1 + maup/madown)
        """
        self.lines.rsi[0] = self._calc_rsi(self.maup[0], self.madown[0])

    def once(self, start, end):
        """Calculate RSI in runonce mode.

        Computes RSI values across all bars with safe division handling.
        """
        maup_array = self.maup.lines[0].array
        madown_array = self.madown.lines[0].array
        larray = self.lines.rsi.array
        safediv = self.p.safediv
        safehigh = self.p.safehigh
        safelow = self.p.safelow

        while len(larray) < end:
            larray.append(0.0)

        for i in range(start, min(end, len(maup_array), len(madown_array))):
            maup_val = maup_array[i] if i < len(maup_array) else 0.0
            madown_val = madown_array[i] if i < len(madown_array) else 0.0

            if isinstance(maup_val, float) and math.isnan(maup_val):
                larray[i] = float("nan")
            elif isinstance(madown_val, float) and math.isnan(madown_val):
                larray[i] = float("nan")
            else:
                if safediv:
                    if madown_val == 0.0:
                        if maup_val == 0.0:
                            larray[i] = safelow
                        else:
                            larray[i] = safehigh
                        continue

                if madown_val == 0.0:
                    larray[i] = 100.0
                else:
                    rs = maup_val / madown_val
                    larray[i] = 100.0 - 100.0 / (1.0 + rs)


RSI = RelativeStrengthIndex


class RSI_Safe(RSI):
    """
    Subclass of RSI which changes parameers ``safediv`` to ``True`` as the
    default value

    See:
      - http://en.wikipedia.org/wiki/Relative_strength_index
    """

    params = (("safediv", True),)


class RSI_SMA(RSI):
    """
    Uses a SimpleMovingAverage as described in Wikipedia and other soures

    See:
      - http://en.wikipedia.org/wiki/Relative_strength_index
    """

    alias = ("RSI_Cutler",)

    params = (("movav", MovAv.Simple),)


class RSI_EMA(RSI):
    """
    Uses an ExponentialMovingAverage as described in Wikipedia

    See:
      - http://en.wikipedia.org/wiki/Relative_strength_index
    """

    params = (("movav", MovAv.Exponential),)
