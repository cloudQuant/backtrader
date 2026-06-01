#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from collections import deque

import pandas as pd

from .. import (
    EMA,
    SMA,
    Indicator,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "LinearRegSlopeV2Indicator",
]


def resolve_ma_class(name):
    """Resolve a human-readable moving-average mode name to a Backtrader class.

    Args:
        name: Strategy parameter value such as ``sma``, ``ema``, or ``smma``.

    Returns:
        The matching Backtrader moving-average indicator class.
    """
    mode = str(name).lower()
    if mode in {"sma", "mode_sma"}:
        return SMA
    if mode in {"ema", "mode_ema"}:
        return EMA
    if mode in {"smma", "mode_smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


def resolve_price_line(data, mode):
    """Resolve an abstract price mode name to a concrete price series line.

    Args:
        data: A Backtrader data feed exposing OHLCV lines.
        mode: Price selector such as ``price_close``, ``price_open``, etc.

    Returns:
        A line-like object representing the selected price calculation.
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
    if price_mode in {"price_simpl", "simpl"}:
        return (data.open + data.close) / 2.0
    if price_mode in {"price_quarter", "quarter"}:
        return (data.high + data.low + data.open + data.close) / 4.0
    if price_mode in {"price_trendfollow0", "trendfollow0"}:
        return (data.high + data.low + data.close + data.close) / 4.0
    if price_mode in {"price_trendfollow1", "trendfollow1"}:
        return (data.high + data.low + data.open + data.close + data.close) / 5.0
    return data.close


class LinearRegSlopeV2Indicator(Indicator):
    """Indicator that computes a linear-regression slope proxy and trigger line."""

    lines = (
        "reg_slope",
        "trigger",
    )
    params = (
        ("sl_method", "sma"),
        ("sl_length", 12),
        ("sl_phase", 15),
        ("ipc", "price_close"),
        ("trigger_shift", 1),
    )

    def __init__(self):
        """Initialize smoothing, regression buffers, and phase-shift settings."""
        ma_cls = resolve_ma_class(self.p.sl_method)
        price_line = resolve_price_line(self.data, self.p.ipc)
        self.smooth = ma_cls(price_line, period=self.p.sl_length)
        self._window = deque(maxlen=self.p.sl_length)
        self._sum_x = self.p.sl_length * (self.p.sl_length - 1) * 0.5
        sum_x_sqr = (
            (self.p.sl_length - 1.0) * self.p.sl_length * (2.0 * self.p.sl_length - 1.0) / 6.0
        )
        self._divisor = self._sum_x * self._sum_x - self.p.sl_length * sum_x_sqr
        if self.p.trigger_shift > self.p.sl_length - 2:
            self._trig_shift = 1
            self._trig_shift_back = self.p.sl_length - 2
        else:
            self._trig_shift = self.p.sl_length - 1 - self.p.trigger_shift
            self._trig_shift_back = self.p.trigger_shift
        self.addminperiod(self.p.sl_length + self.p.trigger_shift + 3)

    def next(self):
        """Update one bar of regression slope and trigger calculations."""
        self._window.appendleft(float(self.smooth[0]))
        if len(self._window) < self.p.sl_length:
            self.lines.reg_slope[0] = float("nan")
            self.lines.trigger[0] = float("nan")
            return
        sum_y = sum(self._window[i] for i in range(self.p.sl_length))
        sum_xy = sum(i * self._window[i] for i in range(self.p.sl_length))
        slope = (
            (self.p.sl_length * sum_xy - self._sum_x * sum_y) / self._divisor
            if self._divisor
            else float("nan")
        )
        intercept = (sum_y - slope * self._sum_x) / self.p.sl_length
        reg_value = intercept + slope * self._trig_shift
        self.lines.reg_slope[0] = reg_value
        if len(self) > self._trig_shift_back and not pd.isna(
            self.lines.reg_slope[-self._trig_shift_back]
        ):
            self.lines.trigger[0] = 2.0 * reg_value - float(
                self.lines.reg_slope[-self._trig_shift_back]
            )
        else:
            self.lines.trigger[0] = float("nan")
