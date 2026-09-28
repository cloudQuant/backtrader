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
    "VininITrendIndicator",
]


def resolve_ma_class(name):
    """Resolve MA method identifier to a Backtrader MA class.

    Args:
        name: Method name from configuration.

    Returns:
        Backtrader MA class.
    """
    mode = str(name).lower()
    if mode in {"sma", "mode_sma"}:
        return SimpleMovingAverage
    if mode in {"ema", "mode_ema"}:
        return ExponentialMovingAverage
    if mode in {"smma", "mode_smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


def resolve_price_line(data, mode):
    """Resolve an applied price variant from raw data lines.

    Args:
        data: Backtrader feed or data object.
        mode: Price selector key.

    Returns:
        backtrader line: Selected price series.
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


class VininITrendIndicator(Indicator):
    """Indicator that calculates a smoothed trend score from MA comparisons."""

    lines = ("trend",)
    params = (
        ("ma_method1", "sma"),
        ("length1", 3),
        ("phase1", 15),
        ("ma_step", 10),
        ("ma_count", 10),
        ("ma_method2", "jjma"),
        ("length2", 20),
        ("phase2", 100),
        ("ipc", "price_close"),
    )

    def __init__(self):
        """Build MA lines and required warmup length."""
        price_line = resolve_price_line(self.data, self.p.ipc)
        periods = [
            int(self.p.length1 + idx * self.p.ma_step) for idx in range(int(self.p.ma_count))
        ]
        self._ma_lines = [
            resolve_ma_class(self.p.ma_method1)(price_line, period=max(1, p)) for p in periods
        ]
        self._smooth = resolve_ma_class(self.p.ma_method2)(
            self.lines.trend, period=max(1, int(self.p.length2))
        )
        self.addminperiod(max(periods) + int(self.p.length2) + 5)

    def next(self):
        """Compute trend score and one-step EMA-smoothed trend value."""
        close_value = float(self.data.close[0])
        score = 0
        for ma_line in self._ma_lines:
            if close_value > float(ma_line[0]):
                score += 1
            else:
                score -= 1
        raw = 100.0 * score / max(1, len(self._ma_lines))
        prev = float(self.lines.trend[-1]) if len(self) > 0 else raw
        if prev != prev:
            prev = raw
        period = max(1, int(self.p.length2))
        alpha = 2.0 / (period + 1.0)
        if len(self) == 0:
            self.lines.trend[0] = raw
        else:
            self.lines.trend[0] = alpha * raw + (1.0 - alpha) * prev

    def once(self, start, end):
        """Compute trend values for startup/backfill path."""
        close_array = self.data.close.array
        ma_arrays = [ma_line.array for ma_line in self._ma_lines]
        trend_line = self.lines.trend.array
        while len(trend_line) < end:
            trend_line.append(float("nan"))

        period = max(1, int(self.p.length2))
        alpha = 2.0 / (period + 1.0)
        prev = None
        actual_end = min([end, len(close_array)] + [len(array) for array in ma_arrays])
        for i in range(start, actual_end):
            close_value = float(close_array[i])
            score = 0
            for ma_array in ma_arrays:
                if close_value > float(ma_array[i]):
                    score += 1
                else:
                    score -= 1
            raw = 100.0 * score / max(1, len(ma_arrays))
            value = raw if prev is None else alpha * raw + (1.0 - alpha) * prev
            trend_line[i] = value
            prev = value
