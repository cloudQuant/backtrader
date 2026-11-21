#!/usr/bin/env python
"""Bollinger Bands Indicator Module - Volatility bands.

This module provides the Bollinger Bands indicator developed by
John Bollinger in the 1980s for measuring market volatility.

Classes:
    BollingerBands: Bollinger Bands indicator (alias: BBands).
    BollingerBandsPct: Bollinger Bands with %B line.

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.bbands = bt.indicators.BBands(self.data, period=20, devfactor=2.0)

        def next(self):
            if self.data.close[0] < self.bbands.bot[0]:
                self.buy()
            elif self.data.close[0] > self.bbands.top[0]:
                self.sell()
"""

import math

from . import Indicator, MovAv



def _population_stddev(values, period):
    """Compute a finite population spread without subtracting large squares.

    Preserve the existing non-finite fallback; finite extremes use scaled
    coordinates when subtraction, a sum, or the Euclidean norm overflows.
    """
    if not values:
        return math.sqrt(0.0 / period)
    if not all(math.isfinite(value) for value in values):
        total = squares = 0.0
        for value in values:
            total += value
            squares += value * value
        return math.sqrt(max(0.0, abs(squares / period - (total / period) ** 2)))

    origin = values[0]
    diffs = [value - origin for value in values]
    try:
        if all(math.isfinite(value) for value in diffs):
            maximum = max(abs(value) for value in diffs)
            if 0.0 < maximum < float.fromhex('0x1.0p-1022'):
                exponent = math.frexp(maximum)[1]
                small = [math.ldexp(value, -exponent) for value in diffs]
                mean = math.fsum(small) / period
                norm = math.hypot(*(value - mean for value in small)) / math.sqrt(period)
                return math.ldexp(norm, exponent)
            mean = math.fsum(diffs) / period
            centered = [value - mean for value in diffs]
            norm = math.hypot(*centered)
            if math.isfinite(norm):
                return norm / math.sqrt(period)
    except OverflowError:
        pass

    max_value = max(abs(value) for value in values)
    if max_value == 0.0:
        return 0.0
    exponent = math.frexp(max_value)[1]
    scaled = [math.ldexp(value, -exponent) for value in values]
    base = scaled[0]
    offsets = [value - base for value in scaled]
    mean = math.fsum(offsets) / period
    normalized = math.hypot(*(value - mean for value in offsets)) / math.sqrt(period)
    try:
        return math.ldexp(normalized, exponent)
    except OverflowError:
        return float("inf")

