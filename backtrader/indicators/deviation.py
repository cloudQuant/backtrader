#!/usr/bin/env python
"""Deviation Indicator Module - Standard deviation and mean deviation.

This module provides deviation indicators for measuring data dispersion.

Classes:
    StandardDeviation: Standard deviation indicator (alias: StdDev).
    MeanDeviation: Mean absolute deviation (alias: MeanDev).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=20)
            self.stddev = bt.indicators.StdDev(self.data.close, period=20)
            self.upper_band = self.sma + 2 * self.stddev
            self.lower_band = self.sma - 2 * self.stddev

        def next(self):
            if self.data.close[0] > self.upper_band[0]:
                self.sell()
            elif self.data.close[0] < self.lower_band[0]:
                self.buy()
"""

import array
import math

from ..parameters import ParameterAccessor, ParameterManager
from . import Indicator, MovAv

_MIN_PERIOD_FOR_ROLLING_STDDEV_ONCE = 16
_MATH_HAS_PLAIN_KEYS = type(math) is type(array) and all(type(key) is str for key in math.__dict__)
_ORIGINAL_FSUM = math.__dict__.get("fsum") if _MATH_HAS_PLAIN_KEYS else None
_ORIGINAL_SQRT = math.__dict__.get("sqrt") if _MATH_HAS_PLAIN_KEYS else None
_ORIGINAL_ISFINITE = math.__dict__.get("isfinite") if _MATH_HAS_PLAIN_KEYS else None
_BUILTINS_HAS_PLAIN_KEYS = type(__builtins__) is dict and all(
    type(key) is str for key in __builtins__
)
_ORIGINAL_ABS = __builtins__.get("abs") if _BUILTINS_HAS_PLAIN_KEYS else None
_NATIVE_MATH_BINDINGS = (
    type(_ORIGINAL_ABS) is type([].append)
    and type(_ORIGINAL_FSUM) is type(_ORIGINAL_ABS)
    and type(_ORIGINAL_SQRT) is type(_ORIGINAL_ABS)
    and type(_ORIGINAL_ISFINITE) is type(_ORIGINAL_ABS)
    and _ORIGINAL_FSUM.__module__ == "math"
    and _ORIGINAL_FSUM.__name__ == "fsum"
    and _ORIGINAL_SQRT.__module__ == "math"
    and _ORIGINAL_SQRT.__name__ == "sqrt"
    and _ORIGINAL_ISFINITE.__module__ == "math"
    and _ORIGINAL_ISFINITE.__name__ == "isfinite"
    and _ORIGINAL_ABS.__module__ == "builtins"
    and _ORIGINAL_ABS.__name__ == "abs"
)
_PARAMETER_ACCESSOR_GETATTRIBUTE = ParameterAccessor.__getattribute__
_PARAMETER_ACCESSOR_GETATTRIBUTE_CODE = _PARAMETER_ACCESSOR_GETATTRIBUTE.__code__
_PARAMETER_MANAGER_GET = ParameterManager.get
_PARAMETER_MANAGER_GET_CODE = _PARAMETER_MANAGER_GET.__code__
_PARAMETER_MANAGER_GET_DEFAULTS = _PARAMETER_MANAGER_GET.__defaults__
_PARAMETER_ACCESSOR_DICT_DESCRIPTOR = vars(ParameterAccessor).get("__dict__")
_PARAMETER_MANAGER_DICT_DESCRIPTOR = vars(ParameterManager).get("__dict__")


