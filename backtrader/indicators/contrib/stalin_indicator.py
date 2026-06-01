#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "StalinIndicator",
]


class StalinIndicator(Indicator):
    """Reconstructs Stalin indicator from its MQ5 source.

    Uses Fast/Slow MA crossover with optional RSI filter.
    BU() fires buy arrow at low if flat distance check passes.
    BD() fires sell arrow at high if flat distance check passes.
    Optional Confirm parameter adds a price-distance confirmation step.
    """

    lines = ("buy_arrow", "sell_arrow")
    params = (
        ("ma_method", "ema"),
        ("fast", 14),
        ("slow", 21),
        ("rsi_period", 17),
        ("confirm", 0),
        ("flat", 0),
        ("point", 0.0001),
    )

    def __init__(self):
        """Prepare cached MA/RSI parameters and state for BU/BD arrow generation."""
        self._fast = int(self.p.fast)
        self._slow = int(self.p.slow)
        self._rsi = int(self.p.rsi_period)
        self._confirm2 = float(self.p.confirm) * float(self.p.point)
        self._flat2 = float(self.p.flat) * float(self.p.point)
        self._e1 = 0.0  # last buy arrow price
        self._e2 = 0.0  # last sell arrow price
        self._iup = 0.0  # pending buy confirmation price
        self._idn = 0.0  # pending sell confirmation price
        self.addminperiod(max(self._fast, self._slow, self._rsi if self._rsi > 0 else 1) + 3)

    def _calc_ema(self, period, ago):
        k = 2.0 / (period + 1)
        val = float(self.data.close[-(ago + period - 1)])
        for i in range(ago + period - 2, ago - 1, -1):
            val = float(self.data.close[-i]) * k + val * (1 - k) if i >= 0 else val
        return val

    def _calc_lwma(self, period, ago):
        total = 0.0
        wsum = 0.0
        for i in range(period):
            w = float(period - i)
            total += float(self.data.close[-(ago + i)]) * w
            wsum += w
        return total / wsum if wsum > 0 else 0.0

    def _calc_sma(self, period, ago):
        total = 0.0
        for i in range(period):
            total += float(self.data.close[-(ago + i)])
        return total / period

    def _calc_ma(self, period, ago):
        method = str(self.p.ma_method).lower()
        if method == "lwma":
            return self._calc_lwma(period, ago)
        if method == "sma":
            return self._calc_sma(period, ago)
        return self._calc_ema(period, ago)

    def _calc_rsi(self, period, ago):
        gains = 0.0
        losses = 0.0
        for i in range(period):
            idx = ago + i
            c = float(self.data.close[-idx])
            cp = float(self.data.close[-(idx + 1)])
            diff = c - cp
            if diff > 0:
                gains += diff
            else:
                losses -= diff
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def next(self):
        """Compute MA crossover and optional RSI filters, then emit buy/sell arrows."""
        fast_ma_0 = self._calc_ma(self._fast, 0)
        slow_ma_0 = self._calc_ma(self._slow, 0)
        fast_ma_1 = self._calc_ma(self._fast, 1)
        slow_ma_1 = self._calc_ma(self._slow, 1)

        use_rsi = self._rsi > 0
        rsi_val = self._calc_rsi(self._rsi, 0) if use_rsi else 50.0

        buy_val = 0.0
        sell_val = 0.0

        cur_low = float(self.data.low[0])
        cur_high = float(self.data.high[0])
        cur_close = float(self.data.close[0])
        flat2 = self._flat2
        confirm2 = self._confirm2

        # MA crossover buy signal
        if (not use_rsi) or (fast_ma_1 < slow_ma_1 and fast_ma_0 > slow_ma_0 and rsi_val > 50):
            if not confirm2:
                # BU: fire buy arrow if flat distance passes
                if cur_low >= (self._e1 + flat2) or cur_low <= (self._e1 - flat2):
                    buy_val = cur_low
                    self._e1 = cur_low
            else:
                self._iup = cur_low
                self._idn = 0.0

        # MA crossover sell signal
        if (not use_rsi) or (fast_ma_1 > slow_ma_1 and fast_ma_0 < slow_ma_0 and rsi_val < 50):
            if not confirm2:
                if cur_high >= (self._e2 + flat2) or cur_high <= (self._e2 - flat2):
                    sell_val = cur_high
                    self._e2 = cur_high
            else:
                self._idn = cur_high
                self._iup = 0.0

        # Confirm pending buy
        if self._iup and cur_high - self._iup >= confirm2 and cur_close <= cur_high:
            if cur_low >= (self._e1 + flat2) or cur_low <= (self._e1 - flat2):
                buy_val = cur_low
                self._e1 = cur_low
            self._iup = 0.0

        # Confirm pending sell
        if self._idn and self._idn - cur_low >= confirm2 and float(self.data.open[0]) >= cur_close:
            if cur_high >= (self._e2 + flat2) or cur_high <= (self._e2 - flat2):
                sell_val = cur_high
                self._e2 = cur_high
            self._idn = 0.0

        self.lines.buy_arrow[0] = buy_val
        self.lines.sell_arrow[0] = sell_val
