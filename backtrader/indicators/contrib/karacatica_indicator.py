#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from ...linebuffer import _reject_factor_infinity
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
        self._karacatica_bar_length = None
        self._karacatica_prior_ltr = 0
        self.addminperiod(int(self.p.iperiod) + 2)

    def _finite(self, *values):
        valid = True
        for value in values:
            if not math.isfinite(value):
                _reject_factor_infinity(self.lines.buy_arrow, value)
                valid = False
        return valid

    def _calc_atr(self):
        period = int(self.p.iperiod)
        total = 0.0
        for i in range(period):
            hi = float(self.data.high[-i])
            lo = float(self.data.low[-i])
            prev_c = float(self.data.close[-(i + 1)])
            if not self._finite(hi, lo, prev_c):
                return float("nan")
            ranges = (hi - lo, hi - prev_c, prev_c - lo)
            if not self._finite(*ranges):
                return float("nan")
            total += max(ranges[0], abs(ranges[1]), abs(ranges[2]))
            if not self._finite(total):
                return float("nan")
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
            if not self._finite(hi, lo, prev_hi, prev_lo, prev_c):
                return float("nan"), float("nan")
            up_move = hi - prev_hi
            down_move = prev_lo - lo
            ranges = (hi - lo, hi - prev_c, prev_c - lo)
            if not self._finite(up_move, down_move, *ranges):
                return float("nan"), float("nan")
            plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
            minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
            tr = max(ranges[0], abs(ranges[1]), abs(ranges[2]))
            plus_dm_sum += plus_dm
            minus_dm_sum += minus_dm
            tr_sum += tr
            if not self._finite(plus_dm_sum, minus_dm_sum, tr_sum):
                return float("nan"), float("nan")
        if tr_sum == 0:
            return 0.0, 0.0
        plus_scaled = 100.0 * plus_dm_sum
        minus_scaled = 100.0 * minus_dm_sum
        if not self._finite(plus_scaled, minus_scaled):
            return float("nan"), float("nan")
        plus_di = plus_scaled / tr_sum
        minus_di = minus_scaled / tr_sum
        if not self._finite(plus_di, minus_di):
            return float("nan"), float("nan")
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

        bar_length = len(self.data)
        if bar_length != self._karacatica_bar_length:
            self._karacatica_bar_length = bar_length
            self._karacatica_prior_ltr = self._ltr
        prior_ltr = self._karacatica_prior_ltr

        atr = self._calc_atr()
        plus_di, minus_di = self._calc_adx_di()
        cur_close = float(self.data.close[0])
        past_close = float(self.data.close[-period])
        cur_high = float(self.data.high[0])
        cur_low = float(self.data.low[0])

        if not self._finite(
            atr, plus_di, minus_di, cur_close, past_close, cur_high, cur_low
        ):
            self.lines.buy_arrow[0] = float("nan")
            self.lines.sell_arrow[0] = float("nan")
            self._ltr = prior_ltr
            return

        buy_val = 0.0
        sell_val = 0.0
        next_ltr = prior_ltr

        if cur_close > past_close and plus_di > minus_di and prior_ltr != 1:
            buy_val = cur_low - atr * self._s
            next_ltr = 1
        if cur_close < past_close and plus_di < minus_di and prior_ltr != 2:
            sell_val = cur_high + atr * self._s
            next_ltr = 2

        if not self._finite(buy_val, sell_val):
            self.lines.buy_arrow[0] = float("nan")
            self.lines.sell_arrow[0] = float("nan")
            self._ltr = prior_ltr
            return

        self.lines.buy_arrow[0] = buy_val
        self.lines.sell_arrow[0] = sell_val
        self._ltr = next_ltr
