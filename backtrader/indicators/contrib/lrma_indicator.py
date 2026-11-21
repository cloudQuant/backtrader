#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from ...linebuffer import _factor_context_for_line, _factor_phase
from .. import (
    ExponentialMovingAverage,
    Indicator,
    SimpleMovingAverage,
    SmoothedMovingAverage,
    StandardDeviation,
    WeightedMovingAverage,
)

__all__ = [
    "LRMAIndicator",
    "ChangeOfVolatilityIndicator",
    "VininITrendLRMAIndicator",
]


def resolve_ma_class(name):
    """Map a moving-average method name to a backtrader indicator class.

    Args:
        name: Moving-average method identifier (e.g. ``sma``, ``ema``,
            ``smma``).

    Returns:
        The backtrader moving-average indicator class matching ``name``,
        defaulting to WeightedMovingAverage for unknown names.
    """
    mode = str(name).lower()
    if mode in {"sma", "mode_sma"}:
        return SimpleMovingAverage
    if mode in {
        "ema",
        "mode_ema",
        "ama",
        "mode_ama",
        "jjma",
        "mode_jjma",
        "jurx",
        "mode_jurx",
        "parma",
        "mode_parma",
        "t3",
        "mode_t3",
        "vidya",
        "mode_vidya",
    }:
        return ExponentialMovingAverage
    if mode in {"smma", "mode_smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


def resolve_price_line(data, mode):
    """Select the price line for a given applied-price mode.

    Args:
        data: The data feed exposing open/high/low/close lines.
        mode: Applied-price identifier (e.g. ``price_close``, ``price_median``,
            ``price_typical``, ``price_weighted``).

    Returns:
        The data line or derived line expression for the requested price mode,
        defaulting to the close line.
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


class LRMAIndicator(Indicator):
    """Linear regression moving average projected to the latest bar."""

    lines = ("lrma",)
    params = (("period", 13),)

    def __init__(self):
        """Set the minimum period required before the LRMA can be computed."""
        self.addminperiod(int(self.p.period))

    def next(self):
        """Fit a least-squares line over the window and emit its endpoint."""
        period = int(self.p.period)
        xs = list(range(period))
        ys = [float(self.data[-period + 1 + i]) for i in range(period)]
        mean_x = sum(xs) / period
        context = _factor_context_for_line(self.lines.lrma)
        if context is not None:
            from ...research.strict import reject_infinity

            phase = _factor_phase(context)

            def check(value):
                reject_infinity(context, value, phase, operation=self.lines.lrma)

            running = 0
            for value in ys:
                check(value)
                running += value
                check(running)
        mean_y = sum(ys) / period
        if context is not None:
            check(mean_y)

            def terms():
                running = 0
                for x, y in zip(xs, ys):
                    difference = y - mean_y
                    check(difference)
                    value = (x - mean_x) * difference
                    check(value)
                    running += value
                    check(running)
                    yield value

            num = sum(terms())
            check(num)
        else:
            num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        den = sum((x - mean_x) ** 2 for x in xs)
        slope = num / den if den else 0.0
        if context is not None:
            check(slope)
            check(slope * mean_x)
        intercept = mean_y - slope * mean_x
        result = intercept + slope * (period - 1)
        if context is not None:
            check(intercept)
            check(slope * (period - 1))
            check(result)
        self.lines.lrma[0] = result


class ChangeOfVolatilityIndicator(Indicator):
    """Ratio of short- to long-window momentum dispersion (as a percentage)."""

    lines = ("trend",)
    params = (
        ("mperiod", 1),
        ("short", 6),
        ("long", 100),
    )

    def __init__(self):
        """Build short/long momentum SMAs and standard deviations."""
        period = int(self.p.mperiod)
        momentum = self.data.close - self.data.close(-period)
        self._sma_long = SimpleMovingAverage(momentum, period=max(1, int(self.p.long)))
        self._sma_short = SimpleMovingAverage(
            momentum, period=max(1, int(self.p.short))
        )
        self._std_long = StandardDeviation(momentum, period=max(1, int(self.p.long)))
        self._std_short = StandardDeviation(momentum, period=max(1, int(self.p.short)))
        self.addminperiod(
            int(self.p.mperiod) + max(int(self.p.short), int(self.p.long)) + 3
        )

    def next(self):
        """Emit the short/long volatility ratio scaled to a percentage."""
        long_std = float(self._std_long[0])
        short_std = float(self._std_short[0])
        self.lines.trend[0] = 100.0 * short_std / long_std if long_std else 0.0


class VininITrendLRMAIndicator(Indicator):
    """Trend oscillator scoring LRMA against a fan of moving averages.

    The secondary smoothing method is selected when the indicator is built.
    """

    lines = ("trend",)
    params = (
        ("lrma_period", 13),
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
        """Construct the LRMA, the MA fan, and the output smoother."""
        price_line = resolve_price_line(self.data, self.p.ipc)
        self._lrma = LRMAIndicator(price_line, period=self.p.lrma_period)
        periods = [
            int(self.p.length1 + idx * self.p.ma_step)
            for idx in range(int(self.p.ma_count))
        ]
        ma_cls = resolve_ma_class(self.p.ma_method1)
        self._ma_lines = [ma_cls(self._lrma.lrma, period=max(1, p)) for p in periods]
        # Parameters configure the fan clock and smoothing together at construction.
        self._ma_method2_mode = str(self.p.ma_method2).lower()
        # The new windowed paths revisit fan history by target-feed bars. A fan
        # owned by a multi-feed strategy may otherwise inherit its primary clock.
        # Keep the existing legacy EMA-proxy clock unchanged for compatibility.
        if self._ma_method2_mode in {
            "sma",
            "mode_sma",
            "smma",
            "mode_smma",
            "lwma",
            "mode_lwma",
            "wma",
        }:
            for ma in self._ma_lines:
                ma._clock = self.data
        self.addminperiod(
            int(self.p.lrma_period) + max(periods) + int(self.p.length2) + 5
        )

    def _raw_score(self, ago=0):
        """Return a fan score only when the requested history is complete."""
        lrma_value = float(self._lrma.lrma[-ago])
        ma_values = [float(ma_line[-ago]) for ma_line in self._ma_lines]
        if not math.isfinite(lrma_value) or not all(
            math.isfinite(value) for value in ma_values
        ):
            return float("nan")

        score = 0
        for ma_value in ma_values:
            if lrma_value > ma_value:
                score += 1
            else:
                score -= 1
        return 100.0 * score / max(1, len(self._ma_lines))

    def next(self):
        """Smooth the raw fan score with the explicitly selected classic MA."""
        raw = self._raw_score()
        if not math.isfinite(raw):
            self.lines.trend[0] = float("nan")
            return
        period = max(1, int(self.p.length2))
        mode = self._ma_method2_mode
        if mode in {"sma", "mode_sma", "lwma", "mode_lwma", "wma", "smma", "mode_smma"}:
            prev = float(self.lines.trend[-1]) if len(self) > 0 else float("nan")
            if mode in {"smma", "mode_smma"} and math.isfinite(prev):
                self.lines.trend[0] = (prev * (period - 1) + raw) / period
                return
            scores = [self._raw_score(ago) for ago in range(period - 1, 0, -1)] + [raw]
            if not all(math.isfinite(value) for value in scores):
                self.lines.trend[0] = float("nan")
            elif mode in {"lwma", "mode_lwma", "wma"}:
                self.lines.trend[0] = sum(
                    (index + 1) * value for index, value in enumerate(scores)
                ) / (period * (period + 1) / 2.0)
            else:
                self.lines.trend[0] = sum(scores) / period
            return

        # Existing default JJMA and other legacy aliases remain the EMA proxy.
        alpha = 2.0 / (period + 1.0)
        prev = float(self.lines.trend[-1]) if len(self) > 0 else raw
        if not math.isfinite(prev):
            prev = raw
        self.lines.trend[0] = alpha * raw + (1.0 - alpha) * prev