class BollingerBands(Indicator):
    """
    Defined by John Bollinger in the 80s. It measures volatility by defining
    upper and lower bands at distance x standard deviations

    Formula:
      - midband = MovingAverage(data, period)
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

    plotinfo = {"subplot": False}
    plotlines = {
        "mid": {"ls": "--"},
        "top": {"_samecolor": True},
        "bot": {"_samecolor": True},
    }

    def _plotlabel(self):
        plabels = [self.p.period, self.p.devfactor]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self):
        """Initialize the Bollinger Bands indicator.

        Creates the configured moving average for the middle band and sets the
        minimum period to the configured period.
        """
        super().__init__()
        self.midma = self.p.movav(self.data, period=self.p.period)
        self.addminperiod(self.p.period)

    def next(self):
        """Calculate Bollinger Bands for the current bar.

        Calculates mid (configured moving average), top (mid + devfactor*stddev),
        and bot (mid - devfactor*stddev) bands.
        """
        period = self.p.period
        devfactor = self.p.devfactor

        # Calculate the arithmetic mean used by the population standard deviation.
        values = [self.data[-i] for i in range(period)]
        mid = self.midma[0]
        stddev = _population_stddev(values, period)

        # Set lines
        width = devfactor * stddev
        top = mid + width
        bot = mid - width
        context = self._factor_strict_context_for_callback()
        if context is not None:
            from ..research.strict import reject_infinity

            phase = getattr(context, "phase", None) or "next"
            for value in (devfactor, stddev, width, mid, top, bot):
                reject_infinity(context, value, phase, operation=self)
        self.lines.mid[0] = mid
        self.lines.top[0] = top
        self.lines.bot[0] = bot

    def once(self, start, end):
        """Calculate Bollinger Bands in runonce mode."""
        if start >= end:
            return
        darray = self.data.array
        mid_array = self.lines.mid.array
        top_array = self.lines.top.array
        bot_array = self.lines.bot.array
        midma_array = self.midma.lines[0].array
        period = self.p.period
        devfactor = self.p.devfactor
        actual_end = min(end, len(darray), len(midma_array))
        darray_len = len(darray)

        # Ensure arrays are sized
        for arr in [mid_array, top_array, bot_array]:
            while len(arr) < end:
                arr.append(float("nan"))

        # PERFORMANCE: Cache constants and functions
        nan_val = float("nan")
        context = self._factor_strict_context_for_callback()
        if context is not None:
            from ..research.strict import reject_infinity

            phase = getattr(context, "phase", None) or "once"

        # Pre-fill warmup with NaN
        for i in range(max(0, start), min(period - 1, darray_len, end)):
            mid_array[i] = nan_val
            top_array[i] = nan_val
            bot_array[i] = nan_val

        for i in range(max(start, period - 1), actual_end):
            if context is not None:
                reject_infinity(context, devfactor, phase, operation=self)
            values = []
            has_nan = False
            for j in range(period):
                idx = i - j
                if 0 <= idx < darray_len:
                    val = darray[idx]
                    if val != val:
                        has_nan = True
                        if context is None:
                            break
                        continue
                    if context is not None:
                        reject_infinity(context, val, phase, operation=self)
                    values.append(val)

            if has_nan:
                mid_array[i] = nan_val
                top_array[i] = nan_val
                bot_array[i] = nan_val
                continue

            mid = midma_array[i]
            stddev = _population_stddev(values, period)

            width = devfactor * stddev
            top = mid + width
            bot = mid - width
            if context is not None:
                for value in (devfactor, stddev, width, mid, top, bot):
                    reject_infinity(context, value, phase, operation=self)
            mid_array[i] = mid
            top_array[i] = top
            bot_array[i] = bot


# Bollinger Bands Percentage indicator
class BollingerBandsPct(BollingerBands):
    """
    Extends the Bollinger Bands with a Percentage line
    """

    lines = ("pctb",)
    plotlines = {"pctb": {"_name": "%B"}}  # display the line as %B on chart

    def __init__(self):
        """Initialize the Bollinger Bands %B indicator.

        Extends Bollinger Bands with percentage calculation.
        """
        super().__init__()

    def next(self):
        """Calculate %B line for the current bar.

        Formula: %B = (price - bot) / (top - bot)
        """
        super().next()
        top = self.lines.top[0]
        bot = self.lines.bot[0]
        diff = top - bot
        context = self._factor_strict_context_for_callback()
        if context is not None:
            from ..research.strict import reject_infinity

            phase = getattr(context, "phase", None) or "next"
            reject_infinity(context, diff, phase, operation=self)
        if diff != 0:
            numerator = self.data[0] - bot
            if context is not None:
                reject_infinity(context, numerator, phase, operation=self)
            pct = numerator / diff
        else:
            pct = 0.0
        if context is not None:
            reject_infinity(context, pct, phase, operation=self)
        self.lines.pctb[0] = pct

    def once(self, start, end):
        """Calculate %B line in runonce mode."""
        if start >= end:
            return
        super().once(start, end)
        darray = self.data.array
        top_array = self.lines.top.array
        bot_array = self.lines.bot.array
        pctb_array = self.lines.pctb.array
        context = self._factor_strict_context_for_callback()
        if context is not None:
            from ..research.strict import reject_infinity

            phase = getattr(context, "phase", None) or "once"

        while len(pctb_array) < end:
            pctb_array.append(float("nan"))

        for i in range(start, min(end, len(darray), len(top_array), len(bot_array))):
            top = top_array[i] if i < len(top_array) else 0.0
            bot = bot_array[i] if i < len(bot_array) else 0.0
            data_val = darray[i] if i < len(darray) else 0.0

            if (
                isinstance(top, float)
                and math.isnan(top)
                or isinstance(bot, float)
                and math.isnan(bot)
            ):
                pctb_array[i] = float("nan")
            else:
                diff = top - bot
                if context is not None:
                    reject_infinity(context, diff, phase, operation=self)
                if diff != 0:
                    if context is not None:
                        reject_infinity(context, data_val, phase, operation=self)
                    numerator = data_val - bot
                    if context is not None:
                        reject_infinity(context, numerator, phase, operation=self)
                    pct = numerator / diff
                else:
                    pct = 0.0
                if context is not None:
                    reject_infinity(context, pct, phase, operation=self)
                pctb_array[i] = pct
