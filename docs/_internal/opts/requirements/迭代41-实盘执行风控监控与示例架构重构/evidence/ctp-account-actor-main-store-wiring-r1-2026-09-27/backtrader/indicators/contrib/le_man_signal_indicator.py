#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "LeManSignalIndicator",
]


class LeManSignalIndicator(Indicator):
    """Reconstructs LeManSignal from its MQ5 source.

    Compares two consecutive LPeriod-window high/low ranges shifted by 1 bar
    and by LPeriod bars to detect breakouts.
    buy_arrow: H3<=H4 && H1>H2  (high range expansion upward)
    sell_arrow: L3>=L4 && L1<L2  (low range expansion downward)
    """

    lines = ("buy_arrow", "sell_arrow")
    params = (
        ("lperiod", 12),
        ("point", 0.0001),
    )

    def __init__(self):
        """Store LPeriod/rules and initialize lookback requirements."""
        self._lp = int(self.p.lperiod)
        self.addminperiod(self._lp * 2 + 3)

    def next(self):
        """Compute LeManSignal buy/sell arrows from rolling high-low ranges."""
        lp = self._lp
        # MQ5 as-series indexing: bar=0 is current, bar+1 is 1 ago, etc.
        # H1 = max high over [bar+1, bar+1+LPeriod)  => [-1 .. -(lp)]
        # H2 = max high over [bar+1+LPeriod, bar+1+2*LPeriod) => [-(lp+1) .. -(2*lp)]
        # H3 = max high over [bar+2, bar+2+LPeriod)  => [-2 .. -(lp+1)]
        # H4 = max high over [bar+2+LPeriod, bar+2+2*LPeriod) => [-(lp+2) .. -(2*lp+1)]
        H1 = max(float(self.data.high[-i]) for i in range(1, lp + 1))
        H2 = max(float(self.data.high[-i]) for i in range(lp + 1, 2 * lp + 1))
        H3 = max(float(self.data.high[-i]) for i in range(2, lp + 2))
        H4 = max(float(self.data.high[-i]) for i in range(lp + 2, 2 * lp + 2))

        L1 = min(float(self.data.low[-i]) for i in range(1, lp + 1))
        L2 = min(float(self.data.low[-i]) for i in range(lp + 1, 2 * lp + 1))
        L3 = min(float(self.data.low[-i]) for i in range(2, lp + 2))
        L4 = min(float(self.data.low[-i]) for i in range(lp + 2, 2 * lp + 2))

        buy_val = 0.0
        sell_val = 0.0
        pt = float(self.p.point)

        if H3 <= H4 and H1 > H2:
            buy_val = float(self.data.high[-1]) + pt
        if L3 >= L4 and L1 < L2:
            sell_val = float(self.data.low[-1]) - pt

        self.lines.buy_arrow[0] = buy_val
        self.lines.sell_arrow[0] = sell_val
