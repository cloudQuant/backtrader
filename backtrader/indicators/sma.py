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
import math
import sys
import types

from ..utils.log_message import get_logger
from .mabase import MovingAverageBase

logger = get_logger(__name__)
_MIN_PERIOD_FOR_ROLLING_ONCE = 32
_ORIGINAL_FSUM = math.fsum
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
