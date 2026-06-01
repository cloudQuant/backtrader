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
    "ZPFIndicator",
]


def resolve_ma_class(name):
    """Map a moving-average name to its backtrader indicator class.

    Args:
        name: MA type name (e.g. ``sma``, ``ema``, ``smma`` or MT5-style
            ``mode_*`` variants).

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
    """Return the applied-price line for a data feed given a price mode.

    Args:
        data: The data feed providing OHLC lines.
        mode: Applied-price selector (e.g. ``price_close``, ``price_median``,
            ``price_typical`` or their short forms).

    Returns:
        A line expression for the selected applied price, defaulting to the
        close for unrecognized modes.
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
        return (data.high + data.low + data.close + data.open + data.close) / 5.0
    return data.close


class ZPFIndicator(Indicator):
    """Zero Power Flow oscillator (volume-weighted MA spread).

    Multiplies a moving average of volume by the gap between a short and a long
    moving average of an applied price, producing a volume-weighted
    trend-strength value (``zpf``) that oscillates around zero, with symmetric
    ``line1``/``line2`` envelopes.
    """

    lines = (
        "line1",
        "line2",
        "zpf",
    )
    params = (
        ("xma_method", "sma"),
        ("xlength", 12),
        ("xphase", 15),
        ("ipc", "price_close"),
        ("volume_type", "tick"),
    )

    def __init__(self):
        """Build the price/volume moving averages and the ZPF lines."""
        ma_cls = resolve_ma_class(self.p.xma_method)
        price_line = resolve_price_line(self.data, self.p.ipc)
        volume_line = (
            self.data.volume
            if str(self.p.volume_type).lower() == "tick"
            else self.data.openinterest
        )
        self.x1ma = ma_cls(price_line, period=self.p.xlength)
        self.x2ma = ma_cls(price_line, period=max(1, 2 * self.p.xlength))
        self.xvol = ma_cls(volume_line, period=self.p.xlength)
        self.lines.zpf = self.xvol * (self.x1ma - self.x2ma) / 2.0
        self.lines.line1 = -self.lines.zpf
        self.lines.line2 = self.lines.zpf
        self.addminperiod(max(2 * self.p.xlength, self.p.xlength) + 2)
