#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "EFDistanceIndicator",
]


def resolve_price_line(data, mode):
    """Build an applied-price line from a data feed per MT5 price modes.

    Args:
        data: The backtrader data feed providing OHLC lines.
        mode: MT5 applied-price mode (e.g. ``'price_close'``, ``'price_typical'``).

    Returns:
        A backtrader line expression for the selected applied price, defaulting
        to the close line.
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
        return (data.open + data.close + data.high + data.low) / 4.0
    return data.close


class EFDistanceIndicator(Indicator):
    """Energy-field distance indicator producing a weighted applied-price value.

    Weights each price in a window by the accumulated powered distance to the
    other prices in the window, yielding a smoothed ``value`` line whose turns
    signal momentum shifts.
    """

    lines = ("value",)
    params = (
        ("length", 10),
        ("power", 2.0),
        ("ipc", "price_close"),
        ("price_shift", 0.0),
    )

    def __init__(self):
        """Set the minimum period required for the energy-field window."""
        self.addminperiod(int(self.p.length) * 2 + 2)

    def next(self):
        """Compute the energy-field weighted price value for the current bar."""
        length = int(self.p.length)
        float(resolve_price_line(self.data, self.p.ipc)[0])
        weights = []
        prices = []
        for i in range(length):
            base_price = float(resolve_price_line(self.data, self.p.ipc)[-i])
            energy = 0.0
            for j in range(length):
                ref_price = float(resolve_price_line(self.data, self.p.ipc)[-(i + j)])
                energy += abs((base_price - ref_price) ** float(self.p.power))
            weights.append(energy)
            prices.append(base_price)
        norm = sum(weights)
        value = sum(w * p for w, p in zip(weights, prices)) / norm if norm else 0.0
        self.lines.value[0] = value + float(self.p.price_shift)
