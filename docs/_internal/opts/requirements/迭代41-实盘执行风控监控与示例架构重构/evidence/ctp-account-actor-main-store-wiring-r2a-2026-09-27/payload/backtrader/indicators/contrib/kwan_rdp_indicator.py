#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "KwanRdpIndicator",
]


class KwanRdpIndicator(Indicator):
    """Custom Kwan RDP technical indicator.

    Lines:
        kwan (LineSeries): Smoothed combination of DeMarker, MFI, and Momentum.
        direction (LineSeries): Directional momentum flag (0 = bullish, 1 = flat, 2 = bearish).
    """

    lines = (
        "kwan",
        "direction",
    )

    params = (
        ("demarker_period", 14),
        ("mfi_period", 14),
        ("volume_type", "TICK"),
        ("momentum_period", 14),
        ("momentum_price", "CLOSE"),
        ("xma_method", "JJMA"),
        ("x_length", 7),
        ("x_phase", 100),
    )

    def __init__(self):
        """Initialize indicator state: rolling buffers and minperiod."""
        self.addminperiod(
            max(self.p.demarker_period, self.p.mfi_period, self.p.momentum_period)
            + self.p.x_length
            + 5
        )
        self._high_buf = []
        self._low_buf = []
        self._close_buf = []
        self._typical_buf = []
        self._money_flow_buf = []
        self._raw_buf = []
        self._smooth_prev = None
        self._smooth_buf = []

    def _select_price(self, mode):
        """Return the selected price value (open/high/low/median/typical/weighted/close)."""
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

    def _calc_demarker(self):
        """Compute DeMarker oscillator from rolling high/low buffers."""
        p = int(self.p.demarker_period)
        if len(self._high_buf) <= p or len(self._low_buf) <= p:
            return None
        demax = []
        demin = []
        for i in range(len(self._high_buf) - p, len(self._high_buf)):
            high_diff = self._high_buf[i] - self._high_buf[i - 1]
            low_diff = self._low_buf[i - 1] - self._low_buf[i]
            demax.append(max(high_diff, 0.0))
            demin.append(max(low_diff, 0.0))
        smax = sum(demax)
        smin = sum(demin)
        denom = smax + smin
        if denom == 0:
            return 0.5
        return smax / denom

    def _calc_mfi(self):
        """Compute Money Flow Index from typical price and volume buffers."""
        p = int(self.p.mfi_period)
        if len(self._typical_buf) <= p or len(self._money_flow_buf) <= p:
            return None
        pos_flow = 0.0
        neg_flow = 0.0
        start = len(self._typical_buf) - p
        for i in range(start, len(self._typical_buf)):
            prev_tp = self._typical_buf[i - 1]
            curr_tp = self._typical_buf[i]
            curr_flow = self._money_flow_buf[i]
            if curr_tp > prev_tp:
                pos_flow += curr_flow
            elif curr_tp < prev_tp:
                neg_flow += curr_flow
        if neg_flow == 0:
            return 100.0
        money_ratio = pos_flow / neg_flow
        return 100.0 - (100.0 / (1.0 + money_ratio))

    def _calc_momentum(self):
        """Compute momentum as percentage change of selected price over period."""
        p = int(self.p.momentum_period)
        if len(self._close_buf) <= p:
            return None
        prev_price = self._close_buf[-(p + 1)]
        curr_price = self._select_price(self.p.momentum_price)
        if prev_price == 0:
            return None
        return 100.0 * curr_price / prev_price

    def _smooth_value(self, raw_value):
        """Smooth raw_value using SMA or phase-adjusted exponential (JJMA-like)."""
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
        """Compute Kwan RDP indicator: composite of DeMarker * MFI / momentum, smoothed."""
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        close = float(self.data.close[0])
        volume = float(self.data.volume[0]) if math.isfinite(float(self.data.volume[0])) else 0.0

        self._high_buf.append(high)
        self._low_buf.append(low)
        self._close_buf.append(close)
        typical = (high + low + close) / 3.0
        self._typical_buf.append(typical)
        self._money_flow_buf.append(typical * volume)

        demarker = self._calc_demarker()
        mfi = self._calc_mfi()
        momentum = self._calc_momentum()
        if demarker is None or mfi is None or momentum is None:
            self.lines.kwan[0] = 0.0
            self.lines.direction[0] = 1.0
            return

        if momentum == 0 or not math.isfinite(momentum):
            raw_value = 100.0
        else:
            raw_value = 100.0 * demarker * mfi / momentum
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
