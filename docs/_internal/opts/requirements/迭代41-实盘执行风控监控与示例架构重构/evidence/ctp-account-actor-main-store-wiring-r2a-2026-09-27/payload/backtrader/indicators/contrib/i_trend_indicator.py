#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    BollingerBands,
    ExponentialMovingAverage,
    Indicator,
    SimpleMovingAverage,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "ITrendIndicator",
]


def get_price_line(data, price_mode):
    """Return the price line of ``data`` matching the requested mode.

    Args:
        data: A data feed exposing open/high/low/close lines.
        price_mode: Price selector such as close, open, high, low, median,
            typical, or weighted (with optional ``price_*`` prefixes).

    Returns:
        The corresponding price line or derived price expression.

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


def build_ma(price_line, period, ma_type):
    """Construct a moving average indicator of the requested type.

    Args:
        price_line: The input price line to smooth.
        period: Lookback length for the moving average.
        ma_type: Moving average type (SMA, EMA, SMMA/LWMA or their ``MODE_*``
            aliases).

    Returns:
        The instantiated moving average indicator.

    Raises:
        ValueError: If ``ma_type`` is not supported.
    """
    mode = str(ma_type).upper()
    mapping = {
        "MODE_SMA": SimpleMovingAverage,
        "SMA": SimpleMovingAverage,
        "MODE_EMA": ExponentialMovingAverage,
        "EMA": ExponentialMovingAverage,
        "MODE_SMMA": SmoothedMovingAverage,
        "SMMA": SmoothedMovingAverage,
        "MODE_LWMA": WeightedMovingAverage,
        "LWMA": WeightedMovingAverage,
    }
    if mode not in mapping:
        raise ValueError(f"Unsupported ma_type: {ma_type}")
    return mapping[mode](price_line, period=period)


class ITrendIndicator(Indicator):
    """i_Trend indicator producing primary and signal crossover lines.

    The ``primary`` line is the selected price minus a Bollinger band line and
    the ``signal`` line is a moving average mirrored around the bar's high/low
    range; their crossovers drive the strategy's entries and exits.
    """

    lines = ("primary", "signal")
    params = (
        ("price_type", "close"),
        ("ma_period", 13),
        ("ma_type", "EMA"),
        ("ma_price", "close"),
        ("bb_period", 20),
        ("deviation", 2.0),
        ("bb_price", "close"),
        ("bb_mode", 0),
    )

    def __init__(self):
        """Wire the moving average and Bollinger band into the output lines."""
        price_type_line = get_price_line(self.data, self.p.price_type)
        ma_price_line = get_price_line(self.data, self.p.ma_price)
        bb_price_line = get_price_line(self.data, self.p.bb_price)
        ma = build_ma(ma_price_line, int(self.p.ma_period), self.p.ma_type)
        bands = BollingerBands(
            bb_price_line, period=int(self.p.bb_period), devfactor=float(self.p.deviation)
        )
        mode = int(self.p.bb_mode)
        if mode == 0:
            band_line = bands.mid
        elif mode == 1:
            band_line = bands.top
        elif mode == 2:
            band_line = bands.bot
        else:
            raise ValueError(f"Unsupported bb_mode: {self.p.bb_mode}")
        self.l.primary = price_type_line - band_line
        self.l.signal = (ma * 2.0) - self.data.low - self.data.high
        self.addminperiod(max(int(self.p.ma_period), int(self.p.bb_period)) + 5)
