#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    ATR,
    Indicator,
)

__all__ = [
    "FisherOrgV1Sign",
]


def _price(data, mode, ago=0):
    """Return a price value from OHLC data based on a mode selector.

    Parameters
    ----------
    data : DataFeed
        Data feed with open/high/low/close lines.
    mode : int
        Price mode: 2=open, 3=high, 4=low, 5=(h+l)/2, 6=(h+l+c)/3,
        7=(2c+h+l)/4, 8=(o+c)/2, 9=(o+h+l+c)/4; default returns close.
    ago : int
        Bar offset.

    Returns
    -------
    float
        Selected price value.
    """
    o = float(data.open[-ago])
    h = float(data.high[-ago])
    low_price = float(data.low[-ago])
    c = float(data.close[-ago])
    if mode == 2:
        return o
    if mode == 3:
        return h
    if mode == 4:
        return low_price
    if mode == 5:
        return (h + low_price) / 2.0
    if mode == 6:
        return (h + low_price + c) / 3.0
    if mode == 7:
        return (2.0 * c + h + low_price) / 4.0
    if mode == 8:
        return (o + c) / 2.0
    if mode == 9:
        return (o + h + low_price + c) / 4.0
    return c


class FisherOrgV1Sign(Indicator):
    """Fisher Transform Org V1 Sign indicator.

    Normalises price within a highest-high/lowest-low window over `length`
    bars, smooths the normalised position via recursive formula, then applies
    the Fisher Transform (atanh) to produce a near-Gaussian signal. Buy/sell
    trigger lines are set at ATR-scaled price levels on threshold crossovers.

    Lines
    -----
    sell : float
        Price level for sell signals (high + 3/8 ATR), set on up-cross.
    buy : float
        Price level for buy signals (low - 3/8 ATR), set on down-cross.
    """

    lines = ("sell", "buy")
    params = (
        ("atr_period", 14),
        ("length", 7),
        ("ipc", 1),
        ("up_level", 1.5),
        ("dn_level", -1.5),
    )

    def __init__(self):
        """Initialise indicator state: ATR sub-indicator and Fisher smoothing values."""
        self.addminperiod(max(int(self.p.atr_period), int(self.p.length)) + 3)
        self.atr = ATR(self.data, period=int(self.p.atr_period))
        self._value1 = 0.0
        self._fish1 = 0.0

    def next(self):
        """Compute Fisher Transform values and set buy/sell signal lines."""
        length = int(self.p.length)
        highs = [float(self.data.high[-i]) for i in range(length)]
        lows = [float(self.data.low[-i]) for i in range(length)]
        smax = max(highs)
        smin = min(lows)
        if smax == smin:
            smax += 1e-12
        price = _price(self.data, int(self.p.ipc), 0)
        wpr = (price - smin) / (smax - smin)
        value0 = (wpr - 0.5) + 0.67 * self._value1
        value0 = min(max(value0, -0.999), 0.999)
        res2 = (1.0 + value0) / (1.0 - value0)
        if res2 < 1e-7:
            res2 = 1.0
        fish0 = 0.5 * math.log(res2) + 0.5 * self._fish1
        self.lines.buy[0] = float("nan")
        self.lines.sell[0] = float("nan")
        atr = float(self.atr[0])
        if fish0 > float(self.p.dn_level) and self._fish1 <= float(self.p.dn_level):
            self.lines.buy[0] = float(self.data.low[0]) - atr * 3.0 / 8.0
        if fish0 < float(self.p.up_level) and self._fish1 >= float(self.p.up_level):
            self.lines.sell[0] = float(self.data.high[0]) + atr * 3.0 / 8.0
        self._value1 = value0
        self._fish1 = fish0
