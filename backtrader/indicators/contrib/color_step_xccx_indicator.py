#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    EMA,
    SMA,
    Indicator,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "ColorStepXCCXIndicator",
]


def resolve_ma_class(name):
    """Resolve a moving-average mode name to a Backtrader MA class."""
    mode = str(name).lower()
    if mode in {"sma", "mode_sma"}:
        return SMA
    if mode in {"ema", "mode_ema"}:
        return EMA
    if mode in {"smma", "mode_smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


def resolve_price_line(data, mode):
    """Return the selected price series from data for indicator calculations.

    Args:
        data: Backtrader data feed.
        mode: Price selector token from strategy configuration.

    Returns:
        A Backtrader data line used as input to indicators.
    """
    price_mode = str(mode).lower()
    if price_mode in {"price_open", "open"}:
        return data.open
    if price_mode in {"price_high", "high"}:
        return data.high
    if price_mode in {"price_low", "low"}:
        return data.low
    if price_mode in {"price_median", "median"}:
        return (data.high + data.low) / 2.0
    if price_mode in {"price_typical", "typical"}:
        return (data.high + data.low + data.close) / 3.0
    if price_mode in {"price_weighted", "weighted"}:
        return (data.high + data.low + data.close + data.close) / 4.0
    return data.close


def _advance_channels(
    xccx,
    fmin1,
    fmax1,
    smin1,
    smax1,
    ftrend,
    strend,
    fast_step,
    slow_step,
):
    """Advance channel state using one finite oscillator value.

    The first real value seeds the channel bounds, but cannot establish a
    direction because there is no prior channel to cross.  ``None`` denotes
    unseeded state; output lines remain NaN until a later value crosses a
    seeded bound.
    """
    fmax0 = xccx + 2.0 * fast_step
    fmin0 = xccx - 2.0 * fast_step
    smax0 = xccx + 2.0 * slow_step
    smin0 = xccx - 2.0 * slow_step

    if fmin1 is None:
        return (
            fmin0,
            fmax0,
            smin0,
            smax0,
            ftrend,
            strend,
            float("nan"),
            float("nan"),
        )

    if xccx > fmax1:
        ftrend = 1
    if xccx < fmin1:
        ftrend = -1
    if ftrend > 0 and fmin0 < fmin1:
        fmin0 = fmin1
    if ftrend < 0 and fmax0 > fmax1:
        fmax0 = fmax1

    if xccx > smax1:
        strend = 1
    if xccx < smin1:
        strend = -1
    if strend > 0 and smin0 < smin1:
        smin0 = smin1
    if strend < 0 and smax0 > smax1:
        smax0 = smax1

    mplus = float("nan")
    if ftrend > 0:
        mplus = fmin0 + fast_step
    elif ftrend < 0:
        mplus = fmax0 - fast_step

    mminus = float("nan")
    if strend > 0:
        mminus = smin0 + slow_step
    elif strend < 0:
        mminus = smax0 - slow_step

    return fmin0, fmax0, smin0, smax0, ftrend, strend, mplus, mminus


class ColorStepXCCXIndicator(Indicator):
    """Compute fast/slow XCCX channel lines for directional step signals."""

    lines = (
        "mplus",
        "mminus",
    )
    params = (
        ("dsmooth_method", "jjma"),
        ("dperiod", 30),
        ("dphase", 100),
        ("msmooth_method", "t3"),
        ("mperiod", 7),
        ("mphase", 15),
        ("ipc", "price_typical"),
        ("step_size_fast", 5),
        ("step_size_slow", 30),
    )

    def __init__(self):
        """Initialize smoothed base/offset series and running channel states."""
        price_line = resolve_price_line(self.data, self.p.ipc)
        self._base = resolve_ma_class(self.p.dsmooth_method)(price_line, period=self.p.dperiod)
        self._up = resolve_ma_class(self.p.msmooth_method)(
            price_line - self._base, period=self.p.mperiod
        )
        self._dn = resolve_ma_class(self.p.msmooth_method)(
            abs(price_line - self._base), period=self.p.mperiod
        )
        self._fmin1 = None
        self._fmax1 = None
        self._smin1 = None
        self._smax1 = None
        self._ftrend = 0
        self._strend = 0
        self._once_next = None
        self.addminperiod(self.p.dperiod + self.p.mperiod + 5)

    def next(self):
        """Update fast and slow channel lines on the next bar."""
        self.lines.mplus[0], self.lines.mminus[0] = self._advance_oscillator(
            float(self._up[0]), float(self._dn[0])
        )

    def prenext(self):
        """Seed/update state from valid warm-up values without publishing it."""
        self._advance_oscillator(float(self._up[0]), float(self._dn[0]))

    def preonce(self, start, end):
        """Advance warm-up state while leaving output buffers unavailable."""
        up_array = self._up.array
        dn_array = self._dn.array
        actual_end = min(end, len(up_array), len(dn_array))
        for index in range(start, actual_end):
            self._advance_oscillator(float(up_array[index]), float(dn_array[index]))
        self._once_next = end

    def _advance_oscillator(self, xupccx, xdnccx):
        """Advance state for one valid oscillator sample or preserve it."""
        if (
            not math.isfinite(xupccx)
            or not math.isfinite(xdnccx)
            or xdnccx <= 0.0
        ):
            return float("nan"), float("nan")

        xccx = 100.0 * xupccx / xdnccx
        if not math.isfinite(xccx):
            return float("nan"), float("nan")

        (
            self._fmin1,
            self._fmax1,
            self._smin1,
            self._smax1,
            self._ftrend,
            self._strend,
            mplus,
            mminus,
        ) = _advance_channels(
            xccx,
            self._fmin1,
            self._fmax1,
            self._smin1,
            self._smax1,
            self._ftrend,
            self._strend,
            float(self.p.step_size_fast),
            float(self.p.step_size_slow),
        )
        return mplus, mminus

    def once(self, start, end):
        """Compute channel lines for vectorized/cached bars from `start` to `end`."""
        up_array = self._up.array
        dn_array = self._dn.array
        mplus_line = self.lines.mplus.array
        mminus_line = self.lines.mminus.array
        for line in (mplus_line, mminus_line):
            while len(line) < end:
                line.append(float("nan"))

        if start == 0:
            self._fmin1 = None
            self._fmax1 = None
            self._smin1 = None
            self._smax1 = None
            self._ftrend = 0
            self._strend = 0
            self._once_next = 0
        elif self._once_next is not None and start != self._once_next:
            raise ValueError("ColorStepXCCX once() ranges must be contiguous")

        fast_step = float(self.p.step_size_fast)
        slow_step = float(self.p.step_size_slow)
        actual_end = min(end, len(up_array), len(dn_array))
        for i in range(start, actual_end):
            xupccx = float(up_array[i])
            xdnccx = float(dn_array[i])
            if (
                not math.isfinite(xupccx)
                or not math.isfinite(xdnccx)
                or xdnccx <= 0.0
            ):
                mplus_line[i] = float("nan")
                mminus_line[i] = float("nan")
                continue

            xccx = 100.0 * xupccx / xdnccx
            if not math.isfinite(xccx):
                mplus_line[i] = float("nan")
                mminus_line[i] = float("nan")
                continue

            (
                self._fmin1,
                self._fmax1,
                self._smin1,
                self._smax1,
                self._ftrend,
                self._strend,
                mplus_line[i],
                mminus_line[i],
            ) = _advance_channels(
                xccx,
                self._fmin1,
                self._fmax1,
                self._smin1,
                self._smax1,
                self._ftrend,
                self._strend,
                fast_step,
                slow_step,
            )

        self._once_next = end
