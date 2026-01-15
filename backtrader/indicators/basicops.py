#!/usr/bin/env python
"""Basic Operations Indicator Module - Fundamental calculation indicators.

This module provides basic mathematical operations and calculations for
indicator development, including period-based operations and statistics.

Classes:
    PeriodN: Base class for period-based indicators.
    OperationN: Base class for function-based period calculations.
    BaseApplyN: Base class for applying a function over a period.
    ApplyN: Applies a function over a period.
    Highest: Calculates highest value (alias: MaxN).
    Lowest: Calculates lowest value (alias: MinN).
    ReduceN: Applies reduce function over a period.
    SumN: Calculates sum over a period.
    AnyN: Returns True if any value is True.
    AllN: Returns True only if all values are True.
    FindFirstIndex: Finds first index matching condition.
    FindFirstIndexHighest: Index of first highest value.
    FindFirstIndexLowest: Index of first lowest value.
    FindLastIndex: Finds last index matching condition.
    FindLastIndexHighest: Index of last highest value.
    FindLastIndexLowest: Index of last lowest value.
    Accum: Cumulative sum (aliases: CumSum, CumulativeSum).
    Average: Arithmetic mean (aliases: ArithmeticMean, Mean).
    ExponentialSmoothing: EMA-style smoothing (alias: ExpSmoothing).
    ExponentialSmoothingDynamic: Dynamic alpha smoothing (alias: ExpSmoothingDynamic).
    WeightedAverage: Weighted average (alias: AverageWeighted).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> highest = bt.indicators.Highest(data.close, period=20)
"""
import functools
import math
import operator

from ..utils.py3 import map, range
from . import Indicator


class PeriodN(Indicator):
    """
    Base class for indicators which take a period (__init__ has to be called
    either via supper or explicitly)

    This class has no defined lines
    """

    params = (("period", 1),)

    def __init__(self):
        """Initialize the period-based indicator.

        Sets minimum period based on the period parameter.
        """
        super().__init__()
        self.addminperiod(self.p.period)


# Calculate data for past N periods using func, func is a callable function
class OperationN(PeriodN):
    """
    Calculates "func" for a given period

    Serves as a base for classes that work with a period and can express the
    logic in a callable object

    Note:
      Base classes must provide a "func" attribute which is callable

    Formula:
      - line = func(data, period)
    """

    def next(self):
        """Calculate function value for the current bar.

        Applies func to the last 'period' data values.
        """
        # CRITICAL FIX: Use proper line assignment instead of direct array manipulation
        # The line[0] assignment will handle the buffer correctly
        value = self.func(self.data.get(size=self.p.period))
        self.lines[0][0] = value

    def once(self, start, end):
        """Optimized batch calculation for runonce mode - same approach as SMA"""
        try:
            # Get arrays for efficient calculation - use same approach as SMA
            dst = self.lines[0].array
            src = self.data.array
            period = self.p.period
            func = self.func

            # CRITICAL FIX: Handle case where start >= end (not enough data for this indicator)
            # This can happen when nested indicators have larger minperiod than available data
            if start >= end:
                # Still need to pre-fill the array with NaN
                while len(dst) < end:
                    dst.append(float("nan"))
                return  # No data to process

            # CRITICAL FIX: Pre-fill warmup period with NaN instead of 0.0
            # This ensures that accessing indicator values before minperiod returns nan
            # instead of 0.0, which could trigger incorrect buy/sell signals
            while len(dst) < end:
                dst.append(float("nan"))

            # Calculate for each index from start to end
            for i in range(start, end):
                if i >= period - 1:
                    # Calculate SMA-style: get last 'period' values
                    start_idx = i - period + 1
                    end_idx = i + 1
                    if end_idx <= len(src):
                        # Get slice of data
                        slice_data = src[start_idx:end_idx]
                        # Apply function (min, max, etc.)
                        if len(slice_data) == period:
                            try:
                                result = func(slice_data)
                                dst[i] = float(result) if result is not None else float("nan")
                            except (ValueError, TypeError):
                                dst[i] = float("nan")
                        else:
                            dst[i] = float("nan")
                    else:
                        dst[i] = float("nan")
                else:
                    # Not enough data yet
                    dst[i] = float("nan")
        except Exception:
            # Fallback to once_via_next if once() fails
            super().once_via_next(start, end)


