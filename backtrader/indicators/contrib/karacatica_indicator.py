#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "KaracaticaIndicator",
]


class KaracaticaIndicator(Indicator):
    """Reconstructs Karacatica from MQ5 source.

    Uses ATR(iPeriod), ADX(iPeriod) +DI/-DI, and close-vs-close(iPeriod-ago)
    to generate buy/sell arrows with direction latch to avoid repeats.
    """

    lines = ("buy_arrow", "sell_arrow")
    params = (("iperiod", 70),)

    def __init__(self):
        """Initialize the ATR scaling factor, direction latch, and min period."""
        self._s = 1.5 / 2.0
        self._ltr = 0  # 0=none, 1=last was buy, 2=last was sell
        self.addminperiod(int(self.p.iperiod) + 2)

    def _calc_atr(self):
        period = int(self.p.iperiod)
        total = 0.0
        for i in range(period):
            hi = float(self.data.high[-i])
            lo = float(self.data.low[-i])
            prev_c = float(self.data.close[-(i + 1)])
            total += max(hi - lo, abs(hi - prev_c), abs(prev_c - lo))
        return total / period

    def _calc_adx_di(self):
        period = int(self.p.iperiod)
        plus_dm_sum = 0.0
        minus_dm_sum = 0.0
        tr_sum = 0.0
        for i in range(period):
            hi = float(self.data.high[-i])
            lo = float(self.data.low[-i])
            prev_hi = float(self.data.high[-(i + 1)])
            prev_lo = float(self.data.low[-(i + 1)])
            prev_c = float(self.data.close[-(i + 1)])
            up_move = hi - prev_hi
            down_move = prev_lo - lo
            plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
            minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
            tr = max(hi - lo, abs(hi - prev_c), abs(prev_c - lo))
            plus_dm_sum += plus_dm
            minus_dm_sum += minus_dm
            tr_sum += tr
        if tr_sum == 0:
            return 0.0, 0.0
        plus_di = 100.0 * plus_dm_sum / tr_sum
        minus_di = 100.0 * minus_dm_sum / tr_sum
        return plus_di, minus_di

    def next(self):
        """Emit ATR-offset buy/sell arrows on latched directional breakouts.

        Computes ATR and +DI/-DI over ``iperiod`` and, when the close exceeds
        its value ``iperiod`` bars ago with +DI dominant (and the last arrow was
        not a buy), places a buy arrow below the low; the symmetric condition
        places a sell arrow above the high. The direction latch prevents
        consecutive arrows of the same side.
        """
        period = int(self.p.iperiod)
        if len(self.data) < period + 2:
            self.lines.buy_arrow[0] = 0.0
            self.lines.sell_arrow[0] = 0.0
            return

        atr = self._calc_atr()
        plus_di, minus_di = self._calc_adx_di()
        cur_close = float(self.data.close[0])
        past_close = float(self.data.close[-period])
        cur_high = float(self.data.high[0])
        cur_low = float(self.data.low[0])

        buy_val = 0.0
        sell_val = 0.0

        if cur_close > past_close and plus_di > minus_di and self._ltr != 1:
            buy_val = cur_low - atr * self._s
            self._ltr = 1
        if cur_close < past_close and plus_di < minus_di and self._ltr != 2:
            sell_val = cur_high + atr * self._s
            self._ltr = 2

        self.lines.buy_arrow[0] = buy_val
        self.lines.sell_arrow[0] = sell_val
