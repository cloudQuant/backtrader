#!/usr/bin/env python
"""SMA Indicator Module - Simple Moving Average.

This module provides the SMA (Simple Moving Average) indicator for
calculating the non-weighted average of the last n periods.

Classes:
    MovingAverageSimple: SMA indicator (alias: SMA).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=20)

        def next(self):
            if self.data.close[0] > self.sma[0]:
                self.buy()
            elif self.data.close[0] < self.sma[0]:
                self.sell()
"""

import array
import builtins
import math
import sys
import types

from ..utils.log_message import get_logger
from .mabase import MovingAverageBase

logger = get_logger(__name__)
_MIN_PERIOD_FOR_ROLLING_ONCE = 32
_ORIGINAL_FSUM = math.fsum
_ORIGINAL_MATH = math
_ORIGINAL_ISFINITE = math.__dict__.get("isfinite") if type(math) is types.ModuleType else None
_ORIGINAL_FREXP = math.__dict__.get("frexp") if type(math) is types.ModuleType else None
_ORIGINAL_ABS = builtins.__dict__.get("abs") if type(builtins) is types.ModuleType else None
_ORIGINAL_BUILTINS = builtins
_ORIGINAL_SYS = sys
_ORIGINAL_FLOAT_INFO = vars(sys).get("float_info") if type(sys) is types.ModuleType else None
_FLOAT_INFO_TYPE = type(_ORIGINAL_FLOAT_INFO)
_FLOAT_INFO_FLAGS = getattr(_FLOAT_INFO_TYPE, "__flags__", None) if type(_FLOAT_INFO_TYPE) is type else None
_ORIGINAL_FLOAT_INFO_IS_NATIVE = (
    type(_FLOAT_INFO_FLAGS) is int
    and not (_FLOAT_INFO_FLAGS & (1 << 9))
    and _FLOAT_INFO_TYPE.__module__ == "sys"
    and _FLOAT_INFO_TYPE.__name__ == "float_info"
)
_ORIGINAL_MIN_NORMAL = _ORIGINAL_FLOAT_INFO.min if _ORIGINAL_FLOAT_INFO_IS_NATIVE else None
_ORIGINAL_FSUM_IS_NATIVE = (
    type(_ORIGINAL_FSUM) is types.BuiltinFunctionType
    and _ORIGINAL_FSUM.__module__ == "math"
    and _ORIGINAL_FSUM.__name__ == "fsum"
)


def _add_fsum_partial(partials, value):
    """Add a finite float to a non-overlapping Shewchuk exact-sum expansion."""
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


_ORIGINAL_ADD_PARTIAL = _add_fsum_partial
_ORIGINAL_ADD_PARTIAL_CODE = _add_fsum_partial.__code__


def _sma_window_fsum(src, dst, index, period, fsum, nan_val):
    """Compute one SMA bar with exact ``math.fsum`` and legacy NaN semantics."""
    window = src[index - period + 1 : index + 1]
    # Check the entire window first: fsum can overflow before reaching a NaN.
    if any(v != v for v in window):
        dst[index] = nan_val
    else:
        dst[index] = fsum(window) / period


def _once_exact_sma(src, dst, calc_start, actual_end, period, nan_val):
    """Calculate rolling SMA over ``array('d')`` using an exact Shewchuk sum.

    Preserves bit-exact parity with ``math.fsum(window) / period`` on all
    finite windows, falls back to exact per-window ``math.fsum`` while any
    non-finite value or overflow is inside the window, and cleanly re-seeds
    once those values exit the window.
    """
    # once() only enters this path when its captured binding is this object.
    # Do not reread math.fsum: it can change after once() captured it.
    fsum = _ORIGINAL_FSUM
    isfinite = math.isfinite
    # Rolling updates can bypass order-dependent fsum intermediate overflow.
    # Near the float limit, retain the original ordered window calculation.
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
                    _sma_window_fsum(src, dst, k, period, fsum, nan_val)
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
                _sma_window_fsum(src, dst, i, period, fsum, nan_val)
                partials = None
                i += 1
                continue

            dst[i] = cur / period
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

            dst[i] = cur / period
            i += 1


_ORIGINAL_ONCE_EXACT_SMA = _once_exact_sma
_ORIGINAL_ONCE_EXACT_SMA_CODE = _once_exact_sma.__code__


