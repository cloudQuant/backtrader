#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "TrendArrowsIndicator",
]


class TrendArrowsIndicator(Indicator):
    """Reconstructs trend_arrows indicator.

    Computes AverageHigh (avg of highest highs over iPeriod sub-windows)
    and AverageLow (avg of lowest lows over iPeriod sub-windows).
    TrendUp = LL when close > HH; TrendDown = HH when close < LL;
    else continues previous trend.
    SignUp when TrendUp appears fresh; SignDown when TrendDown appears fresh.
    Buffers: 0=TrendUp, 1=TrendDown, 2=SignUp(buy), 3=SignDown(sell).
    """

    lines = ("trend_up", "trend_down", "sign_up", "sign_down")
    params = (
        ("iperiod", 15),
        ("ifullperiods", 1),
    )

    def __init__(self):
        """Initialize cached period lengths for trend arrow reconstruction."""
        self._ip = int(self.p.iperiod)
        self._ifp = int(self.p.ifullperiods)
        self._window = self._ip + self._ifp
        self.addminperiod(self._window + 2)

    def next(self):
        """Compute trend and signal buffers for the current bar.

        The method:
        1. Splits the lookback window into `iperiod` sub-windows and averages highs/lows.
        2. Generates TrendUp/TrendDown buffers based on close relative to aggregated levels.
        3. Emits SignUp/SignDown only on fresh transitions from inactive to active.
        """
        ip = self._ip
        window = self._window

        # Compute AverageHigh: average of highest highs over ip sub-windows
        segment_size = max(window // ip, 1)
        hh_sum = 0.0
        ll_sum = 0.0
        count = 0
        for seg in range(ip):
            start = seg * segment_size
            end = min(start + segment_size, window)
            if start >= len(self.data):
                break
            seg_high = -1e30
            seg_low = 1e30
            for k in range(start, min(end, len(self.data))):
                h = float(self.data.high[-k]) if k > 0 else float(self.data.high[0])
                low_price = float(self.data.low[-k]) if k > 0 else float(self.data.low[0])
                if h > seg_high:
                    seg_high = h
                if low_price < seg_low:
                    seg_low = low_price
            hh_sum += seg_high
            ll_sum += seg_low
            count += 1

        hh = hh_sum / count if count else float(self.data.high[0])
        ll = ll_sum / count if count else float(self.data.low[0])

        close_val = float(self.data.close[0])
        prev_tu = float(self.lines.trend_up[-1]) if len(self.lines.trend_up) > 1 else 0.0
        prev_td = float(self.lines.trend_down[-1]) if len(self.lines.trend_down) > 1 else 0.0
        if math.isnan(prev_tu):
            prev_tu = 0.0
        if math.isnan(prev_td):
            prev_td = 0.0

        tu = 0.0
        td = 0.0

        if close_val > hh:
            tu = ll
        elif close_val < ll:
            td = hh
        else:
            if prev_td != 0.0:
                td = hh
            if prev_tu != 0.0:
                tu = ll

        su = 0.0
        sd = 0.0
        if prev_tu == 0.0 and tu != 0.0:
            su = tu
        if prev_td == 0.0 and td != 0.0:
            sd = td

        self.lines.trend_up[0] = tu
        self.lines.trend_down[0] = td
        self.lines.sign_up[0] = su
        self.lines.sign_down[0] = sd
