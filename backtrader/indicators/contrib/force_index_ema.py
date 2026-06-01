#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    ATR,
    EMA,
    Indicator,
)

__all__ = [
    "ForceIndexEMA",
    "ForceDiverSign",
]


class ForceIndexEMA(Indicator):
    """Indicator producing a smoothed force index."""

    lines = ("value",)
    params = (("period", 3),)

    def __init__(self):
        """Compute raw force index then smooth with an EMA."""
        raw = (self.data.close - self.data.close(-1)) * self.data.volume
        self.l.value = EMA(raw, period=max(int(self.p.period), 1))


class ForceDiverSign(Indicator):
    """Divergence signal detector built from two force-index EMAs."""

    lines = ("sell", "buy")
    params = (
        ("i_period1", 3),
        ("i_period2", 7),
    )

    def __init__(self):
        """Initialize ATR filter and dual force-index streams."""
        self.atr = ATR(self.data, period=10)
        self.ind1 = ForceIndexEMA(self.data, period=int(self.p.i_period1)).value
        self.ind2 = ForceIndexEMA(self.data, period=int(self.p.i_period2)).value
        self.addminperiod(max(int(self.p.i_period1), int(self.p.i_period2)) * 2 + 10)

    def next(self):
        """Evaluate candle patterns and divergence confirmation each bar."""
        self.l.sell[0] = float("nan")
        self.l.buy[0] = float("nan")
        if len(self.data) < 6:
            return

        sell_candle = (
            float(self.data.open[-3]) < float(self.data.close[-3])
            and float(self.data.open[-2]) > float(self.data.close[-2])
            and float(self.data.open[-1]) < float(self.data.close[-1])
        )
        buy_candle = (
            float(self.data.open[-3]) > float(self.data.close[-3])
            and float(self.data.open[-2]) < float(self.data.close[-2])
            and float(self.data.open[-1]) > float(self.data.close[-1])
        )

        ind1 = [
            float(self.ind1[-4]),
            float(self.ind1[-3]),
            float(self.ind1[-2]),
            float(self.ind1[-1]),
        ]
        ind2 = [
            float(self.ind2[-4]),
            float(self.ind2[-3]),
            float(self.ind2[-2]),
            float(self.ind2[-1]),
        ]
        atr = float(self.atr[0]) if not math.isnan(float(self.atr[0])) else 0.0

        if sell_candle:
            if ind1[0] < ind1[1] and ind1[1] > ind1[2] and ind1[2] < ind1[3]:
                if ind2[0] < ind2[1] and ind2[1] > ind2[2] and ind2[2] < ind2[3]:
                    if (ind1[1] > ind1[3] and ind2[1] < ind2[3]) or (
                        ind1[1] < ind1[3] and ind2[1] > ind2[3]
                    ):
                        self.l.sell[0] = float(self.data.high[0]) + atr * 3.0 / 8.0

        if buy_candle:
            if ind1[0] > ind1[1] and ind1[1] < ind1[2] and ind1[2] > ind1[3]:
                if ind2[0] > ind2[1] and ind2[1] < ind2[2] and ind2[2] > ind2[3]:
                    if (ind1[1] > ind1[3] and ind2[1] < ind2[3]) or (
                        ind1[1] < ind1[3] and ind2[1] > ind2[3]
                    ):
                        self.l.buy[0] = float(self.data.low[0]) - atr * 3.0 / 8.0
