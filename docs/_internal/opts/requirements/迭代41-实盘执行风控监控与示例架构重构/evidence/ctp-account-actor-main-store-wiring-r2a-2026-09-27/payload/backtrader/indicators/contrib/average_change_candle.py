#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "AverageChangeCandle",
]


class AverageChangeCandle(Indicator):
    """Custom Average Change Candle indicator that computes power-scaled smoothed lines.

    Lines:
        open_line (LineSeries): Smoothed open line.
        high_line (LineSeries): Smoothed high line.
        low_line (LineSeries): Smoothed low line.
        close_line (LineSeries): Smoothed close line.
        color (LineSeries): Candle color state (0 = bearish, 1 = flat, 2 = bullish).
    """

    lines = (
        "open_line",
        "high_line",
        "low_line",
        "close_line",
        "color",
    )

    params = (
        ("ma_method1", "LWMA"),
        ("length1", 12),
        ("phase1", 15),
        ("ipc1", "PRICE_MEDIAN_"),
        ("ma_method2", "JJMA"),
        ("length2", 5),
        ("phase2", 100),
        ("pow_value", 5.0),
    )

    def __init__(self):
        """Initialize indicator variables, buffer lists, and min periods."""
        self.addminperiod(max(int(self.p.length1), int(self.p.length2)) + 10)
        self._base_buf = []
        self._o_buf = []
        self._h_buf = []
        self._l_buf = []
        self._c_buf = []
        self._base_prev = None
        self._o_prev = None
        self._h_prev = None
        self._l_prev = None
        self._c_prev = None

    def _price_series(self):
        mode = str(self.p.ipc1).upper()
        o = float(self.data.open[0])
        h = float(self.data.high[0])
        low_price = float(self.data.low[0])
        c = float(self.data.close[0])
        if mode == "PRICE_OPEN_":
            return o
        if mode == "PRICE_HIGH_":
            return h
        if mode == "PRICE_LOW_":
            return low_price
        if mode == "PRICE_TYPICAL_":
            return (h + low_price + c) / 3.0
        if mode == "PRICE_WEIGHTED_":
            return (h + low_price + c + c) / 4.0
        if mode == "PRICE_SIMPL_":
            return (o + c) / 2.0
        if mode == "PRICE_QUARTER_":
            return (h + low_price + o + c) / 4.0
        if mode == "PRICE_DEMARK_":
            return (h + low_price + 2.0 * c) / 4.0
        return (h + low_price) / 2.0

    def _smooth(self, raw_value, method, length, phase, buf, prev_value_attr):
        method = str(method).upper()
        length = max(1, int(length))
        if method in ("MODE_SMA_", "SMA"):
            if len(buf) < length:
                return raw_value
            return sum(buf[-length:]) / float(length)
        if method in ("MODE_LWMA_", "LWMA"):
            if len(buf) < length:
                return raw_value
            weights = list(range(1, length + 1))
            values = buf[-length:]
            denom = float(sum(weights))
            return sum(v * w for v, w in zip(values, weights)) / denom
        prev = getattr(self, prev_value_attr)
        phase = max(-100, min(100, int(phase)))
        alpha = 2.0 / (length + 1.0)
        alpha *= 1.0 + 0.35 * (phase / 100.0)
        alpha = max(0.01, min(0.99, alpha))
        if prev is None or not math.isfinite(prev):
            smooth = raw_value
        else:
            smooth = prev + alpha * (raw_value - prev)
        setattr(self, prev_value_attr, smooth)
        return smooth

    def next(self):
        """Compute smoothed and power-scaled candle lines on each bar."""
        base_price = self._price_series()
        self._base_buf.append(base_price)
        xma = self._smooth(
            base_price,
            self.p.ma_method1,
            self.p.length1,
            self.p.phase1,
            self._base_buf,
            "_base_prev",
        )
        xma = xma if xma != 0 else 1e-12

        power = float(self.p.pow_value)
        o_raw = math.pow(float(self.data.open[0]) / xma, power)
        h_raw = math.pow(float(self.data.high[0]) / xma, power)
        l_raw = math.pow(float(self.data.low[0]) / xma, power)
        c_raw = math.pow(float(self.data.close[0]) / xma, power)

        self._o_buf.append(o_raw)
        self._h_buf.append(h_raw)
        self._l_buf.append(l_raw)
        self._c_buf.append(c_raw)

        o_val = self._smooth(
            o_raw, self.p.ma_method2, self.p.length2, self.p.phase2, self._o_buf, "_o_prev"
        )
        h_val = self._smooth(
            h_raw, self.p.ma_method2, self.p.length2, self.p.phase2, self._h_buf, "_h_prev"
        )
        l_val = self._smooth(
            l_raw, self.p.ma_method2, self.p.length2, self.p.phase2, self._l_buf, "_l_prev"
        )
        c_val = self._smooth(
            c_raw, self.p.ma_method2, self.p.length2, self.p.phase2, self._c_buf, "_c_prev"
        )

        max_body = max(o_val, c_val)
        min_body = min(o_val, c_val)
        h_val = max(max_body, h_val)
        l_val = min(min_body, l_val)

        if o_val < c_val:
            color = 2.0
        elif o_val > c_val:
            color = 0.0
        else:
            color = 1.0

        self.lines.open_line[0] = o_val
        self.lines.high_line[0] = h_val
        self.lines.low_line[0] = l_val
        self.lines.close_line[0] = c_val
        self.lines.color[0] = color
