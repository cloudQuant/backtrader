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
    "BlauCMomentumIndicator",
]


def resolve_ma_class(name):
    """Map a moving-average mode name to a backtrader indicator class.

    Args:
        name: The MA mode name (e.g. ``sma``, ``ema``, ``smma``, or a MODE_*
            alias).

    Returns:
        The matching backtrader moving-average indicator class, defaulting to
        the weighted moving average for unrecognised names.
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
    """Map a price mode name to the corresponding feed price line.

    Args:
        data: The data feed whose OHLC lines are referenced.
        mode: The price mode name (e.g. ``close``, ``median``, ``typical``,
            ``weighted``).

    Returns:
        The selected price line or derived price expression, defaulting to the
        close for unrecognised modes.
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


class BlauCMomentumIndicator(Indicator):
    """Blau composite momentum: triple-smoothed price-difference oscillator."""

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
        """Build the price difference, triple-smooth it, and set the min period."""
        ma_cls = resolve_ma_class(self.p.xma_method)
        price1 = resolve_price_line(self.data, self.p.ipc1)
        price2 = resolve_price_line(self.data, self.p.ipc2)
        mom = price1 - price2(-max(0, int(self.p.xlength) - 1))
        xmom = ma_cls(mom, period=max(1, int(self.p.xlength1)))
        xxmom = ma_cls(xmom, period=max(1, int(self.p.xlength2)))
        xxxmom = ma_cls(xxmom, period=max(1, int(self.p.xlength3)))
        self._momentum = xxxmom
        self.lines.value = 100.0 * xxxmom
        self.addminperiod(
            int(self.p.xlength)
            + int(self.p.xlength1)
            + int(self.p.xlength2)
            + int(self.p.xlength3)
            + 5
        )
