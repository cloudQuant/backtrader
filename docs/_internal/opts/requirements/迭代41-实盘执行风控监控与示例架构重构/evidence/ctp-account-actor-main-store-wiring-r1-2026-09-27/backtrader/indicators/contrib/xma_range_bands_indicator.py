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
    "XMARangeBandsIndicator",
]


def resolve_ma_class(name):
    """Map a moving-average name to its backtrader indicator class.

    Args:
        name: Moving-average mode name (e.g. ``'sma'``, ``'ema'``, ``'smma'``).

    Returns:
        The matching backtrader moving-average indicator class, defaulting to
        the weighted moving average for unrecognized names.
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
    """Map an applied-price mode to a price line built from the data feed.

    Args:
        data: The data feed providing open/high/low/close lines.
        mode: Applied-price mode name (e.g. ``'price_close'``, ``'median'``,
            ``'typical'``, ``'weighted'``).

    Returns:
        A line expression for the requested applied price, defaulting to close.
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


class XMARangeBandsIndicator(Indicator):
    """Moving-average midline with range-scaled upper and lower bands."""

    lines = (
        "mid",
        "upper",
        "lower",
    )
    params = (
        ("ma_method1", "sma"),
        ("length1", 100),
        ("phase1", 15),
        ("ma_method2", "jjma"),
        ("length2", 20),
        ("phase2", 100),
        ("deviation", 2.0),
        ("ipc", "price_close"),
        ("price_shift", 0),
    )

    def __init__(self):
        """Build the midline MA and range MA, then derive the band lines."""
        price_line = resolve_price_line(self.data, self.p.ipc)
        ma_cls_1 = resolve_ma_class(self.p.ma_method1)
        ma_cls_2 = resolve_ma_class(self.p.ma_method2)
        self._base = ma_cls_1(price_line, period=self.p.length1)
        bar_range = self.data.high - self.data.low
        self._range_ma = ma_cls_2(bar_range, period=self.p.length2)
        self.lines.mid = self._base + self.p.price_shift
        self.lines.upper = self.lines.mid + self._range_ma * self.p.deviation
        self.lines.lower = self.lines.mid - self._range_ma * self.p.deviation
        self.addminperiod(max(self.p.length1, self.p.length2) + 3)
