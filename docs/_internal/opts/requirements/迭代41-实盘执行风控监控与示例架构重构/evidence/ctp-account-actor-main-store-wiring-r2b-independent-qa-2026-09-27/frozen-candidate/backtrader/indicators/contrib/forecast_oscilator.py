#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "ForecastOscilator",
]


def _price_value(data, shift, mode):
    key = str(mode).lower()
    open_ = float(data.open[-shift]) if shift else float(data.open[0])
    high = float(data.high[-shift]) if shift else float(data.high[0])
    low = float(data.low[-shift]) if shift else float(data.low[0])
    close = float(data.close[-shift]) if shift else float(data.close[0])
    if key in ("close", "1", "price_close"):
        return close
    if key in ("open", "2", "price_open"):
        return open_
    if key in ("high", "3", "price_high"):
        return high
    if key in ("low", "4", "price_low"):
        return low
    if key in ("median", "5", "price_median"):
        return (high + low) / 2.0
    if key in ("typical", "6", "price_typical"):
        return (high + low + close) / 3.0
    if key in ("weighted", "7", "price_weighted"):
        return (high + low + close + close) / 4.0
    if key in ("simple", "8", "price_simpl"):
        return (open_ + close) / 2.0
    if key in ("quarter", "9", "price_quarter"):
        return (high + low + open_ + close) / 4.0
    if key in ("trendfollow0", "10", "price_trendfollow0"):
        if close > open_:
            return high
        if close < open_:
            return low
        return close
    if key in ("trendfollow1", "11", "price_trendfollow1"):
        if close > open_:
            return (high + close) / 2.0
        if close < open_:
            return (low + close) / 2.0
        return close
    return close


class ForecastOscilator(Indicator):
    """Forecast Oscillator with T3-smoothed signal and arrow lines.

    Computes the percentage deviation of price from a linear-regression
    forecast (the raw ``ind`` line), smooths it with a six-stage T3 moving
    average into the ``signal`` line, and emits ``buy``/``sell`` arrow values
    when the oscillator crosses its signal under the configured sign
    conditions.
    """

    lines = ("ind", "signal", "buy", "sell")
    params = (
        ("length", 15),
        ("t3", 3),
        ("b", 0.7),
        ("ipc", "close"),
    )

    def __init__(self):
        """Reserve the warm-up window and initialise T3 smoothing state."""
        self.addminperiod(int(self.p.length) + 5)
        self._e1 = 0.0
        self._e2 = 0.0
        self._e3 = 0.0
        self._e4 = 0.0
        self._e5 = 0.0
        self._e6 = 0.0
        self._initialized = False

    def next(self):
        """Compute the oscillator, T3 signal and arrow lines for this bar."""
        length = max(int(self.p.length), 1)
        t3 = max(int(self.p.t3), 1)
        b = float(self.p.b)
        b2 = b * b
        b3 = b2 * b
        c1 = -b3
        c2 = 3 * (b2 + b3)
        c3 = -3 * (2 * b2 + b + b3)
        c4 = 1 + 3 * b + b3 + 3 * b2
        n = max(1 + 0.5 * (t3 - 1), 1.0)
        w1 = 2.0 / (n + 1.0)
        w2 = 1.0 - w1
        kx = 6.0 / (length * (length + 1.0))
        br = (length + 1.0) / 3.0

        if len(self.data) <= length + 2:
            price = _price_value(self.data, 0, self.p.ipc)
            self.l.ind[0] = 0.0
            self.l.signal[0] = 0.0
            self.l.buy[0] = float("nan")
            self.l.sell[0] = float("nan")
            if not self._initialized:
                self._e1 = self._e2 = self._e3 = self._e4 = self._e5 = self._e6 = price
                self._initialized = True
            return

        weighted_sum = 0.0
        for i in range(length, 0, -1):
            tmp = i - br
            weighted_sum += tmp * _price_value(self.data, length - i, self.p.ipc)
        wt = weighted_sum * kx
        price_now = _price_value(self.data, 0, self.p.ipc)
        forecastosc = ((price_now - wt) / wt * 100.0) if wt else 0.0

        if not self._initialized:
            self._e1 = self._e2 = self._e3 = self._e4 = self._e5 = self._e6 = forecastosc
            self._initialized = True

        self._e1 = w1 * forecastosc + w2 * self._e1
        self._e2 = w1 * self._e1 + w2 * self._e2
        self._e3 = w1 * self._e2 + w2 * self._e3
        self._e4 = w1 * self._e3 + w2 * self._e4
        self._e5 = w1 * self._e4 + w2 * self._e5
        self._e6 = w1 * self._e5 + w2 * self._e6
        t3_fosc = c1 * self._e6 + c2 * self._e5 + c3 * self._e4 + c4 * self._e3

        self.l.ind[0] = forecastosc
        self.l.signal[0] = t3_fosc
        self.l.buy[0] = float("nan")
        self.l.sell[0] = float("nan")

        if len(self.data) >= length + 4:
            ind_prev1 = float(self.l.ind[-1])
            ind_prev2 = float(self.l.ind[-2])
            sig_prev1 = float(self.l.signal[-1])
            sig_prev2 = float(self.l.signal[-2])
            sig_prev3 = float(self.l.signal[-3])
            if ind_prev1 > sig_prev2 and ind_prev2 <= sig_prev3 and sig_prev1 < 0:
                self.l.buy[0] = t3_fosc - 0.05
            if ind_prev1 < sig_prev2 and ind_prev2 >= sig_prev3 and sig_prev1 > 0:
                self.l.sell[0] = t3_fosc + 0.05
