#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "WPRSISignalIndicator",
]


class WPRSISignalIndicator(Indicator):
    """Reconstructs WPRSIsignal indicator from its MQ5 source.

    Uses WPR and RSI with same period.
    Buy: WPR crosses above -20 from below AND RSI > 50, with filterUP lookback confirmation.
    Sell: WPR crosses below -80 from above AND RSI < 50, with filterDN lookback confirmation.
    """

    lines = ("sell_arrow", "buy_arrow")  # buffer 0 = sell, buffer 1 = buy
    params = (
        ("wprsi_period", 27),
        ("filter_up", 10),
        ("filter_dn", 10),
    )

    def __init__(self):
        """Reserve warm-up bars covering the WPRSI period plus the filter window."""
        self._period = int(self.p.wprsi_period)
        self._filter_up = int(self.p.filter_up)
        self._filter_dn = int(self.p.filter_dn)
        filter_max = max(self._filter_up, self._filter_dn)
        self.addminperiod(self._period + filter_max + 3)

    def _calc_wpr(self, ago=0):
        period = self._period
        highest = max(float(self.data.high[-(ago + i)]) for i in range(period))
        lowest = min(float(self.data.low[-(ago + i)]) for i in range(period))
        close = float(self.data.close[-ago])
        if highest == lowest:
            return -50.0
        return -100.0 * (highest - close) / (highest - lowest)

    def _calc_rsi(self, ago=0):
        period = self._period
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
        """Emit buy/sell arrows on filtered Williams %R crosses confirmed by RSI."""
        wpr_0 = self._calc_wpr(0)
        wpr_1 = self._calc_wpr(1)
        rsi_0 = self._calc_rsi(0)

        buy_val = 0.0
        sell_val = 0.0

        cur_high = float(self.data.high[0])
        cur_low = float(self.data.low[0])
        rng = cur_high - cur_low

        # Buy: WPR crosses above -20 from below, RSI > 50
        if wpr_0 > -20.0 and wpr_1 < -20.0 and rsi_0 > 50.0:
            z = 0
            for k in range(2, self._filter_up + 3):
                if k < len(self.data):
                    wk = self._calc_wpr(k)
                    if wk > -20.0:
                        z = 1
                        break
            if z == 0:
                buy_val = cur_low - rng / 2.0

        # Sell: WPR crosses below -80 from above, RSI < 50
        if wpr_1 > -80.0 and wpr_0 < -80.0 and rsi_0 < 50.0:
            h = 0
            for c in range(2, self._filter_dn + 3):
                if c < len(self.data):
                    wk = self._calc_wpr(c)
                    if wk < -80.0:
                        h = 1
                        break
            if h == 0:
                sell_val = cur_high + rng / 2.0

        self.lines.sell_arrow[0] = sell_val
        self.lines.buy_arrow[0] = buy_val