def _has_plain_safepow_parameter(indicator):
    """Only cache rolling state when reading safepow cannot call user code."""
    if (
        type(indicator) is not _STANDARD_DEVIATION_CLASS
        or vars(ParameterAccessor).get("__getattribute__") is not _PARAMETER_ACCESSOR_GETATTRIBUTE
        or _PARAMETER_ACCESSOR_GETATTRIBUTE.__code__ is not _PARAMETER_ACCESSOR_GETATTRIBUTE_CODE
        or vars(ParameterManager).get("get") is not _PARAMETER_MANAGER_GET
        or _PARAMETER_MANAGER_GET.__code__ is not _PARAMETER_MANAGER_GET_CODE
        or _PARAMETER_MANAGER_GET.__defaults__ is not _PARAMETER_MANAGER_GET_DEFAULTS
    ):
        return False
    for cls in (type(indicator), ParameterManager):
        for base in type.__getattribute__(cls, "__mro__"):
            namespace = type.__getattribute__(base, "__dict__")
            if "__getattribute__" in namespace:
                if namespace["__getattribute__"] is not object.__getattribute__:
                    return False
                break
        else:
            return False
    for cls, expected_dict in (
        (type(indicator), _STANDARD_DEVIATION_DICT_DESCRIPTOR),
        (ParameterAccessor, _PARAMETER_ACCESSOR_DICT_DESCRIPTOR),
        (ParameterManager, _PARAMETER_MANAGER_DICT_DESCRIPTOR),
    ):
        for base in type.__getattribute__(cls, "__mro__"):
            namespace = type.__getattribute__(base, "__dict__")
            if "__dict__" in namespace:
                if namespace["__dict__"] is not expected_dict:
                    return False
                break
        else:
            return False
    for base in type.__getattribute__(ParameterAccessor, "__mro__"):
        if "_param_manager" in type.__getattribute__(base, "__dict__"):
            return False
    for base in type.__getattribute__(ParameterManager, "__mro__"):
        namespace = type.__getattribute__(base, "__dict__")
        if any(name in namespace for name in ("_values", "_descriptors", "_lazy_defaults")):
            return False
    for base in type.__getattribute__(type(indicator), "__mro__"):
        namespace = type.__getattribute__(base, "__dict__")
        if "p" in namespace:
            if namespace["p"] is not _STANDARD_DEVIATION_P_DESCRIPTOR:
                return False
            break
    else:
        return False
    instance = object.__getattribute__(indicator, "__dict__")
    if type(instance) is not dict or any(type(key) is not str for key in instance):
        return False
    params = instance.get("_params_instance")
    if type(params) is not ParameterAccessor:
        return False
    params_state = object.__getattribute__(params, "__dict__")
    if type(params_state) is not dict or any(type(key) is not str for key in params_state):
        return False
    manager = params_state.get("_param_manager")
    if type(manager) is not ParameterManager:
        return False
    state = object.__getattribute__(manager, "__dict__")
    if type(state) is not dict or any(type(key) is not str for key in state):
        return False
    if "get" in state:
        return False
    for name in ("_values", "_descriptors", "_lazy_defaults"):
        mapping = state.get(name)
        if type(mapping) is not dict or any(type(key) is not str for key in mapping):
            return False
    return type(state["_values"].get("safepow")) is bool


