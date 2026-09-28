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
    "CandlesXSmoothedIndicator",
]


def resolve_ma_class(name):
    """Resolve moving-average strategy by string key.

    Args:
        name (str): MA method key from config.

    Returns:
        indicator: Corresponding Backtrader MA class.
    """
    mode = str(name).lower()
    if mode in {"sma", "mode_sma"}:
        return SMA
    if mode in {"ema", "mode_ema"}:
        return EMA
    if mode in {"smma", "mode_smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


class CandlesXSmoothedIndicator(Indicator):
    """Indicator that smooths OHLC bars with configurable MA and derives color state."""

    lines = (
        "smooth_open",
        "smooth_high",
        "smooth_low",
        "smooth_close",
        "color_state",
    )
    params = (
        ("ma_method", "lwma"),
        ("ma_length", 30),
        ("ma_phase", 100),
    )

    def __init__(self):
        """Initialize all smoothed OHLC lines and color state."""
        ma_cls = resolve_ma_class(self.p.ma_method)
        self.lines.smooth_open = ma_cls(self.data.open, period=self.p.ma_length)
        self.lines.smooth_high = ma_cls(self.data.high, period=self.p.ma_length)
        self.lines.smooth_low = ma_cls(self.data.low, period=self.p.ma_length)
        self.lines.smooth_close = ma_cls(self.data.close, period=self.p.ma_length)
        self.addminperiod(self.p.ma_length + 2)

    def next(self):
        """Set color state to bullish (`0`) or bearish (`1`) for current bar."""
        self.lines.color_state[0] = (
            0.0 if float(self.lines.smooth_open[0]) < float(self.lines.smooth_close[0]) else 1.0
        )
