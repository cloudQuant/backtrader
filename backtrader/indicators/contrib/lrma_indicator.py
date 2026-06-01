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
        mean_y = sum(ys) / period
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        den = sum((x - mean_x) ** 2 for x in xs)
        slope = num / den if den else 0.0
        intercept = mean_y - slope * mean_x
        self.lines.lrma[0] = intercept + slope * (period - 1)


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
        self._sma_short = SimpleMovingAverage(momentum, period=max(1, int(self.p.short)))
        self._std_long = StandardDeviation(momentum, period=max(1, int(self.p.long)))
        self._std_short = StandardDeviation(momentum, period=max(1, int(self.p.short)))
        self.addminperiod(int(self.p.mperiod) + max(int(self.p.short), int(self.p.long)) + 3)

    def next(self):
        """Emit the short/long volatility ratio scaled to a percentage."""
        long_std = float(self._std_long[0])
        short_std = float(self._std_short[0])
        self.lines.trend[0] = 100.0 * short_std / long_std if long_std else 0.0


class VininITrendLRMAIndicator(Indicator):
    """Trend oscillator scoring LRMA against a fan of moving averages."""

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
            int(self.p.length1 + idx * self.p.ma_step) for idx in range(int(self.p.ma_count))
        ]
        ma_cls = resolve_ma_class(self.p.ma_method1)
        self._ma_lines = [ma_cls(self._lrma.lrma, period=max(1, p)) for p in periods]
        smooth_cls = resolve_ma_class(self.p.ma_method2)
        self._smooth = smooth_cls(self.lines.trend, period=max(1, int(self.p.length2)))
        self.addminperiod(int(self.p.lrma_period) + max(periods) + int(self.p.length2) + 5)

    def next(self):
        """Score LRMA versus the MA fan and exponentially smooth the result."""
        lrma_value = float(self._lrma.lrma[0])
        score = 0
        for ma_line in self._ma_lines:
            if lrma_value > float(ma_line[0]):
                score += 1
            else:
                score -= 1
        raw = 100.0 * score / max(1, len(self._ma_lines))
        period = max(1, int(self.p.length2))
        alpha = 2.0 / (period + 1.0)
        prev = float(self.lines.trend[-1]) if len(self) > 0 else raw
        if len(self) == 0:
            self.lines.trend[0] = raw
        else:
            self.lines.trend[0] = alpha * raw + (1.0 - alpha) * prev