def _add_fsum_partial(partials, value):
    """Add a finite float to a non-overlapping exact-sum expansion.

    This is the same error-free high/low decomposition used by ``fsum``.  The
    caller can then remove outgoing rolling-window terms without losing the
    rounded-sum contract of recalculating each window with ``math.fsum``.
    Return false if an intermediate overflow makes the expansion unusable.
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


def _update_fsum_step(partials, outgoing, incoming):
    """Apply ``-outgoing + incoming`` to an exact Shewchuk expansion.

    Uses Knuth TwoSum on ``incoming - outgoing`` so common financial prices
    (Sterbenz range) require only a single expansion update with inline 1/2-term
    fast paths, while falling back to separate exact updates whenever
    ``incoming - outgoing`` has non-zero rounding error.  Returns False if any
    input or intermediate value is non-finite.
    """
    isfinite = math.isfinite
    diff = incoming - outgoing
    v = diff - incoming
    err = (incoming - (diff - v)) + (-outgoing - v)
    if err == 0.0 and isfinite(diff):
        if not diff:
            return True
        n = len(partials)
        if n == 0:
            partials.append(diff)
            return True
        if n == 1:
            x = diff
            p0 = partials[0]
            if abs(x) < abs(p0):
                x, p0 = p0, x
            h0 = x + p0
            if not isfinite(h0):
                return False
            l0 = p0 - (h0 - x)
            if l0:
                partials[0] = l0
                partials.append(h0)
            elif h0:
                partials[0] = h0
            else:
                partials.clear()
            return True
        if n == 2:
            p0 = partials[0]
            p1 = partials[1]
            x = diff
            if abs(x) < abs(p0):
                x, p0 = p0, x
            h0 = x + p0
            if not isfinite(h0):
                return False
            l0 = p0 - (h0 - x)
            x = h0
            if abs(x) < abs(p1):
                x, p1 = p1, x
            h1 = x + p1
            if not isfinite(h1):
                return False
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
            return True
        return _add_fsum_partial(partials, diff)

    return _add_fsum_partial(partials, -outgoing) and _add_fsum_partial(partials, incoming)


class StandardDeviation(Indicator):
    """
    Calculates the standard deviation of the passed data for a given period

    Note:
      - If 2 datas are provided as parameters, the second is considered to be the
        mean of the first

      - ``safepow`` (default: False) If this parameter is True, the standard
        deviation will be calculated as pow (abs(meansq - sqmean), 0.5) to
        safeguard for possible negative results of ``meansq - sqmean`` caused by
        the floating point representation.

    Formula:
      - meansquared = SimpleMovingAverage(pow (data, 2), period)
      - squaredmean = pow(SimpleMovingAverage(data, period), 2)
      - stddev = pow(meansquared - squaredmean, 0.5) # square root

    See:
      - http://en.wikipedia.org/wiki/Standard_deviation
    """

    alias = ("StdDev",)

    lines = ("stddev",)
    params = (
        ("period", 20),
        ("movav", MovAv.Simple),
        ("safepow", True),
    )

    def _plotlabel(self):
        plabels = [self.p.period]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self):
        """Initialize the Standard Deviation indicator."""
        super().__init__()
        self.addminperiod(self.p.period)
        self._use_external_mean = len(self.datas) > 1
        self._mean_prev = None
        self._meansq_prev = None

    def _movav_kind(self):
        movav = self.p.movav
        names = {getattr(movav, "__name__", "")}
        aliases = getattr(movav, "alias", ())
        if isinstance(aliases, str):
            names.add(aliases)
        else:
            names.update(aliases)

        if names.intersection(
            {
                "SmoothedMovingAverage",
                "SMMA",
                "WilderMA",
                "MovingAverageSmoothed",
                "MovingAverageWilder",
                "ModifiedMovingAverage",
                "Smoothed",
            }
        ):
            return "smoothed"

        if names.intersection(
            {"ExponentialMovingAverage", "EMA", "MovingAverageExponential", "Exponential"}
        ):
            return "exponential"

        return "simple"

    def _finish(self, meansq, mean):
        diff = meansq - mean * mean
        if self.p.safepow:
            diff = abs(diff)
        return math.sqrt(max(0.0, diff))

    def _once_simple_fsum(
        self, actual_end, darray, larray, period, mean_array, nan_val, first_index
    ):
        """Retain the original per-window math.fsum calculation as fallback."""
        for i in range(first_index, actual_end):
            start_idx = i - period + 1
            end_idx = i + 1
            window = darray[start_idx:end_idx]
            if len(window) != period or any(value != value for value in window):
                larray[i] = nan_val
                continue

            meansq = math.fsum(value * value for value in window) / period
            if mean_array is not None:
                if i >= len(mean_array) or mean_array[i] != mean_array[i]:
                    larray[i] = nan_val
                    continue
                mean = mean_array[i]
            else:
                mean = math.fsum(window) / period
            larray[i] = self._finish(meansq, mean)

    def _once_legacy_rolling(self, actual_end, darray, larray, period, nan_val):
        """Keep HEAD's rolling and fallback order outside the new fast path."""
        sum_partials = []
        square_partials = []
        for index in range(period):
            value = float(darray[index])
            square = value * value
            if (
                not math.isfinite(value)
                or not math.isfinite(square)
                or not _add_fsum_partial(sum_partials, value)
                or not _add_fsum_partial(square_partials, square)
            ):
                self._once_simple_fsum(
                    actual_end, darray, larray, period, None, nan_val, period - 1
                )
                return

        try:
            total_sq = math.fsum(square_partials)
            total = math.fsum(sum_partials)
        except OverflowError:
            self._once_simple_fsum(actual_end, darray, larray, period, None, nan_val, period - 1)
            return

        for index in range(period - 1, actual_end):
            if index >= period:
                outgoing = float(darray[index - period])
                incoming = float(darray[index])
                outgoing_sq = outgoing * outgoing
                incoming_sq = incoming * incoming
                if (
                    not math.isfinite(outgoing)
                    or not math.isfinite(incoming)
                    or not math.isfinite(outgoing_sq)
                    or not math.isfinite(incoming_sq)
                    or not _add_fsum_partial(sum_partials, -outgoing)
                    or not _add_fsum_partial(sum_partials, incoming)
                    or not _add_fsum_partial(square_partials, -outgoing_sq)
                    or not _add_fsum_partial(square_partials, incoming_sq)
                ):
                    self._once_simple_fsum(actual_end, darray, larray, period, None, nan_val, index)
                    return
                try:
                    total_sq = math.fsum(square_partials)
                    total = math.fsum(sum_partials)
                except OverflowError:
                    self._once_simple_fsum(actual_end, darray, larray, period, None, nan_val, index)
                    return

            larray[index] = self._finish(total_sq / period, total / period)

    def next(self):
        """Calculate standard deviation for the current bar."""
        period = self.p.period
        if len(self) < period:
            self.lines.stddev[0] = float("nan")
            return

        kind = self._movav_kind()
        values = [float(self.data[i]) for i in range(1 - period, 1)]
        if any(value != value for value in values):
            self.lines.stddev[0] = float("nan")
            return

        if kind == "smoothed":
            alpha = 1.0 / period
        elif kind == "exponential":
            alpha = 2.0 / (1.0 + period)
        else:
            alpha = None

        if alpha is None or self._meansq_prev is None:
            meansq = math.fsum(value * value for value in values) / period
        else:
            meansq = (
                self._meansq_prev * (1.0 - alpha)
                + float(self.data[0]) * float(self.data[0]) * alpha
            )

        if self._use_external_mean:
            mean = float(self.data1[0])
        elif alpha is None or self._mean_prev is None:
            mean = math.fsum(values) / period
        else:
            mean = self._mean_prev * (1.0 - alpha) + float(self.data[0]) * alpha

        self._meansq_prev = meansq
        if not self._use_external_mean:
            self._mean_prev = mean

        # Keep an unavailable external mean missing in incremental mode, just
        # as ``once`` does.  Update the smoothed source state first so a later
        # finite mean resumes from the same price-window history.
        if self._use_external_mean and mean != mean:
            self.lines.stddev[0] = float("nan")
            return

        self.lines.stddev[0] = self._finish(meansq, mean)

    def once(self, start, end):
        """Calculate standard deviation in runonce mode."""
        darray = self.data.array
        larray = self.lines.stddev.array
        period = self.p.period
        actual_end = min(end, len(darray))
        nan_val = float("nan")

        while len(larray) < end:
            larray.append(nan_val)

        for i in range(min(period - 1, len(larray), actual_end)):
            larray[i] = nan_val

        if self._use_external_mean:
            if hasattr(self.data1, "once"):
                self.data1.once(0, end)
            mean_array = self.data1.array
        else:
            mean_array = None

        kind = self._movav_kind()
        if kind == "smoothed":
            alpha = 1.0 / period
        elif kind == "exponential":
            alpha = 2.0 / (1.0 + period)
        else:
            alpha = None

        if alpha is None:
            # HEAD performs this comparison even when no fast path is used.
            legacy_long_period = period >= 64
            is_double_array = type(darray) is array.array and darray.typecode == "d"
            plain_safepow = _has_plain_safepow_parameter(self)
            check_fsum = (
                type(period) is int
                and type(_MIN_PERIOD_FOR_ROLLING_STDDEV_ONCE) is int
                and period >= _MIN_PERIOD_FOR_ROLLING_STDDEV_ONCE
                and is_double_array
                and darray is not larray
                and type(actual_end) is int
                and plain_safepow is True
                and mean_array is None
                and actual_end >= period
                and (legacy_long_period or actual_end - (period - 1) >= 4)
                and type(self) is _STANDARD_DEVIATION_CLASS
            )
            native_fsum = not check_fsum or (
                type(math) is type(array)
                and _NATIVE_MATH_BINDINGS
                and all(type(key) is str for key in math.__dict__)
                and math.__dict__.get("fsum") is _ORIGINAL_FSUM
                and math.__dict__.get("sqrt") is _ORIGINAL_SQRT
                and math.__dict__.get("isfinite") is _ORIGINAL_ISFINITE
                and type(__builtins__) is dict
                and all(type(key) is str for key in __builtins__)
                and __builtins__.get("abs") is _ORIGINAL_ABS
            )
            if (
                (
                    not is_double_array
                    or type(period) is not int
                    or type(actual_end) is not int
                    or darray is larray
                    or not plain_safepow
                    or not native_fsum
                    or _STANDARD_DEVIATION_FINISH.__code__ is not _STANDARD_DEVIATION_FINISH_CODE
                )
                and legacy_long_period
                and mean_array is None
                and actual_end >= period
                and type(self) is _STANDARD_DEVIATION_CLASS
                and getattr(getattr(self, "_finish"), "__func__", None)
                is _STANDARD_DEVIATION_FINISH
            ):
                _STANDARD_DEVIATION_LEGACY_ROLLING(
                    self, actual_end, darray, larray, period, nan_val
                )
                return
            # For simple windows at or above the measured crossover, keep exact
            # Shewchuk floating-point expansions for the rolling sum and sum of
            # squares.  This preserves each window's math.fsum result bit-for-bit
            # while avoiding per-bar slicing and dual window scans.  Any window
            # containing non-finite values or overflow falls back to the original
            # per-window path and cleanly re-seeds once those values exit.
            # The original simple-window branch recomputes the complete valid
            # prefix even for a partial once() request. Preserve that contract.
            calc_start = period - 1
            if (
                type(period) is int
                and period >= _MIN_PERIOD_FOR_ROLLING_STDDEV_ONCE
                and is_double_array
                and darray is not larray
                and type(actual_end) is int
                and plain_safepow
                and native_fsum
                and mean_array is None
                and actual_end >= period
                and actual_end - calc_start >= 4
                and type(self) is _STANDARD_DEVIATION_CLASS
                and getattr(getattr(self, "_finish"), "__func__", None)
                is _STANDARD_DEVIATION_FINISH
                and _STANDARD_DEVIATION_FINISH.__code__ is _STANDARD_DEVIATION_FINISH_CODE
            ):
                fsum = math.fsum
                isfinite = math.isfinite
                sqrt = math.sqrt
                sum_partials = None
                square_partials = None
                total = 0.0
                total_sq = 0.0
                index = calc_start

                while index < actual_end:
                    if sum_partials is None:
                        win_start = index - period + 1
                        bad_idx = -1
                        for j in range(index, win_start - 1, -1):
                            val = darray[j] if is_double_array else float(darray[j])
                            if not isfinite(val) or not isfinite(val * val):
                                bad_idx = j
                                break

                        if bad_idx >= 0:
                            fallback_end = min(actual_end, bad_idx + period)
                            self._once_simple_fsum(
                                fallback_end,
                                darray,
                                larray,
                                period,
                                mean_array,
                                nan_val,
                                index,
                            )
                            index = fallback_end
                            continue

                        sum_partials = []
                        square_partials = []
                        overflowed = False
                        for j in range(win_start, index + 1):
                            val = darray[j] if is_double_array else float(darray[j])
                            sq = val * val
                            if not _add_fsum_partial(sum_partials, val) or not _add_fsum_partial(
                                square_partials, sq
                            ):
                                overflowed = True
                                break

                        if not overflowed:
                            try:
                                total = (
                                    sum_partials[0]
                                    if len(sum_partials) == 1
                                    else (fsum(sum_partials) if sum_partials else 0.0)
                                )
                                total_sq = (
                                    square_partials[0]
                                    if len(square_partials) == 1
                                    else (fsum(square_partials) if square_partials else 0.0)
                                )
                            except OverflowError:
                                overflowed = True

                        if overflowed:
                            self._once_simple_fsum(
                                index + 1,
                                darray,
                                larray,
                                period,
                                mean_array,
                                nan_val,
                                index,
                            )
                            sum_partials = None
                            square_partials = None
                            index += 1
                            continue

                        mean = total / period
                        diff_v = total_sq / period - mean * mean
                        if self.p.safepow:
                            diff_v = abs(diff_v)
                        larray[index] = sqrt(diff_v if diff_v > 0.0 else 0.0)
                        index += 1
                        continue

                    while index < actual_end:
                        outgoing = (
                            darray[index - period]
                            if is_double_array
                            else float(darray[index - period])
                        )
                        incoming = darray[index] if is_double_array else float(darray[index])
                        outgoing_sq = outgoing * outgoing
                        incoming_sq = incoming * incoming
                        if (
                            not isfinite(outgoing_sq)
                            or not isfinite(incoming_sq)
                            or not _update_fsum_step(sum_partials, outgoing, incoming)
                            or not _update_fsum_step(square_partials, outgoing_sq, incoming_sq)
                        ):
                            sum_partials = None
                            square_partials = None
                            break

                        try:
                            total = (
                                sum_partials[0]
                                if len(sum_partials) == 1
                                else (fsum(sum_partials) if sum_partials else 0.0)
                            )
                            total_sq = (
                                square_partials[0]
                                if len(square_partials) == 1
                                else (fsum(square_partials) if square_partials else 0.0)
                            )
                        except OverflowError:
                            sum_partials = None
                            square_partials = None
                            break

                        mean = total / period
                        diff_v = total_sq / period - mean * mean
                        if self.p.safepow:
                            diff_v = abs(diff_v)
                        larray[index] = sqrt(diff_v if diff_v > 0.0 else 0.0)
                        index += 1
                return

            # HEAD calculated this general path inline.  In particular, do not
            # call the overridable rolling-fallback hook for custom indicators.
            for i in range(period - 1, actual_end):
                window = darray[i - period + 1 : i + 1]
                if len(window) != period or any(value != value for value in window):
                    larray[i] = nan_val
                    continue

                meansq = math.fsum(value * value for value in window) / period
                if mean_array is not None:
                    if i >= len(mean_array) or mean_array[i] != mean_array[i]:
                        larray[i] = nan_val
                        continue
                    mean = mean_array[i]
                else:
                    mean = math.fsum(window) / period
                larray[i] = self._finish(meansq, mean)
            return

        prev_mean = None
        prev_meansq = None
        # Track missing values in the rolling window without rescanning it.
        nan_count = 0
        if actual_end >= period:
            nan_count = sum(value != value for value in darray[0:period])

        for i in range(period - 1, actual_end):
            if i >= period:
                outgoing = darray[i - period]
                incoming = darray[i]
                nan_count -= outgoing != outgoing
                nan_count += incoming != incoming

            if nan_count:
                # next() leaves the smoothed state untouched while a window
                # contains NaN; retain it so recurrence resumes identically.
                larray[i] = nan_val
                continue

            if prev_meansq is None:
                window = darray[i - period + 1 : i + 1]
                if len(window) != period:
                    larray[i] = nan_val
                    continue
                prev_meansq = math.fsum(value * value for value in window) / period
                if mean_array is None:
                    prev_mean = math.fsum(window) / period
            else:
                value = float(darray[i])
                prev_meansq = prev_meansq * (1.0 - alpha) + value * value * alpha
                if mean_array is None:
                    prev_mean = prev_mean * (1.0 - alpha) + value * alpha

            if mean_array is not None:
                if i >= len(mean_array) or mean_array[i] != mean_array[i]:
                    larray[i] = nan_val
                    continue
                mean = mean_array[i]
            else:
                mean = prev_mean

            larray[i] = self._finish(prev_meansq, mean)


