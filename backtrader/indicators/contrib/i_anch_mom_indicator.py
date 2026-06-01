#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
    SimpleMovingAverage,
)

__all__ = [
    "IAnchMomIndicator",
]


def get_price_line(data, price_mode):
    """Select an applied-price line from a data feed by mode name.

    Args:
        data: The backtrader data feed providing OHLC lines.
        price_mode: Applied-price mode (e.g. ``'close'``, ``'median'``,
            ``'typical'``, ``'weighted'``); case-insensitive.

    Returns:
        The selected price line or a derived combination of OHLC lines.

    Raises:
        ValueError: If ``price_mode`` is not recognised.
    """
    mode = str(price_mode).lower()
    if mode in ("close", "price_close", "price_close_"):
        return data.close
    if mode in ("open", "price_open", "price_open_"):
        return data.open
    if mode in ("high", "price_high", "price_high_"):
        return data.high
    if mode in ("low", "price_low", "price_low_"):
        return data.low
    if mode in ("median", "price_median", "price_median_"):
        return (data.high + data.low) / 2.0
    if mode in ("typical", "price_typical", "price_typical_"):
        return (data.high + data.low + data.close) / 3.0
    if mode in ("weighted", "price_weighted", "price_weighted_"):
        return (data.high + data.low + data.close + data.close) / 4.0
    raise ValueError(f"Unsupported price mode: {price_mode}")


class IAnchMomIndicator(Indicator):
    """Anchored-momentum oscillator: percentage gap of a fast EMA over a slow SMA."""

    lines = ("value",)
    params = (
        ("sma_period", 34),
        ("ema_period", 20),
        ("price_type", "close"),
    )

    def __init__(self):
        """Build the SMA and EMA of the applied price and set the warm-up period."""
        price = get_price_line(self.data, self.p.price_type)
        self.sma = SimpleMovingAverage(price, period=int(self.p.sma_period))
        self.ema = ExponentialMovingAverage(price, period=int(self.p.ema_period))
        self.addminperiod(int(self.p.sma_period) + 2)

    def next(self):
        """Emit the percentage gap ``100 * (ema / sma - 1)`` for the current bar."""
        sma = float(self.sma[0])
        ema = float(self.ema[0])
        self.l.value[0] = 0.0 if sma == 0.0 else 100.0 * ((ema / sma) - 1.0)
