#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    If,
    Indicator,
    SimpleMovingAverage,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "Color3rdGenXMAIndicator",
]


def resolve_ma_class(name):
    """Map a moving-average name to its backtrader indicator class.

    Args:
        name: MA type name (e.g. ``sma``, ``ema``, ``smma`` or MT5-style
            ``mode_*`` variants); several smoothing variants map to EMA.

    Returns:
        The matching backtrader moving-average indicator class, defaulting to
        the weighted moving average for unrecognized names.
    """
    mode = str(name).lower()
    if mode in {"mode_sma", "sma"}:
        return SimpleMovingAverage
    if mode in {
        "mode_ema",
        "ema",
        "mode_jjma",
        "jjma",
        "mode_jurx",
        "jurx",
        "mode_parma",
        "parma",
        "mode_t3",
        "t3",
        "mode_vidya",
        "vidya",
        "mode_ama",
        "ama",
    }:
        return ExponentialMovingAverage
    if mode in {"mode_smma", "smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


def resolve_price_line(data, mode):
    """Return the applied-price line for a data feed given a price mode.

    Args:
        data: The data feed providing OHLC lines.
        mode: Applied-price selector (e.g. ``price_close``, ``price_typical``,
            ``price_weighted`` or their short forms).

    Returns:
        A line expression for the selected applied price, defaulting to the
        typical price for unrecognized modes.
    """
    price_mode = str(mode).lower()
    if price_mode in {"price_close", "close"}:
        return data.close
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
        return (2.0 * data.close + data.high + data.low) / 4.0
    if price_mode in {"price_simpl", "simpl"}:
        return (data.open + data.close) / 2.0
    if price_mode in {"price_quarter", "quarter"}:
        return (data.high + data.low + data.open + data.close) / 4.0
    return (data.high + data.low + data.close) / 3.0


class Color3rdGenXMAIndicator(Indicator):
    """Third-generation (reduced-lag) moving average with a slope color.

    Combines a base moving average with a re-smoothed version using a
    lambda-derived alpha to cut lag, exposing the resulting line on ``value`` and
    a ``color`` line marking whether it is rising (2), falling (0) or flat (1).
    """

    lines = ("value", "color")
    params = (
        ("xma_method", "ema"),
        ("xlength", 50),
        ("xphase", 15),
        ("ipc", "price_typical"),
        ("price_shift", 0),
    )

    def __init__(self):
        """Build the two-stage moving average and the value/color lines."""
        price = resolve_price_line(self.data, self.p.ipc)
        ma_cls = resolve_ma_class(self.p.xma_method)
        slength = max(1, int(self.p.xlength) * 2)
        self._x1 = ma_cls(price, period=slength)
        self._x2 = ma_cls(self._x1, period=max(1, int(self.p.xlength)))
        lam = float(slength) / max(1.0, float(self.p.xlength))
        self._alpha = lam * (slength - 1.0) / max(1e-9, (slength - lam))
        self._dprice_shift = float(self.p.price_shift) * 0.00001
        value = (self._alpha + 1.0) * self._x1 - self._alpha * self._x2 + self._dprice_shift
        self.lines.value = value
        self.lines.color = If(value > value(-1), 2.0, If(value < value(-1), 0.0, 1.0))
        self.addminperiod(slength + int(self.p.xlength) + 5)
