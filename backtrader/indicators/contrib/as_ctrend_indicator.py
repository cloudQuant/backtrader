#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "ASCtrendIndicator",
]


def _wpr(highs, lows, close, period):
    """Return Williams %R for the last bar given arrays of length >= period."""
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh == ll:
        return 0.0
    return -100.0 * (hh - close) / (hh - ll)


class ASCtrendIndicator(Indicator):
    """Reconstructs ASCtrend from its MQ5 source.

    Outputs:
      - buy_arrow : non-zero price level when a buy arrow fires
      - sell_arrow: non-zero price level when a sell arrow fires
    """

    lines = ("buy_arrow", "sell_arrow")
    params = (("risk", 4),)

    def __init__(self):
        """Derive %R thresholds/periods from ``risk`` and reserve warm-up bars."""
        self._x1 = 67 + int(self.p.risk)
        self._x2 = 33 - int(self.p.risk)
        self._wpr_periods = [3, 4, 3 + int(self.p.risk) * 2]
        self._value10 = 2  # default WPR index
        min_period = max(3 + int(self.p.risk) * 2, 4) + 1
        # need enough history for ATR-style range calc (10 bars) + WPR look-back
        self.addminperiod(max(min_period, 12))

    # -- helpers operating on self.data (signal-timeframe feed) --
    def _get_wpr_val(self, period_idx, ago):
        """Compute WPR(period) at bar shifted by -ago from current."""
        period = self._wpr_periods[period_idx]
        n = len(self.data)
        idx = n - 1 - ago
        if idx < period:
            return 0.0
        highs = [float(self.data.high.array[i]) for i in range(idx - period + 1, idx + 1)]
        lows = [float(self.data.low.array[i]) for i in range(idx - period + 1, idx + 1)]
        close_val = float(self.data.close.array[idx])
        return _wpr(highs, lows, close_val, period)

    def next(self):
        """Emit ASCtrend buy/sell arrows from the %R band transitions per bar."""
        risk = int(self.p.risk)
        x1 = self._x1
        x2 = self._x2

        # --- ATR-style average range (10 bars) ---
        total_range = 0.0
        for i in range(1, 11):
            hi = float(self.data.high[-i])
            lo = float(self.data.low[-i])
            prev_close = float(self.data.close[-(i + 1)]) if len(self.data) > i + 1 else lo
            true_range = max(hi - lo, abs(hi - prev_close), abs(prev_close - lo))
            total_range += true_range
        avg_range = total_range / 10.0
        half_range = avg_range * 0.5

        # --- MRO1 / MRO2: look back for WPR threshold breach ---
        value10 = self._value10
        value11 = value10

        # MRO1: check if WPR(3) crossed > x1 recently
        mro1 = -1
        for k in range(1, risk * 2 + 1):
            if len(self.data) <= k:
                break
            w = 100.0 - abs(self._get_wpr_val(0, k))  # WPR_Handle[0] period=3
            if w > x1:
                mro1 = k
                break

        # MRO2: check if WPR(4) crossed < x2 recently
        mro2 = -1
        for k in range(1, risk * 2 + 1):
            if len(self.data) <= k:
                break
            w = 100.0 - abs(self._get_wpr_val(1, k))  # WPR_Handle[1] period=4
            if w < x2:
                mro2 = k
                break

        if mro1 > -1:
            value11 = 0
        else:
            value11 = value10
        if mro2 > -1:
            value11 = 1
        else:
            value11 = value10

        # Current WPR value with the selected period
        wpr_raw = self._get_wpr_val(value11, 0)
        value2 = 100.0 - abs(wpr_raw)

        buy_val = 0.0
        sell_val = 0.0
        cur_high = float(self.data.high[0])
        cur_low = float(self.data.low[0])

        if value2 < x2:
            # look back for transition from neutral zone to >x1
            iii = 1
            vel = 0.0
            while len(self.data) > iii:
                vel = 100.0 - abs(self._get_wpr_val(value11, iii))
                if x2 <= vel <= x1:
                    iii += 1
                else:
                    break
            if vel > x1:
                sell_val = cur_high + half_range

        if value2 > x1:
            iii = 1
            vel = 0.0
            while len(self.data) > iii:
                vel = 100.0 - abs(self._get_wpr_val(value11, iii))
                if x2 <= vel <= x1:
                    iii += 1
                else:
                    break
            if vel < x2:
                buy_val = cur_low - half_range

        self.lines.buy_arrow[0] = buy_val
        self.lines.sell_arrow[0] = sell_val
