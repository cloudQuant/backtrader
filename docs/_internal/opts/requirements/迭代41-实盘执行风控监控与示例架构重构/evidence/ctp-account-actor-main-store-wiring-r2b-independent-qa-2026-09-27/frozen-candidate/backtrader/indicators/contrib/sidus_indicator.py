#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "SidusIndicator",
]


class SidusIndicator(Indicator):
    """Reconstructs Sidus indicator from its MQ5 source.

    Uses 4 MAs: FastEMA, SlowEMA, FastLWMA, SlowLWMA + ATR(15).
    Buy arrows on: FastLWMA crosses above SlowLWMA, or SlowLWMA crosses above SlowEMA.
    Sell arrows on reverse crosses.
    Arrow offset = ATR * digit scaling.
    """

    lines = ("buy_arrow", "sell_arrow")
    params = (
        ("fast_ema", 18),
        ("slow_ema", 28),
        ("fast_lwma", 5),
        ("slow_lwma", 8),
        ("digit", 0),
    )

    def __init__(self):
        """Cache MA periods and digit scaling, and set the indicator warmup."""
        self._fe = int(self.p.fast_ema)
        self._se = int(self.p.slow_ema)
        self._fl = int(self.p.fast_lwma)
        self._sl = int(self.p.slow_lwma)
        self._digit = float(10 ** int(self.p.digit)) if int(self.p.digit) > 0 else 0.0
        self.addminperiod(max(self._fe, self._se, self._fl, self._sl) + 3)

    def _ema(self, period, ago):
        # Simple EMA approximation using close prices
        k = 2.0 / (period + 1)
        val = float(self.data.close[-(ago + period - 1)])
        for i in range(ago + period - 2, ago - 1, -1):
            val = float(self.data.close[-i]) * k + val * (1 - k) if i >= 0 else val
        return val

    def _lwma(self, period, ago):
        total = 0.0
        wsum = 0.0
        for i in range(period):
            w = float(period - i)
            total += float(self.data.close[-(ago + i)]) * w
            wsum += w
        return total / wsum if wsum > 0 else 0.0

    def _atr(self, period, ago):
        total = 0.0
        for i in range(period):
            idx = ago + i
            h = float(self.data.high[-idx])
            low_price = float(self.data.low[-idx])
            if idx + 1 < len(self.data):
                pc = float(self.data.close[-(idx + 1)])
                tr = max(h - low_price, abs(h - pc), abs(low_price - pc))
            else:
                tr = h - low_price
            total += tr
        return total / period

    def next(self):
        """Emit buy/sell arrow offsets when the LWMA/EMA cross conditions fire."""
        # Current bar (ago=0) and previous bar (ago=1)
        self._ema(self._fe, 0)
        slw_ema_0 = self._ema(self._se, 0)
        fst_lwma_0 = self._lwma(self._fl, 0)
        slw_lwma_0 = self._lwma(self._sl, 0)

        fst_lwma_1 = self._lwma(self._fl, 1)
        slw_lwma_1 = self._lwma(self._sl, 1)
        slw_ema_1 = self._ema(self._se, 1)

        atr_val = self._atr(15, 0)
        rng = atr_val * 3.0
        digit = self._digit

        buy_val = 0.0
        sell_val = 0.0

        # Buy: FastLWMA crosses above SlowLWMA, or SlowLWMA crosses above SlowEMA
        if fst_lwma_0 > slw_lwma_0 + digit and fst_lwma_1 <= slw_lwma_1:
            buy_val = float(self.data.low[0]) - rng
        if slw_lwma_0 > slw_ema_0 + digit and slw_lwma_1 <= slw_ema_1:
            buy_val = float(self.data.low[0]) - rng

        # Sell: FastLWMA crosses below SlowLWMA, or SlowLWMA crosses below SlowEMA
        if fst_lwma_0 < slw_lwma_0 - digit and fst_lwma_1 >= slw_lwma_1:
            sell_val = float(self.data.high[0]) + rng
        if slw_lwma_0 < slw_ema_0 - digit and slw_lwma_1 >= slw_ema_1:
            sell_val = float(self.data.high[0]) + rng

        self.lines.buy_arrow[0] = buy_val
        self.lines.sell_arrow[0] = sell_val