# Set callable function when calculating indicators
class BaseApplyN(OperationN):
    """
    Base class for ApplyN and others which may take a ``func`` as a parameter
    but want to define the lines in the indicator.

    Calculates ``func`` for a given period where func is given as a parameter,
    aka named argument or ``kwarg``

    Formula:
      - lines[0] = func(data, period)

    Any extra lines defined beyond the first (index 0) are not calculated
    """

    params = (("func", None),)

    def __init__(self):
        """Initialize the base apply indicator.

        Sets func from parameter and initializes parent.
        """
        self.func = self.p.func
        super().__init__()


# Calculate specific line based on the set callable function
class ApplyN(BaseApplyN):
    """
    Calculates ``func`` for a given period

    Formula:
      - line = func(data, period)
    """

    lines = ("apply",)


# Calculate highest price in past N periods
class Highest(OperationN):
    """
    Calculates the highest value for the data in a given period

    Uses the built-in ``max`` for the calculation

    Formula:
      - highest = max(data, period)
    """

    alias = ("MaxN",)
    lines = ("highest",)
    func = max


# Calculate lowest price in past N periods
class Lowest(OperationN):
    """
    Calculates the lowest value for the data in a given period

    Uses the built-in ``min`` for the calculation

    Formula:
      - lowest = min(data, period)
    """

    alias = ("MinN",)
    lines = ("lowest",)
    func = min


# Mimic Python's reduce functionality
class ReduceN(OperationN):
    """
    Calculates the Reduced value of the ``period`` data points applying
    ``function``

    Uses the built-in ``reduce`` for the calculation plus the ``func`` that
    subclassess define

    Formula:
      - reduced = reduce (function(data, period)), initializer=initializer)

    Notes:

      - In order to mimic the python `reduce`, this indicator takes a
        ``function`` non-named argument as the 1st argument, unlike other
        Indicators which take only named arguments
    """

    lines = ("reduced",)
    func = functools.reduce

    def __init__(self, function, **kwargs):
        """Initialize the ReduceN indicator.

        Sets up reduce function with optional initializer.

        Args:
            function: The reduce function to apply.
            **kwargs: Optional 'initializer' parameter.
        """
        if "initializer" not in kwargs:
            self.func = functools.partial(self.func, function)
        else:
            self.func = functools.partial(self.func, function, initializer=kwargs["initializer"])

        super().__init__()


# Calculate sum of past N periods
class SumN(OperationN):
    """
    Calculates the Sum of the data values over a given period

    Uses ``math.fsum`` for the calculation rather than the built-in ``sum`` to
    avoid precision errors

    Formula:
      - sumn = sum(data, period)
    """

    lines = ("sumn",)
    func = math.fsum


# Return True if any value in past N periods is True
class AnyN(OperationN):
    """
    Has a value of ``True`` (stored as ``1.0`` in the lines) if *any* of the
    values in the ``period`` evaluates to non-zero (ie: ``True``)

    Uses the built-in `any` for the calculation

    Formula:
      - anyn = any(data, period)
    """

    lines = ("anyn",)
    func = any


# Return True only if all values in past N periods are True
class AllN(OperationN):
    """
    Has a value of ``True`` (stored as ``1.0`` in the lines) if *all* of the
    values in the ``period`` evaluates to non-zero (ie: ``True``)

    Uses the built-in `all` for the calculation

    Formula:
      - alln = all(data, period)
    """

    lines = ("alln",)
    func = all


# Return the first data point that satisfies the condition
class FindFirstIndex(OperationN):
    """
    Returns the index of the last data that satisfies equality with the
    condition generated by the parameter _evalfunc

    Note:
      Returned indexes look backwards. 0 is the current index and 1 is
      the previous bar.

    Formula:
      - index = first for which data[index] == _evalfunc(data)
    """

    lines = ("index",)
    params = (("_evalfunc", None),)

    def func(self, iterable):
        """Find first index where value matches eval function result.

        Args:
            iterable: Data values to search.

        Returns:
            Index of first matching value (looking backwards).
        """
        m = self.p._evalfunc(iterable)
        return next(i for i, v in enumerate(reversed(iterable)) if v == m)


# Get the earliest occurrence of the highest price in the past
class FindFirstIndexHighest(FindFirstIndex):
    """
    Returns the index of the first data that is the highest in the period

    Note:
      Returned indexes look backwards. 0 is the current index and 1 is
      the previous bar.

    Formula:
      - index = index of first data which is the highest
    """

    params = (("_evalfunc", max),)


