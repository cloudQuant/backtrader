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
    "TrendContinuationIndicator",
]


def resolve_ma_class(name):
    """Resolve a strategy MA mode string to a Backtrader MA indicator class."""
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
    """Resolve requested price source string to the corresponding line in data.

    Args:
        data: Backtrader data feed.
        mode: Configured price selector such as ``price_close`` or ``price_open``.

    Returns:
        A line object for the selected price representation.
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


class TrendContinuationIndicator(Indicator):
    """Momentum continuation indicator using smoothed up/down directional components."""

    lines = ("up", "down")
    params = (
        ("nperiod", 20),
        ("xmethod", "t3"),
        ("xperiod", 5),
        ("xphase", 61),
        ("ipc", "price_close"),
    )

    def __init__(self):
        """Resolve price source and moving-average class then enforce warm-up period."""
        self._price = resolve_price_line(self.data, self.p.ipc)
        self._ma_cls = resolve_ma_class(self.p.xmethod)
        self.addminperiod(int(self.p.nperiod) + int(self.p.xperiod) + 5)

    def next(self):
        """Compute smoothed up/down continuation values from directional price differences."""
        nperiod = max(2, int(self.p.nperiod))
        float(self._price[0]) - float(self._price[-1])
        positives = []
        negatives = []
        cf_p = []
        cf_n = []
        running_p = 0.0
        running_n = 0.0
        for i in range(nperiod):
            diff = float(self._price[-i]) - float(self._price[-i - 1])
            pos = -diff if diff > 0 else 0.0
            neg = diff if diff < 0 else 0.0
            running_p += pos
            running_n += neg
            positives.append(pos)
            negatives.append(neg)
            cf_p.append(running_p)
            cf_n.append(running_n)
        ch_p = sum(positives)
        ch_n = sum(negatives)
        cff_p = sum(cf_p)
        cff_n = sum(cf_n)
        k_p = ch_p - cff_n
        k_n = ch_n - cff_p
        period = max(1, int(self.p.xperiod))
        alpha = 2.0 / (period + 1.0)
        prev_up = float(self.lines.up[-1]) if len(self) > 0 else k_p
        prev_dn = float(self.lines.down[-1]) if len(self) > 0 else k_n
        self.lines.up[0] = alpha * k_p + (1.0 - alpha) * prev_up if len(self) > 0 else k_p
        self.lines.down[0] = alpha * k_n + (1.0 - alpha) * prev_dn if len(self) > 0 else k_n
