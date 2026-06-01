#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

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
        self._fmin1 = 999999.0
        self._fmax1 = -999999.0
        self._smin1 = 999999.0
        self._smax1 = -999999.0
        self._ftrend = 0
        self._strend = 0
        self.addminperiod(self.p.dperiod + self.p.mperiod + 5)

    def next(self):
        """Update fast and slow channel lines on the next bar."""
        xupccx = float(self._up[0])
        xdnccx = float(self._dn[0])
        xccx = 100.0 * xupccx / xdnccx if xupccx != 0.0 and xdnccx != 0.0 else 0.0
        fmax0 = xccx + 2 * float(self.p.step_size_fast)
        fmin0 = xccx - 2 * float(self.p.step_size_fast)
        if xccx > self._fmax1:
            self._ftrend = 1
        if xccx < self._fmin1:
            self._ftrend = -1
        if self._ftrend > 0 and fmin0 < self._fmin1:
            fmin0 = self._fmin1
        if self._ftrend < 0 and fmax0 > self._fmax1:
            fmax0 = self._fmax1
        smax0 = xccx + 2 * float(self.p.step_size_slow)
        smin0 = xccx - 2 * float(self.p.step_size_slow)
        if xccx > self._smax1:
            self._strend = 1
        if xccx < self._smin1:
            self._strend = -1
        if self._strend > 0 and smin0 < self._smin1:
            smin0 = self._smin1
        if self._strend < 0 and smax0 > self._smax1:
            smax0 = self._smax1
        self.lines.mplus[0] = (
            fmin0 + float(self.p.step_size_fast)
            if self._ftrend > 0
            else fmax0 - float(self.p.step_size_fast)
        )
        self.lines.mminus[0] = (
            smin0 + float(self.p.step_size_slow)
            if self._strend > 0
            else smax0 - float(self.p.step_size_slow)
        )
        self._fmin1 = fmin0
        self._fmax1 = fmax0
        self._smin1 = smin0
        self._smax1 = smax0

    def once(self, start, end):
        """Compute channel lines for vectorized/cached bars from `start` to `end`."""
        up_array = self._up.array
        dn_array = self._dn.array
        mplus_line = self.lines.mplus.array
        mminus_line = self.lines.mminus.array
        for line in (mplus_line, mminus_line):
            while len(line) < end:
                line.append(float("nan"))

        fmin1 = 999999.0
        fmax1 = -999999.0
        smin1 = 999999.0
        smax1 = -999999.0
        ftrend = 0
        strend = 0
        fast_step = float(self.p.step_size_fast)
        slow_step = float(self.p.step_size_slow)
        actual_end = min(end, len(up_array), len(dn_array))
        for i in range(start, actual_end):
            xupccx = float(up_array[i])
            xdnccx = float(dn_array[i])
            xccx = 100.0 * xupccx / xdnccx if xupccx != 0.0 and xdnccx != 0.0 else 0.0
            fmax0 = xccx + 2.0 * fast_step
            fmin0 = xccx - 2.0 * fast_step
            if xccx > fmax1:
                ftrend = 1
            if xccx < fmin1:
                ftrend = -1
            if ftrend > 0 and fmin0 < fmin1:
                fmin0 = fmin1
            if ftrend < 0 and fmax0 > fmax1:
                fmax0 = fmax1

            smax0 = xccx + 2.0 * slow_step
            smin0 = xccx - 2.0 * slow_step
            if xccx > smax1:
                strend = 1
            if xccx < smin1:
                strend = -1
            if strend > 0 and smin0 < smin1:
                smin0 = smin1
            if strend < 0 and smax0 > smax1:
                smax0 = smax1

            mplus_line[i] = fmin0 + fast_step if ftrend > 0 else fmax0 - fast_step
            mminus_line[i] = smin0 + slow_step if strend > 0 else smax0 - slow_step
            fmin1 = fmin0
            fmax1 = fmax0
            smin1 = smin0
            smax1 = smax0

        self._fmin1 = fmin1
        self._fmax1 = fmax1
        self._smin1 = smin1
        self._smax1 = smax1
        self._ftrend = ftrend
        self._strend = strend