# Get the earliest occurrence of the lowest price in the past
class FindFirstIndexLowest(FindFirstIndex):
    """
    Returns the index of the first data that is the lowest in the period

    Note:
      Returned indexes look backwards. 0 is the current index and 1 is
      the previous bar.

    Formula:
      - index = index of first data which is the lowest
    """

    params = (("_evalfunc", min),)


# Get the index of the last data point that satisfies the condition
class FindLastIndex(OperationN):
    """
    Returns the index of the last data that satisfies equality with the
    condition generated by the parameter _evalfunc

    Note:
      Returned indexes look backwards. 0 is the current index and 1 is
      the previous bar.

    Formula:
      - index = last for which data[index] == _evalfunc(data)
    """

    lines = ("index",)
    params = (("_evalfunc", None),)

    def func(self, iterable):
        """Find last index where value matches eval function result.

        Args:
            iterable: Data values to search.

        Returns:
            Index of last matching value (looking backwards).
        """
        m = self.p._evalfunc(iterable)
        index = next(i for i, v in enumerate(iterable) if v == m)
        # The iterable goes from 0 -> period - 1. If the last element
        # which is the current bar is returned and without the -1 then
        # period - index = 1 ... and must be zero!
        return self.p.period - index - 1


# Get the latest occurrence of the highest price in the past
class FindLastIndexHighest(FindLastIndex):
    """
    Returns the index of the last data that is the highest in the period

    Note:
      Returned indexes look backwards. 0 is the current index and 1 is
      the previous bar.

    Formula:
      - index = index of last data which is the highest
    """

    params = (("_evalfunc", max),)


# Get the latest occurrence of the lowest price in the past
class FindLastIndexLowest(FindLastIndex):
    """
    Returns the index of the last data that is the lowest in the period

    Note:
      Returned indexes look backwards. 0 is the current index and 1 is
      the previous bar.

    Formula:
      - index = index of last data which is the lowest
    """

    params = (("_evalfunc", min),)


# Calculate cumulative sum
class Accum(Indicator):
    """
    Cummulative sum of the data values

    Formula:
      - accum += data
    """

    alias = (
        "CumSum",
        "CumulativeSum",
    )
    lines = ("accum",)
    params = (("seed", 0.0),)

    # xxxstart methods use the seed (starting value) and passed data to
    # construct the first value keeping the minperiod to 1 since no
    # initial look-back value is needed

    def nextstart(self):
        """Start accumulation with seed value.

        accum = seed + data[0]
        """
        self.lines[0][0] = self.p.seed + self.data[0]

    def next(self):
        """Add current data value to accumulation.

        accum += data
        """
        self.lines[0][0] = self.lines[0][-1] + self.data[0]

    def oncestart(self, start, end):
        """Start accumulation in runonce mode.

        accum = seed + data for each bar.
        """
        dst = self.lines[0].array
        src = self.data.array
        prev = self.p.seed

        for i in range(start, end):
            dst[i] = prev = prev + src[i]

    def once(self, start, end):
        """Continue accumulation in runonce mode.

        accum = prev_accum + data for each bar.
        """
        dst = self.lines[0].array
        src = self.data.array
        prev = dst[start - 1]

        for i in range(start, end):
            dst[i] = prev = prev + src[i]


# Calculate arithmetic mean
class Average(PeriodN):
    """
    Averages a given data arithmetically over a period

    Formula:
      - av = data(period) / period

    See also:
      - https://en.wikipedia.org/wiki/Arithmetic_mean
    """

    alias = (
        "ArithmeticMean",
        "Mean",
    )
    lines = ("av",)

    def next(self):
        """Calculate arithmetic mean for the current bar.

        av = sum(data, period) / period
        """
        data_values = self.data.get(size=self.p.period)
        avg_value = math.fsum(data_values) / self.p.period
        self.lines[0][0] = avg_value

    def once(self, start, end):
        """Calculate Average (SMA) in runonce mode"""
        src = self.data.array
        dst = self.lines[0].array
        period = self.p.period

        # Ensure destination array is large enough
        while len(dst) < end:
            dst.append(0.0)

        for i in range(start, end):
            if i >= period - 1:
                start_idx = i - period + 1
                end_idx = i + 1
                if end_idx <= len(src):
                    dst[i] = sum(src[start_idx:end_idx]) / period
                else:
                    dst[i] = float("nan")
            else:
                dst[i] = float("nan")


