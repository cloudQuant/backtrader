#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ADX,
    ExponentialMovingAverage,
    Indicator,
    MinusDirectionalIndicator,
    PlusDirectionalIndicator,
    SimpleMovingAverage,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "SmoothedADXIndicator",
]


def resolve_ma_class(name):
    """Map a moving-average name to its backtrader indicator class.

    Args:
        name: MA type name (e.g. ``t3``, ``ema``, ``sma``, ``smma`` or MT5-style
            ``mode_*`` variants); several smoothing variants map to EMA.

    Returns:
        The matching backtrader moving-average indicator class, defaulting to
        the weighted moving average for unrecognized names.
    """
    mode = str(name).lower()
    if mode in {
        "mode_t3",
        "t3",
        "mode_ema",
        "ema",
        "mode_ama",
        "ama",
        "mode_jjma",
        "jjma",
        "mode_jurx",
        "jurx",
        "mode_vidya",
        "vidya",
        "mode_parma",
        "parma",
    }:
        return ExponentialMovingAverage
    if mode in {"mode_sma", "sma"}:
        return SimpleMovingAverage
    if mode in {"mode_smma", "smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


class SmoothedADXIndicator(Indicator):
    """ADX/DI system with each line smoothed by a configurable moving average.

    Computes raw +DI, -DI and ADX over ``adx_period`` and exposes moving-average
    smoothed versions on the ``plus_di``, ``minus_di`` and ``adx`` lines.
    """

    lines = ("plus_di", "minus_di", "adx")
    params = (
        ("xma_method", "t3"),
        ("adx_period", 14),
        ("adx_phase", 100),
    )

    def __init__(self):
        """Build the raw +DI/-DI/ADX indicators and their smoothed lines."""
        ma_cls = resolve_ma_class(self.p.xma_method)
        self._plus = PlusDirectionalIndicator(self.data, period=max(1, int(self.p.adx_period)))
        self._minus = MinusDirectionalIndicator(self.data, period=max(1, int(self.p.adx_period)))
        self._adx_raw = ADX(self.data, period=max(1, int(self.p.adx_period)))
        self._plus_smooth = ma_cls(self._plus, period=max(1, int(self.p.adx_period)))
        self._minus_smooth = ma_cls(self._minus, period=max(1, int(self.p.adx_period)))
        self._adx_smooth = ma_cls(self._adx_raw, period=max(1, int(self.p.adx_period)))
        self.lines.plus_di = self._plus_smooth
        self.lines.minus_di = self._minus_smooth
        self.lines.adx = self._adx_smooth
        self.addminperiod(int(self.p.adx_period) * 3)
