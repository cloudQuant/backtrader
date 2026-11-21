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
    class MyStrategy(bt.Strategy):
        def __init__(self):
            # Calculate highest and lowest prices over 20 periods
            self.highest = bt.indicators.Highest(self.data.close, period=20)
            self.lowest = bt.indicators.Lowest(self.data.close, period=20)

            # Calculate average price
            self.avg = bt.indicators.Average(self.data.close, period=20)

        def next(self):
            # Buy when price breaks above highest of last 20 bars
            if self.data.close[0] > self.highest[-1]:
                self.buy()

            # Sell when price breaks below lowest of last 20 bars
            elif self.data.close[0] < self.lowest[-1]:
                self.sell()
"""

import array
import functools
import math
import sys
import operator
import types
from collections import deque

from ..parameters import ParameterAccessor
from ..utils.log_message import get_logger
from ..utils.py3 import map, range
from . import Indicator

logger = get_logger(__name__)
_MIN_PERIOD_FOR_MONOTONIC_ONCE = 32
_MIN_PERIOD_FOR_MONOTONIC_INDEX_ONCE = 32
_MIN_PERIOD_FOR_SUM_ONCE = 32
_MIN_PERIOD_FOR_BOOL_ONCE = 32
_INDEX_ACCESSOR_CLASS = ParameterAccessor
_INDEX_ACCESSOR_GETATTRIBUTE = vars(ParameterAccessor).get("__getattribute__")
_INDEX_ACCESSOR_DICT = vars(ParameterAccessor).get("__dict__")


def _plain_index_evalfunc_is(indicator, expected):
    """Identify an inert built-in parameter without invoking its getter."""
    cls = type(indicator)
    if (
        type(cls) is not type
        or ParameterAccessor is not _INDEX_ACCESSOR_CLASS
        or vars(ParameterAccessor).get("__getattribute__") is not _INDEX_ACCESSOR_GETATTRIBUTE
    ):
        return False
    for base in type.__getattribute__(cls, "__mro__"):
        namespace = type.__getattribute__(base, "__dict__")
        if "__getattribute__" in namespace:
            if namespace["__getattribute__"] is not object.__getattribute__:
                return False
            break
    else:
        return False
    for check_cls, expected_dict in (
        (cls, _INDEX_INDICATOR_DICT),
        (ParameterAccessor, _INDEX_ACCESSOR_DICT),
    ):
        for base in type.__getattribute__(check_cls, "__mro__"):
            namespace = type.__getattribute__(base, "__dict__")
            if "__dict__" in namespace:
                if namespace["__dict__"] is not expected_dict:
                    return False
                break
        else:
            return False
    for base in type.__getattribute__(cls, "__mro__"):
        namespace = type.__getattribute__(base, "__dict__")
        if "p" in namespace:
            if namespace["p"] is not _INDEX_INDICATOR_P:
                return False
            break
    else:
        return False
    for base in type.__getattribute__(ParameterAccessor, "__mro__"):
        if "_evalfunc" in type.__getattribute__(base, "__dict__"):
            return False
    state = object.__getattribute__(indicator, "__dict__")
    if type(state) is not dict or any(type(key) is not str for key in state):
        return False
    params = state.get("_params_instance")
    if type(params) is not ParameterAccessor:
        return False
    state = object.__getattribute__(params, "__dict__")
    if type(state) is not dict or any(type(key) is not str for key in state):
        return False
    return state.get("_evalfunc") is expected


def _add_fsum_partial(partials, value):
    """Add a finite float to a non-overlapping Shewchuk exact-sum expansion.

    Matches the error-free high/low decomposition used by ``math.fsum`` so
    rolling window additions and removals retain bit-exact parity with
    per-window ``math.fsum`` calls.  Returns False on non-finite input or
    intermediate overflow.
    """
    isfinite = math.isfinite
    if not isfinite(value):
        return False

    index = 0
    for partial in partials:
        if abs(value) < abs(partial):
            value, partial = partial, value

        high = value + partial
        if not isfinite(high):
            return False

        low = partial - (high - value)
        if low:
            partials[index] = low
            index += 1
        value = high

    del partials[index:]
    if value:
        partials.append(value)
    return True


def _once_exact_sum(src, dst, start, end, period):
    """Calculate rolling ``math.fsum`` windows using an exact expansion.

    Preserves bit-exact parity with per-window ``math.fsum`` over finite data
    and falls back to exact per-window ``math.fsum`` for any window containing
    non-finite values or overflow, then cleanly re-seeds once those values
    leave the window.
    """
    nan = float("nan")
    while len(dst) < end:
        dst.append(nan)

    if start >= end:
        return

    calc_start = max(start, period - 1)
    actual_end = min(end, len(src))
    for i in range(start, min(calc_start, end)):
        dst[i] = nan
    for i in range(max(start, actual_end), end):
        dst[i] = nan

    if calc_start >= actual_end:
        return

    fsum = math.fsum
    isfinite = math.isfinite
    # A rolling expansion loses fsum's input-order overflow behavior.  If a
    # window could approach the floating-point limit, use fsum on that window
    # in its original order instead.  The factor two leaves rounding headroom.
    safe_term = sys.float_info.max / period / 2.0
    partials = None
    cur = 0.0
    i = calc_start

    while i < actual_end:
        if partials is None:
            win_start = i - period + 1
            bad_idx = -1
            for j in range(i, win_start - 1, -1):
                if not isfinite(src[j]) or abs(src[j]) > safe_term:
                    bad_idx = j
                    break

            if bad_idx >= 0:
                fallback_end = min(actual_end, bad_idx + period)
                for k in range(i, fallback_end):
                    try:
                        result = fsum(src[k - period + 1 : k + 1])
                        dst[k] = float(result) if result is not None else nan
                    except (ValueError, TypeError):
                        dst[k] = nan
                i = fallback_end
                continue

            partials = []
            overflowed = False
            for j in range(win_start, i + 1):
                if not _add_fsum_partial(partials, src[j]):
                    overflowed = True
                    break

            if not overflowed:
                try:
                    cur = (
                        partials[0]
                        if len(partials) == 1
                        else (fsum(partials) if partials else 0.0)
                    )
                except OverflowError:
                    overflowed = True

            if overflowed:
                # Re-run exact per-window fsum so OverflowError propagates
                # identically to the generic path if this window truly overflows.
                try:
                    result = fsum(src[win_start : i + 1])
                    dst[i] = float(result) if result is not None else nan
                except (ValueError, TypeError):
                    dst[i] = nan
                partials = None
                i += 1
                continue

            dst[i] = cur
            i += 1
            continue

        while i < actual_end:
            out_v = src[i - period]
            in_v = src[i]
            if not isfinite(in_v) or abs(in_v) > safe_term:
                partials = None
                break
            diff = in_v - out_v
            v = diff - in_v
            err = (in_v - (diff - v)) + (-out_v - v)
            if err == 0.0 and isfinite(diff):
                if diff:
                    n = len(partials)
                    if n == 0:
                        partials.append(diff)
                        cur = diff
                    elif n == 1:
                        x = diff
                        p0 = partials[0]
                        if abs(x) < abs(p0):
                            x, p0 = p0, x
                        h0 = x + p0
                        if not isfinite(h0):
                            partials = None
                            break
                        l0 = p0 - (h0 - x)
                        if l0:
                            partials[0] = l0
                            partials.append(h0)
                            try:
                                cur = fsum(partials)
                            except OverflowError:
                                partials = None
                                break
                        elif h0:
                            partials[0] = h0
                            cur = h0
                        else:
                            partials.clear()
                            cur = 0.0
                    elif n == 2:
                        p0 = partials[0]
                        p1 = partials[1]
                        x = diff
                        if abs(x) < abs(p0):
                            x, p0 = p0, x
                        h0 = x + p0
                        if not isfinite(h0):
                            partials = None
                            break
                        l0 = p0 - (h0 - x)
                        x = h0
                        if abs(x) < abs(p1):
                            x, p1 = p1, x
                        h1 = x + p1
                        if not isfinite(h1):
                            partials = None
                            break
                        l1 = p1 - (h1 - x)
                        if l0:
                            if l1:
                                partials[0] = l0
                                partials[1] = l1
                                if h1:
                                    partials.append(h1)
                            elif h1:
                                partials[0] = l0
                                partials[1] = h1
                            else:
                                partials[0] = l0
                                del partials[1:]
                        else:
                            if l1:
                                if h1:
                                    partials[0] = l1
                                    partials[1] = h1
                                else:
                                    partials[0] = l1
                                    del partials[1:]
                            elif h1:
                                partials[0] = h1
                                del partials[1:]
                            else:
                                partials.clear()
                        try:
                            cur = (
                                partials[0]
                                if len(partials) == 1
                                else (fsum(partials) if partials else 0.0)
                            )
                        except OverflowError:
                            partials = None
                            break
                    else:
                        if not _add_fsum_partial(partials, diff):
                            partials = None
                            break
                        try:
                            cur = (
                                partials[0]
                                if len(partials) == 1
                                else (fsum(partials) if partials else 0.0)
                            )
                        except OverflowError:
                            partials = None
                            break
            else:
                if not _add_fsum_partial(partials, -out_v) or not _add_fsum_partial(
                    partials, in_v
                ):
                    partials = None
                    break
                try:
                    cur = (
                        partials[0]
                        if len(partials) == 1
                        else (fsum(partials) if partials else 0.0)
                    )
                except OverflowError:
                    partials = None
                    break

            dst[i] = cur
            i += 1


def _once_rolling_bool(src, dst, start, end, period, require_all):
    """Calculate rolling ``any``/``all`` over IEEE-754 double arrays in O(n).

    For every IEEE-754 double ``v`` (including NaN, +/-Inf, and -0.0),
    ``bool(v)`` is True if and only if ``v != 0.0``.
    """
    nan = float("nan")
    while len(dst) < end:
        dst.append(nan)

    if start >= end:
        return

    calc_start = max(start, period - 1)
    actual_end = min(end, len(src))
    for i in range(start, min(calc_start, end)):
        dst[i] = nan
    for i in range(max(start, actual_end), end):
        dst[i] = nan

    if calc_start >= actual_end:
        return

    nonzero_count = 0
    for j in range(calc_start - period + 1, calc_start + 1):
        if src[j] != 0.0:
            nonzero_count += 1

    if require_all:
        dst[calc_start] = 1.0 if nonzero_count == period else 0.0
        for i in range(calc_start + 1, actual_end):
            if src[i - period] != 0.0:
                nonzero_count -= 1
            if src[i] != 0.0:
                nonzero_count += 1
            dst[i] = 1.0 if nonzero_count == period else 0.0
    else:
        dst[calc_start] = 1.0 if nonzero_count > 0 else 0.0
        for i in range(calc_start + 1, actual_end):
            if src[i - period] != 0.0:
                nonzero_count -= 1
            if src[i] != 0.0:
                nonzero_count += 1
            dst[i] = 1.0 if nonzero_count > 0 else 0.0


def _once_monotonic_extreme(src, dst, start, end, period, choose_max):
    """Calculate a built-in rolling min/max while preserving Python ordering.

    The deque retains the earliest occurrence of an equal extreme, matching
    ``min``/``max`` on a window. NaNs are not candidates because Python's
    built-ins ignore a NaN that follows the first item; a NaN at the window's
    left edge is emitted directly because it remains the built-in result.
    """
    nan = float("nan")
    while len(dst) < end:
        dst.append(nan)

    if start >= end:
        return

    candidates = deque()

    def add(index):
        value = src[index]
        if value != value:  # NaN is ignored unless it is the window's first value
            return
        while candidates:
            previous = src[candidates[-1]]
            is_better = value > previous if choose_max else value < previous
            if is_better:
                candidates.pop()
            else:
                break
        candidates.append(index)

    # ``oncestart`` and ``once`` are separate calls in the normal runonce
    # scheduler. Rebuild only the preceding portion of the first requested
    # window so this routine is also correct when called on arbitrary chunks.
    seed_start = max(0, start - period + 1)
    for index in range(seed_start, min(start, len(src))):
        add(index)

    for index in range(start, end):
        if index >= len(src):
            dst[index] = nan
            continue

        add(index)
        left = index - period + 1
        while candidates and candidates[0] < left:
            candidates.popleft()

        if index < period - 1:
            dst[index] = nan
        elif src[left] != src[left]:
            # Python max/min returns its first value when it is NaN because
            # all later comparisons against that current result are false.
            dst[index] = src[left]
        elif candidates:
            dst[index] = src[candidates[0]]
        else:
            # A complete non-NaN-first window always has a candidate. Keep a
            # safe fallback for malformed/nonstandard array contents.
            dst[index] = nan


def _once_monotonic_index(src, dst, start, end, period, choose_max, choose_latest):
    """Calculate rolling built-in extremum indexes with a monotonic deque."""
    nan = float("nan")
    while len(dst) < end:
        dst.append(nan)

    if start >= end:
        return

    candidates = deque()

    def add(index):
        value = src[index]
        if value != value:  # NaNs after the window's first value are ignored
            return

        while candidates:
            previous = src[candidates[-1]]
            is_better = value > previous if choose_max else value < previous
            if is_better or (choose_latest and value == previous):
                candidates.pop()
            else:
                break
        candidates.append(index)

    seed_start = max(0, start - period + 1)
    for index in range(seed_start, min(start, len(src))):
        add(index)

    for index in range(start, end):
        if index >= len(src):
            dst[index] = nan
            continue

        add(index)
        left = index - period + 1
        while candidates and candidates[0] < left:
            candidates.popleft()

        if index < period - 1:
            dst[index] = nan
        elif src[left] != src[left]:
            # Match the built-in max/min followed by equality search: when
            # the left edge is NaN, no element compares equal to the result.
            raise StopIteration
        elif candidates:
            dst[index] = float(index - candidates[0])
        else:
            raise StopIteration


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
        window = self.data.get(size=self.p.period)
        if len(window) < self.p.period:
            try:
                window = [self.data[i] for i in range(-self.p.period + 1, 1)]
            except (IndexError, TypeError):
                window = ()

        if len(window) < self.p.period:
            self.lines[0][0] = float("nan")
            return

        value = self.func(window)
        self.lines[0][0] = value

    def once(self, start, end):
        """Optimized batch calculation for runonce mode - same approach as SMA"""
        try:
            # Get arrays for efficient calculation - use same approach as SMA
            dst = self.lines[0].array
            src = self.data.array
            period = self.p.period
            func = self.func

            choose_max = None
            if type(self) is Highest and func is max:
                choose_max = True
            elif type(self) is Lowest and func is min:
                choose_max = False

            index_choice = None
            choose_latest = None
            index_func = None
            if type(func) is types.MethodType and func.__self__ is self:
                index_func = func.__func__

            if (
                type(self) is FindFirstIndexHighest
                and index_func is _FIND_FIRST_INDEX_FUNC
                and _plain_index_evalfunc_is(self, max)
            ):
                index_choice = True
                choose_latest = True
            elif (
                type(self) is FindFirstIndexLowest
                and index_func is _FIND_FIRST_INDEX_FUNC
                and _plain_index_evalfunc_is(self, min)
            ):
                index_choice = False
                choose_latest = True
            elif (
                type(self) is FindLastIndexHighest
                and index_func is _FIND_LAST_INDEX_FUNC
                and _plain_index_evalfunc_is(self, max)
            ):
                index_choice = True
                choose_latest = False
            elif (
                type(self) is FindLastIndexLowest
                and index_func is _FIND_LAST_INDEX_FUNC
                and _plain_index_evalfunc_is(self, min)
            ):
                index_choice = False
                choose_latest = False

            if (
                index_choice is not None
                and type(period) is int
                and period >= _MIN_PERIOD_FOR_MONOTONIC_INDEX_ONCE
                and type(start) is int
                and type(end) is int
                and start >= 0
                and end >= 0
                and type(src) is array.array
                and src.typecode == "d"
                and type(dst) is array.array
                and dst.typecode == "d"
                and src is not dst
            ):
                # The generic path's NaN-left behavior includes a StopIteration
                # fallback. Skip the fast path for any affected window so that
                # existing per-mode exception/fallback behavior stays intact.
                first_current = max(start, period - 1)
                last_current = min(end, len(src))
                has_nan_left = any(
                    src[current - period + 1] != src[current - period + 1]
                    for current in range(first_current, last_current)
                )
                if not has_nan_left:
                    _once_monotonic_index(
                        src,
                        dst,
                        start,
                        end,
                        period,
                        index_choice,
                        choose_latest,
                    )
                    return

            # Only the concrete built-ins over the standard double arrays have
            # the ordering contract implemented by the monotonic deque. Keep
            # subclasses, custom callables and nonstandard storage on the
            # established generic path. Short windows stay on C-level max/min;
            # the deque becomes faster at the measured 32-period crossover.
            if (
                choose_max is not None
                and type(period) is int
                and period >= _MIN_PERIOD_FOR_MONOTONIC_ONCE
                and type(start) is int
                and type(end) is int
                and start >= 0
                and end >= 0
                and type(src) is array.array
                and src.typecode == "d"
                and type(dst) is array.array
                and dst.typecode == "d"
                and src is not dst
            ):
                _once_monotonic_extreme(src, dst, start, end, period, choose_max)
                return

            if (
                type(self) is _SUMN_CLASS
                and func is math.fsum
                and type(period) is int
                and period >= _MIN_PERIOD_FOR_SUM_ONCE
                and type(start) is int
                and type(end) is int
                and start >= 0
                and end >= 0
                and type(src) is array.array
                and src.typecode == "d"
                and type(dst) is array.array
                and dst.typecode == "d"
                and src is not dst
            ):
                _once_exact_sum(src, dst, start, end, period)
                return

            if (
                ((type(self) is _ANYN_CLASS and func is any) or (type(self) is _ALLN_CLASS and func is all))
                and type(period) is int
                and period >= _MIN_PERIOD_FOR_BOOL_ONCE
                and type(start) is int
                and type(end) is int
                and start >= 0
                and end >= 0
                and type(src) is array.array
                and src.typecode == "d"
                and type(dst) is array.array
                and dst.typecode == "d"
                and src is not dst
            ):
                _once_rolling_bool(src, dst, start, end, period, type(self) is _ALLN_CLASS)
                return

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
            logger.debug("OperationN.once() failed, falling back to once_via_next", exc_info=True)
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


# Pin concrete built-in classes at module load so monkeypatching module globals
# cannot cause subclasses with custom contracts to qualify for fast paths.
_SUMN_CLASS = SumN
_ANYN_CLASS = AnyN
_ALLN_CLASS = AllN


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


# Dynamic replacement of either base method must stay on the generic path.
_FIND_FIRST_INDEX_FUNC = FindFirstIndex.func
_FIND_LAST_INDEX_FUNC = FindLastIndex.func
_INDEX_INDICATOR_P = next(
    vars(base)["p"] for base in FindFirstIndexHighest.__mro__ if "p" in vars(base)
)
_INDEX_INDICATOR_DICT = next(
    vars(base)["__dict__"] for base in FindFirstIndexHighest.__mro__ if "__dict__" in vars(base)
)


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
        src_start = max(0, start - self.p.period + 1)
        src_end = end
        # Match next()'s line projection and strict infinity checks while
        # reading only the source segment needed by this runonce chunk.
        src = self.data.get(
            ago=src_end - 1 - self.data._idx,
            size=src_end - src_start,
        )
        dst = self.lines[0].array
        period = self.p.period

        # Ensure destination array is large enough
        while len(dst) < end:
            dst.append(float("nan"))

        for i in range(start, end):
            if i >= period - 1:
                start_idx = i - period + 1
                end_idx = i + 1
                local_start = start_idx - src_start
                local_end = end_idx - src_start
                if local_end <= len(src):
                    dst[i] = math.fsum(src[local_start:local_end]) / period
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
            larray.append(float("nan"))

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
        if prev is None or (isinstance(prev, float) and math.isnan(prev)):
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


class _Alpha1Line(Indicator):
    """Helper indicator to compute 1 - alpha dynamically.

    Used by ExponentialSmoothingDynamic when alpha is a LineBuffer.
    """

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

        self._alpha_is_line = hasattr(self.alpha, "array")

        if self._alpha_is_line:
            # alpha is a LineBuffer or similar object
            minperioddiff = max(0, self.alpha._minperiod - self.p.period)
            self.lines[0].incminperiod(minperioddiff)

            self.alpha1 = _Alpha1Line(alpha_source=self.alpha)

        else:
            # alpha is a float value - fall back to static smoothing
            pass

    def next(self):
        """Calculate dynamic EMA for the current bar.

        Handles both float and LineBuffer alpha sources.
        """
        alpha = self.alpha[0] if self._alpha_is_line else self.alpha
        alpha1 = self.alpha1[0] if self._alpha_is_line else self.alpha1
        self.lines[0][0] = self.lines[0][-1] * alpha1 + self.data[0] * alpha

    def once(self, start, end):
        """Calculate dynamic EMA in runonce mode.

        Handles both float and LineBuffer alpha sources.
        """
        darray = self.data.array
        larray = self.lines[0].array

        alpha = self.alpha.array if self._alpha_is_line else self.alpha
        alpha1 = self.alpha1.array if self._alpha_is_line else self.alpha1

        prev = larray[start - 1]
        for i in range(start, end):
            alpha_i = alpha[i] if self._alpha_is_line else alpha
            alpha1_i = alpha1[i] if self._alpha_is_line else alpha1
            larray[i] = prev = prev * alpha1_i + darray[i] * alpha_i


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
    params: tuple = (
        ("coef", 1.0),
        ("weights", ()),
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
