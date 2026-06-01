#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "KwanCccIndicator",
]


class KwanCccIndicator(Indicator):
    """Custom Kwan CCC technical indicator.

    Lines:
        kwan (LineSeries): Smoothed combination of Chaikin, CCI, and Momentum.
        direction (LineSeries): Directional momentum flag (0 = bullish, 1 = flat, 2 = bearish).
    """

    lines = (
        "kwan",
        "direction",
    )

    params = (
        ("fast_ma_period", 3),
        ("slow_ma_period", 10),
        ("ma_method", "LWMA"),
        ("cci_period", 14),
        ("cci_price", "MEDIAN"),
        ("momentum_period", 7),
        ("momentum_price", "CLOSE"),
        ("xma_method", "JJMA"),
        ("x_length", 7),
        ("x_phase", 100),
    )

    def __init__(self):
        """Initialize indicator variables, buffer lists, and min periods."""
        self.addminperiod(
            max(self.p.slow_ma_period, self.p.cci_period, self.p.momentum_period)
            + self.p.x_length
            + 5
        )
        self._adl_buf = []
        self._chaikin_buf = []
        self._cci_price_buf = []
        self._momentum_price_buf = []
        self._raw_buf = []
        self._smooth_prev = None
        self._smooth_buf = []

    def _select_price(self, mode):
        mode = str(mode).upper()
        if mode == "OPEN":
            return float(self.data.open[0])
        if mode == "HIGH":
            return float(self.data.high[0])
        if mode == "LOW":
            return float(self.data.low[0])
        if mode == "MEDIAN":
            return (float(self.data.high[0]) + float(self.data.low[0])) / 2.0
        if mode == "TYPICAL":
            return (
                float(self.data.high[0]) + float(self.data.low[0]) + float(self.data.close[0])
            ) / 3.0
        if mode == "WEIGHTED":
            return (
                float(self.data.high[0]) + float(self.data.low[0]) + 2.0 * float(self.data.close[0])
            ) / 4.0
        return float(self.data.close[0])

    @staticmethod
    def _sma(values, period):
        if len(values) < period or period <= 0:
            return None
        window = values[-period:]
        return sum(window) / float(period)

    @staticmethod
    def _lwma(values, period):
        if len(values) < period or period <= 0:
            return None
        window = values[-period:]
        weights = list(range(1, period + 1))
        denom = sum(weights)
        return sum(v * w for v, w in zip(window, weights)) / float(denom)

    def _ma(self, values, period, method):
        method = str(method).upper()
        if method in ("MODE_LWMA", "LWMA"):
            return self._lwma(values, period)
        return self._sma(values, period)

    def _calc_cci(self):
        period = int(self.p.cci_period)
        if len(self._cci_price_buf) < period or period <= 0:
            return None
        window = self._cci_price_buf[-period:]
        sma = sum(window) / float(period)
        mean_dev = sum(abs(v - sma) for v in window) / float(period)
        if mean_dev == 0:
            return 0.0
        return (window[-1] - sma) / (0.015 * mean_dev)

    def _calc_momentum(self):
        period = int(self.p.momentum_period)
        if len(self._momentum_price_buf) <= period or period <= 0:
            return None
        prev_price = self._momentum_price_buf[-(period + 1)]
        curr_price = self._momentum_price_buf[-1]
        if prev_price == 0:
            return None
        return 100.0 * curr_price / prev_price

    def _smooth_value(self, raw_value):
        method = str(self.p.xma_method).upper()
        if method in ("MODE_SMA_", "SMA"):
            period = max(1, int(self.p.x_length))
            if len(self._raw_buf) < period:
                return raw_value
            return sum(self._raw_buf[-period:]) / float(period)

        length = max(1, int(self.p.x_length))
        phase = max(-100, min(100, int(self.p.x_phase)))
        alpha = 2.0 / (length + 1.0)
        alpha *= 1.0 + 0.35 * (phase / 100.0)
        alpha = max(0.01, min(0.99, alpha))
        if self._smooth_prev is None or not math.isfinite(self._smooth_prev):
            smooth = raw_value
        else:
            smooth = self._smooth_prev + alpha * (raw_value - self._smooth_prev)
        self._smooth_prev = smooth
        return smooth

    def next(self):
        """Compute the Kwan CCC metric and directional momentum flags on each bar."""
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        close = float(self.data.close[0])
        volume = float(self.data.volume[0]) if math.isfinite(float(self.data.volume[0])) else 0.0

        if high != low:
            mf_mult = ((close - low) - (high - close)) / (high - low)
        else:
            mf_mult = 0.0
        adl_prev = self._adl_buf[-1] if self._adl_buf else 0.0
        adl = adl_prev + mf_mult * volume
        self._adl_buf.append(adl)

        chaikin_fast = self._ma(self._adl_buf, int(self.p.fast_ma_period), self.p.ma_method)
        chaikin_slow = self._ma(self._adl_buf, int(self.p.slow_ma_period), self.p.ma_method)
        if chaikin_fast is None or chaikin_slow is None:
            self.lines.kwan[0] = 0.0
            self.lines.direction[0] = 1.0
            return
        chaikin = chaikin_fast - chaikin_slow
        self._chaikin_buf.append(chaikin)

        self._cci_price_buf.append(self._select_price(self.p.cci_price))
        self._momentum_price_buf.append(self._select_price(self.p.momentum_price))

        cci = self._calc_cci()
        momentum = self._calc_momentum()
        if cci is None or momentum is None:
            self.lines.kwan[0] = 0.0
            self.lines.direction[0] = 1.0
            return

        if momentum == 0 or not math.isfinite(momentum):
            raw_value = 100.0
        else:
            raw_value = chaikin * cci / momentum
        self._raw_buf.append(raw_value)

        smooth = self._smooth_value(raw_value)
        self._smooth_buf.append(smooth)
        self.lines.kwan[0] = smooth

        if len(self._smooth_buf) < 2:
            self.lines.direction[0] = 1.0
            return

        prev_smooth = self._smooth_buf[-2]
        if smooth > prev_smooth:
            self.lines.direction[0] = 0.0
        elif smooth < prev_smooth:
            self.lines.direction[0] = 2.0
        else:
            self.lines.direction[0] = 1.0