def _once_integer_sma(src, dst, start, end, period):
    """Try exact fixed-point prefix sums on a bounded native NumPy segment.

    The fast path is optional: values must share an exact binary scale and
    every chunk's worst-case absolute sum must fit in signed int64.  Otherwise
    no output is written and the ordinary exact rolling implementation runs.
    """
    modules = vars(sys).get("modules")
    if type(modules) is not dict:
        return False
    np = modules.get("numpy")
    if type(np) is not types.ModuleType:
        return False
    namespace = vars(np)
    # Match public NumPy bindings to the already loaded native core. Merely
    # checking names and a replaceable np.ufunc type admits Python wrappers.
    core = modules.get("numpy._core._multiarray_umath")
    if core is None:
        core = modules.get("numpy.core._multiarray_umath")
    if type(core) is not types.ModuleType:
        return False
    native = vars(core)
    ufunc = namespace.get("ufunc")
    add = native.get("add")
    if type(ufunc) is not type or type(add) is not ufunc:
        return False
    flags = getattr(ufunc, "__flags__", None)
    if (
        type(flags) is not int
        or flags & (1 << 9)  # native static type, not a Python heap type
        or ufunc.__module__ != "numpy"
        or ufunc.__name__ != "ufunc"
        or add.__name__ != "add"
    ):
        return False
    funcs = {name: namespace.get(name) for name in ("ldexp", "isfinite", "trunc", "absolute")}
    for name, func in funcs.items():
        if type(func) is not ufunc or native.get(name) is not func:
            return False
    # Explicit native ufuncs avoid NumPy 1.x set_numeric_ops hooks.
    for name in ("not_equal", "less", "logical_and", "equal", "subtract", "true_divide"):
        func = native.get(name)
        if type(func) is not ufunc or func.__name__ != ("divide" if name == "true_divide" else name):
            return False
        funcs[name] = func
    frombuffer = namespace.get("frombuffer")
    dtype = native.get("dtype")
    f64 = namespace.get("float64")
    i64 = namespace.get("int64")
    if (
        type(frombuffer) is not types.BuiltinFunctionType
        or native.get("frombuffer") is not frombuffer
        or frombuffer.__name__ != "frombuffer"
        or frombuffer.__module__ != "numpy"
        or dtype is not namespace.get("dtype")
        or dtype is None
        or f64 is not dtype("float64").type
        or i64 is not dtype("int64").type
    ):
        return False
    src_start = start - period + 1
    if end - src_start > 250000:
        return False
    try:
        values = frombuffer(src, dtype=f64)[src_start:end]
        if not funcs["isfinite"](values).all():
            return False
        absolute = funcs["absolute"](values)
        # Avoid introducing NumPy underflow warnings or callbacks where the
        # original scalar path has none. Subnormal input stays on that path.
        if funcs["logical_and"](
            funcs["not_equal"](absolute, 0.0),
            funcs["less"](absolute, _ORIGINAL_MIN_NORMAL),
        ).any():
            return False
        maximum = float(absolute.max())
        scale = 53 - math.frexp(maximum)[1] if maximum else 0
        if scale < 0:
            scale = 0
        # With at most 250000 inputs, scale <= 960 also keeps every nonzero
        # reconstructed mean normal; smaller values use the original path.
        if scale > 960:
            return False
        scaled = funcs["ldexp"](values, scale)
        if not funcs["isfinite"](scaled).all() or not funcs["equal"](scaled, funcs["trunc"](scaled)).all():
            return False
        peak = int(funcs["absolute"](scaled).max())
        limit = ((1 << 63) - 1) // peak if peak else 8192 + period
        chunk = limit - period + 1
        if chunk > 8192:
            chunk = 8192
        if chunk < 256:
            return False
        integers = scaled.astype(i64)
        out = array.array("d")
        for offset in range(0, end - start, chunk):
            count = end - start - offset
            if count > chunk:
                count = chunk
            prefix = add.accumulate(integers[offset : offset + count + period - 1], dtype=i64)
            totals = prefix[period - 1 :].copy()
            funcs["subtract"](totals[1:], prefix[:-period], out=totals[1:])
            means = funcs["true_divide"](funcs["ldexp"](totals.astype(f64), -scale), period)
            out.frombytes(means.tobytes())
        if len(out) != end - start:
            return False
        dst[start:end] = out
        return True
    except (ArithmeticError, ValueError, TypeError, MemoryError):
        return False


