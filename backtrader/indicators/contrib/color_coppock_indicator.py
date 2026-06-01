#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
    SimpleMovingAverage,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "ColorCoppockIndicator",
]


def resolve_ma_class(name):
    """Map configured MA mode strings to Backtrader MA classes.

    Args:
        name: MA mode token from configuration.

    Returns:
        MA indicator class.
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
    """Resolve a price selector key to a data line for indicator input.

    Args:
        data: Backtrader data feed.
        mode: Price selector token.

    Returns:
        Price series corresponding to the requested selector.
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
        return (2.0 * data.close + data.high + data.low) / 4.0
    if price_mode in {"price_simpl", "simpl"}:
        return (data.open + data.close) / 2.0
    if price_mode in {"price_quarter", "quarter"}:
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class ColorCoppockIndicator(Indicator):
    """Compute Coppock oscillator value and its directional color state."""

    lines = ("value", "color")
    params = (
        ("roc1_period", 14),
        ("roc2_period", 10),
        ("xma_method", "lwma"),
        ("xma_period", 12),
        ("xma_phase", 100),
        ("applied_price", "price_close"),
    )

    def __init__(self):
        """Initialize ROC sum and the final smoothing moving average."""
        price_line = resolve_price_line(self.data, self.p.applied_price)
        roc1 = (price_line - price_line(-int(self.p.roc1_period))) / price_line(
            -int(self.p.roc1_period)
        )
        roc2 = (price_line - price_line(-int(self.p.roc2_period))) / price_line(
            -int(self.p.roc2_period)
        )
        self._roc_sum = roc1 + roc2
        ma_cls = resolve_ma_class(self.p.xma_method)
        self._smooth = ma_cls(self._roc_sum, period=max(1, int(self.p.xma_period)))
        self.addminperiod(
            max(int(self.p.roc1_period), int(self.p.roc2_period)) + int(self.p.xma_period) + 3
        )

    def next(self):
        """Update value and color for the current bar."""
        value = float(self._smooth[0])
        prev = float(self._smooth[-1])
        self.lines.value[0] = value
        color = 2
        if value > 0:
            if value > prev:
                color = 4
            elif value < prev:
                color = 3
        if value < 0:
            if value < prev:
                color = 0
            elif value > prev:
                color = 1
        self.lines.color[0] = color

    def once(self, start, end):
        """Fill value/color lines for preloaded bars in a batch run."""
        smooth = self._smooth.array
        value_line = self.lines.value.array
        color_line = self.lines.color.array
        for line in (value_line, color_line):
            while len(line) < end:
                line.append(float("nan"))

        actual_end = min(end, len(smooth))
        for i in range(start, actual_end):
            value = float(smooth[i])
            prev = float(smooth[i - 1]) if i > 0 else value
            color = 2
            if value > 0:
                if value > prev:
                    color = 4
                elif value < prev:
                    color = 3
            if value < 0:
                if value < prev:
                    color = 0
                elif value > prev:
                    color = 1
            value_line[i] = value
            color_line[i] = color
