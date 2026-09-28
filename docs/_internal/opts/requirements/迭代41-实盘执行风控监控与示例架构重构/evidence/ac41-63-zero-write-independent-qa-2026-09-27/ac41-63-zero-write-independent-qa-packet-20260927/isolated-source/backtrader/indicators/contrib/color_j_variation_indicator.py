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
    "ColorJVariationIndicator",
]


def resolve_ma_class(name):
    """Resolve a moving-average name to Backtrader MA class."""
    mode = str(name).lower()
    if mode in {"sma", "mode_sma"}:
        return SMA
    if mode in {"ema", "mode_ema"}:
        return EMA
    if mode in {"smma", "mode_smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


class ColorJVariationIndicator(Indicator):
    """Indicator deriving a custom color variation series from MA residuals."""

    lines = ("value",)
    params = (
        ("period_", 12),
        ("ma_method_", "sma"),
        ("jlength_", 3),
        ("jphase_", 100),
    )

    def __init__(self):
        """Build nested moving averages and assign EMA-smoothed output line."""
        ma_cls = resolve_ma_class(self.p.ma_method_)
        ma1 = ma_cls(self.data.close, period=self.p.period_)
        residual1 = self.data.close - ma1
        ma2 = ma_cls(residual1, period=self.p.period_)
        residual2 = self.data.close - ma1 - ma2
        ma3 = ma_cls(residual2, period=self.p.period_)
        self.lines.value = EMA(ma3, period=max(1, int(self.p.jlength_)))
        self.addminperiod(self.p.period_ * 3 + self.p.jlength_ + 5)