# Calculate exponential moving average
class ExponentialSmoothing(Average):
    """
    Averages a given data over a period using exponential smoothing

    A regular ArithmeticMean (Average) is used as the seed value considering
    the first period values of data

    Formula:
      - av = prev * (1 - alpha) + data * alpha

    See also:
      - https://en.wikipedia.org/wiki/Exponential_smoothing
    """

    alias = ("ExpSmoothing",)
    params = (("alpha", None),)

    def __init__(self):
        """Initialize the exponential smoothing indicator.

        Calculates alpha and alpha1 for smoothing calculation.
        """
        self.alpha = self.p.alpha
        if self.alpha is None:
            self.alpha = 2.0 / (1.0 + self.p.period)  # def EMA value

        self.alpha1 = 1.0 - self.alpha

        super().__init__()

    def nextstart(self):
        """Seed exponential smoothing with SMA value.

        Uses parent's SMA calculation for initial seed.
        """
        # Fetch the seed value from the base class calculation
        super().next()

    def next(self):
        """Calculate EMA for the current bar.

        av = prev * alpha1 + data * alpha
        """
        self.lines[0][0] = self.lines[0][-1] * self.alpha1 + self.data[0] * self.alpha

    def oncestart(self, start, end):
        """Calculate seed value in runonce mode.

        Uses parent's SMA calculation for initial seed.
        """
        # Calculate seed value using parent's once method (SMA of first period values)
        # Call parent's once method to populate seed at index period-1
        if start == self.p.period - 1:
            super().once(start, end)

    def once(self, start, end):
        """Calculate EMA in runonce mode"""
        darray = self.data.array
        larray = self.lines[0].array
        alpha = self.alpha
        alpha1 = self.alpha1
        period = self.p.period

        # CRITICAL FIX: Ensure array is properly sized
        while len(larray) < end:
            larray.append(0.0)

        # CRITICAL FIX: Pre-fill warmup period with NaN to match expected behavior
        # This prevents invalid comparisons during prenext when strategy calls next()
        for i in range(0, min(period - 1, len(darray))):
            larray[i] = float("nan")

        # CRITICAL FIX: Calculate seed value (SMA of first period values)
        # EMA starts at index period-1 with seed = SMA of first period values
        seed_idx = period - 1

        # Calculate seed as SMA of first period values
        prev = None
        if seed_idx < len(darray) and seed_idx >= 0:
            seed_start = max(0, seed_idx - period + 1)
            seed_end = seed_idx + 1
            if seed_end <= len(darray) and seed_end > seed_start:
                seed_data = darray[seed_start:seed_end]
                if len(seed_data) >= period:
                    prev = sum(seed_data) / period
                elif len(seed_data) > 0:
                    prev = sum(seed_data) / len(seed_data)

        # Fallback: use first data point if seed calculation failed
        if prev is None or prev <= 0.0 or (isinstance(prev, float) and math.isnan(prev)):
            if len(darray) > 0:
                prev = float(darray[0])
            else:
                prev = 0.0

        # Set seed value at index period-1 if within calculation range
        if seed_idx >= start and seed_idx < end:
            larray[seed_idx] = prev

        # Calculate EMA for indices from period to end
        calc_start = max(start, period)
        for i in range(calc_start, end):
            if i < len(darray) and i >= 0:
                # Use previous EMA value if available, otherwise use seed
                if i > calc_start:
                    prev_ema = larray[i - 1]
                    if prev_ema > 0.0 and not (
                        isinstance(prev_ema, float) and math.isnan(prev_ema)
                    ):
                        prev = prev_ema

                # EMA formula: prev * alpha1 + current * alpha
                current_val = float(darray[i])
                prev = prev * alpha1 + current_val * alpha
                larray[i] = prev
            elif i >= len(darray):
                break


