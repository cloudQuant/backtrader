#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    If,
    Indicator,
)

__all__ = [
    "JMASlopeIndicator",
]


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
        return (2.0 * data.close + data.high + data.low) / 4.0
    if price_mode in {"price_simpl", "simpl"}:
        return (data.open + data.close) / 2.0
    if price_mode in {"price_quarter", "quarter"}:
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class JMASlopeIndicator(Indicator):
    """Slope of a Jurik-style moving average with a rising/falling color.

    Approximates the JMA with an EMA of the applied price, then exposes its
    bar-over-bar change on the ``value`` line and a ``color`` line marking
    whether the slope is positive (4), negative (0) or flat (2).
    """

    lines = ("value", "color")
    params = (
        ("jlength", 14),
        ("jphase", 0),
        ("ipc", "price_close"),
    )

    def __init__(self):
        """Build the JMA proxy and its slope/color lines; set the min period."""
        price_line = resolve_price_line(self.data, self.p.ipc)
        self._jma = ExponentialMovingAverage(price_line, period=max(1, int(self.p.jlength)))
        delta = self._jma - self._jma(-1)
        self.lines.value = delta
        self.lines.color = If(delta > 0.0, 4.0, If(delta < 0.0, 0.0, 2.0))
        self.addminperiod(32 + int(self.p.jlength))