# Pin the definitions that were loaded with this module.  Looking up the class
# or method on ``StandardDeviation`` at call time would let a monkeypatch make
# an overridden _finish appear to be the original fast-path contract.
_STANDARD_DEVIATION_CLASS = StandardDeviation
_STANDARD_DEVIATION_FINISH = StandardDeviation._finish
_STANDARD_DEVIATION_FINISH_CODE = _STANDARD_DEVIATION_FINISH.__code__
_STANDARD_DEVIATION_LEGACY_ROLLING = StandardDeviation._once_legacy_rolling
_STANDARD_DEVIATION_P_DESCRIPTOR = next(
    vars(base)["p"] for base in StandardDeviation.__mro__ if "p" in vars(base)
)
_STANDARD_DEVIATION_DICT_DESCRIPTOR = next(
    vars(base)["__dict__"] for base in StandardDeviation.__mro__ if "__dict__" in vars(base)
)


# Average deviation
class MeanDeviation(Indicator):
    """MeanDeviation (alias MeanDev)

    Calculates the Mean Deviation of the passed data for a given period

    Note:
      - If 2 datas are provided as parameters, the second is considered to be the
        mean of the first

    Formula:
      - mean = MovingAverage(data, period) (or provided mean)
      - absdeviation = abs (data - mean)
      - meandev = MovingAverage(absdeviation, period)

    See:
      - https://en.wikipedia.org/wiki/Average_absolute_deviation
    """

    alias = ("MeanDev",)

    lines = ("meandev",)
    params = (
        ("period", 20),
        ("movav", MovAv.Simple),
    )

    def _plotlabel(self):
        plabels = [self.p.period]
        plabels += [self.p.movav] * self.p.notdefault("movav")
        return plabels

    def __init__(self):
        """Initialize the Mean Deviation indicator.

        Creates the mean deviation calculation using either
        external mean or calculated moving average.
        """
        # CRITICAL: Match master branch behavior
        # If 2 datas are provided, the 2nd is considered to be the mean of the first
        if len(self.datas) > 1:
            mean = self.data1
        else:
            mean = self.p.movav(self.data, period=self.p.period)

        absdev = abs(self.data - mean)
        self.lines.meandev = self.p.movav(absdev, period=self.p.period)


StdDev = StandardDeviation
MeanDev = MeanDeviation