# Dynamic exponential moving average
class ExponentialSmoothingDynamic(ExponentialSmoothing):
    """
    Averages a given data over a period using exponential smoothing

    A regular ArithmeticMean (Average) is used as the seed value considering
    the first period values of data

    Note:
      - alpha is an array of values which can be calculated dynamically

    Formula:
      - av = prev * (1 - alpha) + data * alpha

    See also:
      - https://en.wikipedia.org/wiki/Exponential_smoothing
    """

    alias = ("ExpSmoothingDynamic",)

    def __init__(self):
        """Initialize the dynamic exponential smoothing indicator.

        Sets up alpha1 line for dynamic alpha values.
        """
        super().__init__()

        # CRITICAL FIX: Handle cases where alpha is a float instead of a LineBuffer
        # The parent class sets self.alpha to a float value, but ExponentialSmoothingDynamic
        # expects it to be a line-like object with _minperiod and array access

        if hasattr(self.alpha, "_minperiod"):
            # alpha is a LineBuffer or similar object
            minperioddiff = max(0, self.alpha._minperiod - self.p.period)
            self.lines[0].incminperiod(minperioddiff)

            # Set up alpha1 as a line that computes 1 - alpha
            from . import Indicator

            class Alpha1Line(Indicator):
                """Helper class to compute 1 - alpha dynamically."""

                lines = ("alpha1",)
                params = (("alpha_source", None),)

                def __init__(self):
                    """Initialize with alpha source reference."""
                    self.alpha_source = self.p.alpha_source
                    super().__init__()

                def next(self):
                    """Calculate 1 - alpha for current bar."""
                    self.lines.alpha1[0] = 1.0 - self.alpha_source[0]

                def once(self, start, end):
                    """Calculate 1 - alpha in runonce mode."""
                    alpha_array = self.alpha_source.array
                    alpha1_array = self.lines.alpha1.array
                    for i in range(start, end):
                        alpha1_array[i] = 1.0 - alpha_array[i]

            self.alpha1 = Alpha1Line(alpha_source=self.alpha)

        else:
            # alpha is a float value - convert it to work with dynamic smoothing
            # In this case, we can't do true dynamic smoothing, so we fall back to static
            # print(f"WARNING: ExponentialSmoothingDynamic received float alpha={self.alpha}, falling back to static smoothing")  # Removed for performance
            pass
            # No additional minperiod adjustment needed for static alpha
            # self.alpha1 is already set in parent class as a float

    def next(self):
        """Calculate dynamic EMA for the current bar.

        Handles both float and LineBuffer alpha sources.
        """
        # CRITICAL FIX: Handle both float and LineBuffer cases for alpha
        if hasattr(self.alpha, "__getitem__"):
            # alpha is a LineBuffer - use array access
            self.lines[0][0] = self.lines[0][-1] * self.alpha1[0] + self.data[0] * self.alpha[0]
        else:
            # alpha is a float - use regular arithmetic (fall back to parent behavior)
            self.lines[0][0] = self.lines[0][-1] * self.alpha1 + self.data[0] * self.alpha

    def once(self, start, end):
        """Calculate dynamic EMA in runonce mode.

        Handles both float and LineBuffer alpha sources.
        """
        # CRITICAL FIX: Handle both float and LineBuffer cases for alpha
        darray = self.data.array
        larray = self.line.array

        if hasattr(self.alpha, "array"):
            # alpha is a LineBuffer - use array access
            alpha = self.alpha.array
            alpha1 = self.alpha1.array

            # Seed value from SMA calculated with the call to oncestart
            prev = larray[start - 1]
            for i in range(start, end):
                larray[i] = prev = prev * alpha1[i] + darray[i] * alpha[i]
        else:
            # alpha is a float - use regular arithmetic (fall back to parent behavior)
            alpha = self.alpha
            alpha1 = self.alpha1

            # Seed value from SMA calculated with the call to oncestart
            prev = larray[start - 1]
            for i in range(start, end):
                larray[i] = prev = prev * alpha1 + darray[i] * alpha


# Calculate weighted moving average
class WeightedAverage(PeriodN):
    """
    Calculates the weighted average of the given data over a period

    The default weights (if none are provided) are linear to assigne more
    weight to the most recent data

    The result will be multiplied by a given "coef"

    Formula:
      - av = coef * sum(mul(data, period), weights)

    See:
      - https://en.wikipedia.org/wiki/Weighted_arithmetic_mean
    """

    alias = ("AverageWeighted",)
    lines = ("av",)
    params = (
        ("coef", 1.0),
        ("weights", tuple()),
    )

    def __init__(self):
        """Initialize the Weighted Average indicator.

        Sets up parameters for weighted average calculation.
        """
        super().__init__()

    def next(self):
        """Calculate weighted average for the current bar.

        Multiplies data by weights and sums, then applies coefficient.
        """
        data = self.data.get(size=self.p.period)
        dataweighted = map(operator.mul, data, self.p.weights)
        self.lines[0][0] = self.p.coef * math.fsum(dataweighted)

    def once(self, start, end):
        """Calculate weighted average in runonce mode.

        Computes weighted averages across all bars efficiently.
        """
        darray = self.data.array
        larray = self.line.array
        period = self.p.period
        coef = self.p.coef
        weights = self.p.weights

        for i in range(start, end):
            data = darray[i - period + 1 : i + 1]
            larray[i] = coef * math.fsum(map(operator.mul, data, weights))


AverageWeighted = WeightedAverage