# Moving average indicator
class MovingAverageSimple(MovingAverageBase):
    """
    Non-weighted average of the last n periods

    Formula:
      - movav = Sum(data, period) / period

    See also:
      - http://en.wikipedia.org/wiki/Moving_average#Simple_moving_average
    """

    alias = (
        "SMA",
        "SimpleMovingAverage",
    )
    lines = ("sma",)

    def __init__(self):
        """Initialize the SMA indicator."""
        # Before super to ensure mixins (right-hand side in subclassing)
        # can see the assignment operation and operate on the line
        super().__init__()
        self._period = self.p.period
        self._next_offsets = tuple(range(1 - self._period, 1))
        data = getattr(self, "data", None)
        self._data_getitem = data.__getitem__ if data is not None else None
        self._data_get = data.get if data is not None else None
        self._sma_line = self.lines.sma
        self._fsum = math.fsum

    def nextstart(self):
        """Initialize on first call after minperiod is met."""
        # Delegate to next() — at this point we have exactly enough data
        self.next()

    def next(self):
        """Calculate SMA for the current bar.

        Recalculates from scratch each bar using sum of the last 'period'
        values to avoid floating-point drift from incremental updates.
        """
        try:
            data_get = self._data_get
            if data_get is None:
                data = self.data
                data_get = data.get
                self._data_get = data_get
                self._data_getitem = data.__getitem__

            prices = data_get(size=self._period)
            if len(prices) != self._period:
                data_getitem = self._data_getitem
                if data_getitem is None:
                    data_getitem = self.data.__getitem__
                    self._data_getitem = data_getitem
                prices = [float(data_getitem(i)) for i in self._next_offsets]
            self._sma_line[0] = self._fsum(prices) / self._period
        except (AttributeError, ValueError, TypeError, IndexError):
            logger.debug("SMA next() failed", exc_info=True)
            self._sma_line[0] = float("nan")

    def once(self, start, end):
        """Batch calculation for runonce mode."""
        try:
            # If data source is a LinesOperation, ensure its once() is called first
            if hasattr(self.data, "once") and hasattr(self.data, "operation"):
                try:
                    self.data.once(start, end)
                except Exception as e:
                    logger.debug("data.once() failed in SMA: %s", e)

            dst = self.lines[0].array
            src = self.data.array
            period = self.p.period
            actual_end = min(end, len(src))

            # Ensure destination array is large enough, pre-fill with NaN
            while len(dst) < end:
                dst.append(float("nan"))

            # Pre-fill warmup period with NaN
            for i in range(min(period - 1, len(src))):
                dst[i] = float("nan")

            calc_start = max(period - 1, start)
            fsum = math.fsum  # Cache function reference
            nan_val = float("nan")

            if (
                type(period) is int
                and period >= _MIN_PERIOD_FOR_ROLLING_ONCE
                and type(start) is int
                and type(end) is int
                and start >= 0
                and end >= 0
                and actual_end - calc_start >= 4
                and fsum is _ORIGINAL_FSUM
                and _ORIGINAL_FSUM_IS_NATIVE
                and type(src) is array.array
                and src.typecode == "d"
                and type(dst) is array.array
                and dst.typecode == "d"
                and src is not dst
            ):
                if (
                    period >= 256
                    and actual_end - calc_start >= 1024
                    and sys is _ORIGINAL_SYS
                    and type(sys) is types.ModuleType
                    and _ORIGINAL_FLOAT_INFO_IS_NATIVE
                    and vars(sys).get("float_info") is _ORIGINAL_FLOAT_INFO
                    and type(vars(sys).get("modules")) is dict
                    and math is _ORIGINAL_MATH
                    and type(math) is types.ModuleType
                    and math.__dict__.get("isfinite") is _ORIGINAL_ISFINITE
                    and math.__dict__.get("frexp") is _ORIGINAL_FREXP
                    and type(_ORIGINAL_ISFINITE) is types.BuiltinFunctionType
                    and _ORIGINAL_ISFINITE.__module__ == "math"
                    and _ORIGINAL_ISFINITE.__name__ == "isfinite"
                    and type(_ORIGINAL_FREXP) is types.BuiltinFunctionType
                    and _ORIGINAL_FREXP.__module__ == "math"
                    and _ORIGINAL_FREXP.__name__ == "frexp"
                    and builtins is _ORIGINAL_BUILTINS
                    and type(builtins) is types.ModuleType
                    and builtins.__dict__.get("abs") is _ORIGINAL_ABS
                    and globals().get("abs", _ORIGINAL_ABS) is _ORIGINAL_ABS
                    and type(_ORIGINAL_ABS) is types.BuiltinFunctionType
                    and _ORIGINAL_ABS.__module__ == "builtins"
                    and _ORIGINAL_ABS.__name__ == "abs"
                    and _add_fsum_partial is _ORIGINAL_ADD_PARTIAL
                    and _add_fsum_partial.__code__ is _ORIGINAL_ADD_PARTIAL_CODE
                    and _once_exact_sma is _ORIGINAL_ONCE_EXACT_SMA
                    and _once_exact_sma.__code__ is _ORIGINAL_ONCE_EXACT_SMA_CODE
                    and _once_integer_sma(src, dst, calc_start, actual_end, period)
                ):
                    return
                _once_exact_sma(src, dst, calc_start, actual_end, period, nan_val)
                return

            for i in range(calc_start, actual_end):
                end_idx = i + 1
                if end_idx <= len(src):
                    _sma_window_fsum(src, dst, i, period, fsum, nan_val)
                else:
                    dst[i] = nan_val
        except Exception:
            logger.debug("SMA once() failed, falling back to once_via_next", exc_info=True)
            super().once_via_next(start, end)


SMA = MovingAverageSimple
