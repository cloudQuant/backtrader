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
    "BlauCMIIndicator",
]


def resolve_ma_class(name):
    """Resolve a moving-average name string to a Backtrader indicator class.

    Args:
        name: Method token from strategy config.

    Returns:
        Backtrader moving average class.
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
    """Resolve a price selector token into a Backtrader line for arithmetic usage.

    Args:
        data: Backtrader data feed.
        mode: Price selector string.

    Returns:
        Data feed line for the selected price.
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
    return data.close


class BlauCMIIndicator(Indicator):
    """Compute the CMI oscillator from nested moving averages of momentum."""

    lines = ("value",)
    params = (
        ("xma_method", "ema"),
        ("xlength", 1),
        ("xlength1", 20),
        ("xlength2", 5),
        ("xlength3", 3),
        ("xphase", 15),
        ("ipc1", "price_close"),
        ("ipc2", "price_open"),
    )

    def __init__(self):
        """Set up numerator/denominator moving averages for oscillator output."""
        ma_cls = resolve_ma_class(self.p.xma_method)
        price1 = resolve_price_line(self.data, self.p.ipc1)
        price2 = resolve_price_line(self.data, self.p.ipc2)
        mom = price1 - price2(-max(0, int(self.p.xlength) - 1))
        abs_mom = abs(mom)
        xmom = ma_cls(mom, period=max(1, int(self.p.xlength1)))
        xabsmom = ma_cls(abs_mom, period=max(1, int(self.p.xlength1)))
        xxmom = ma_cls(xmom, period=max(1, int(self.p.xlength2)))
        xxabsmom = ma_cls(xabsmom, period=max(1, int(self.p.xlength2)))
        xxxmom = ma_cls(xxmom, period=max(1, int(self.p.xlength3)))
        xxxabsmom = ma_cls(xxabsmom, period=max(1, int(self.p.xlength3)))
        self._numerator = xxxmom
        self._denominator = xxxabsmom
        self.addminperiod(
            int(self.p.xlength1)
            + int(self.p.xlength2)
            + int(self.p.xlength3)
            + int(self.p.xlength)
            + 5
        )

    def next(self):
        """Populate the indicator value on a per-bar basis."""
        den = float(self._denominator[0])
        self.lines.value[0] = 100.0 * float(self._numerator[0]) / den if den else 0.0

    def once(self, start, end):
        """Compute indicator values in a vectorized range for Backtrader backfills."""
        numerator = self._numerator.array
        denominator = self._denominator.array
        value_line = self.lines.value.array
        while len(value_line) < end:
            value_line.append(float("nan"))

        actual_end = min(end, len(numerator), len(denominator))
        for i in range(start, actual_end):
            den = float(denominator[i])
            value_line[i] = 100.0 * float(numerator[i]) / den if den else 0.0
