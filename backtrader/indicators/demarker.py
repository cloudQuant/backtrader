#!/usr/bin/env python
"""DeMarker, Williams %R and related delta/slowdown indicators."""

from . import Indicator
from .atr import ATR
from .rsi import RSI
from .williams import WilliamsR

__all__ = [
    "DeMarker",
    "DeMarkerIndicator",
    "DeMarkerRollingIndicator",
    "DeltaRSI",
    "DeltaWPR",
    "WilliamsPercentR",
    "WPRHistogramIndicator",
    "WPRSlowdown",
]


class DeMarker(Indicator):
    """DeMarker oscillator with both ``demarker`` and ``dem`` output lines."""

    lines = ("demarker", "dem")
    params = (("period", 14), ("zero_value", 0.5))

    def __init__(self):
        self.addminperiod(self.p.period + 1)

    def next(self):
        de_max_sum = 0.0
        de_min_sum = 0.0
        for i in range(self.p.period):
            high_now = float(self.data.high[-i])
            high_prev = float(self.data.high[-(i + 1)])
            low_now = float(self.data.low[-i])
            low_prev = float(self.data.low[-(i + 1)])
            de_max_sum += max(high_now - high_prev, 0.0)
            de_min_sum += max(low_prev - low_now, 0.0)
        denom = de_max_sum + de_min_sum
        value = float(self.p.zero_value) if denom == 0 else de_max_sum / denom
        self.lines.demarker[0] = value
        self.lines.dem[0] = value


class DeMarkerIndicator(DeMarker):
    """Compatibility DeMarker variant whose zero-denominator value is ``0.0``."""

    params = (("period", 14), ("zero_value", 0.0))


class DeMarkerRollingIndicator(Indicator):
    """Rolling-buffer DeMarker variant with ``0.5`` fallback."""

    lines = ("demarker", "dem")
    params = {"period": 14}

    def __init__(self):
        self.addminperiod(int(self.p.period) + 1)
        self._up_moves = []
        self._down_moves = []

    def next(self):
        up_move = max(float(self.data.high[0]) - float(self.data.high[-1]), 0.0)
        down_move = max(float(self.data.low[-1]) - float(self.data.low[0]), 0.0)
        self._up_moves.append(up_move)
        self._down_moves.append(down_move)
        period = int(self.p.period)
        if len(self._up_moves) > period:
            self._up_moves.pop(0)
            self._down_moves.pop(0)
        if len(self._up_moves) < period:
            self.lines.demarker[0] = float("nan")
            self.lines.dem[0] = float("nan")
            return
        up_sum = sum(self._up_moves)
        down_sum = sum(self._down_moves)
        denom = up_sum + down_sum
        value = 0.5 if denom == 0.0 else up_sum / denom
        self.lines.demarker[0] = value
        self.lines.dem[0] = value


class WilliamsPercentR(Indicator):
    """Williams %R with line name ``wpr`` and zero-denominator fallback ``0``."""

    lines = ("wpr",)
    params = {"period": 14}

    def __init__(self):
        self.addminperiod(self.p.period)

    def next(self):
        period = int(self.p.period)
        highest = max(float(self.data.high[-i]) for i in range(period))
        lowest = min(float(self.data.low[-i]) for i in range(period))
        denom = highest - lowest
        if denom == 0.0:
            self.lines.wpr[0] = 0.0
            return
        self.lines.wpr[0] = -100.0 * (highest - float(self.data.close[0])) / denom


class DeltaRSI(Indicator):
    """Difference between fast/slow RSI and a regime color line."""

    lines = ("color", "delta")
    params = {"rsi_period1": 14, "rsi_period2": 50, "level": 50}

    def __init__(self):
        self.addminperiod(max(int(self.p.rsi_period1), int(self.p.rsi_period2)) + 3)
        self.rsi1 = RSI(self.data, period=int(self.p.rsi_period1))
        self.rsi2 = RSI(self.data, period=int(self.p.rsi_period2))
        lvl = int(self.p.level)
        self.max_level = 100 - (100 - lvl)
        self.min_level = 100 - lvl

    def next(self):
        r1 = float(self.rsi1[0])
        r2 = float(self.rsi2[0])
        self.lines.delta[0] = r1 - r2
        color = 1.0
        if r2 > self.max_level and r1 > r2:
            color = 0.0
        if r2 < self.min_level and r1 < r2:
            color = 2.0
        self.lines.color[0] = color


class DeltaWPR(Indicator):
    """Difference between fast/slow Williams %R and a regime color line."""

    lines = ("color", "delta")
    params = {"wpr_period1": 14, "wpr_period2": 30, "level": -50}

    def __init__(self):
        self.addminperiod(max(int(self.p.wpr_period1), int(self.p.wpr_period2)) + 3)
        self.wpr1 = WilliamsR(self.data, period=int(self.p.wpr_period1))
        self.wpr2 = WilliamsR(self.data, period=int(self.p.wpr_period2))
        self.max_level = int(self.p.level)
        self.min_level = int(-100 - self.p.level)

    def next(self):
        w1 = float(self.wpr1[0])
        w2 = float(self.wpr2[0])
        self.lines.delta[0] = w1 - w2
        color = 1.0
        if w2 > self.max_level and w1 > w2:
            color = 0.0
        if w2 < self.min_level and w1 < w2:
            color = 2.0
        self.lines.color[0] = color


class WPRSlowdown(Indicator):
    """Williams %R extreme slowdown signal generator."""

    lines = ("sell", "buy")
    params = {"wpr_period": 12, "level_max": -20.0, "level_min": -80.0, "seek_slowdown": True}

    def __init__(self):
        self.addminperiod(max(int(self.p.wpr_period) + 2, 18))
        self.wpr = WilliamsR(self.data, period=int(self.p.wpr_period))
        self.atr = ATR(self.data, period=15)

    def next(self):
        self.lines.buy[0] = float("nan")
        self.lines.sell[0] = float("nan")
        w0 = float(self.wpr[0])
        w1 = float(self.wpr[-1])
        atr = float(self.atr[0])
        if w0 >= float(self.p.level_max):
            if (not self.p.seek_slowdown) or abs(w1 - w0) < 1.0:
                self.lines.buy[0] = float(self.data.low[0]) - atr * 3.0 / 8.0
        if w0 <= float(self.p.level_min):
            if (not self.p.seek_slowdown) or abs(w1 - w0) < 1.0:
                self.lines.sell[0] = float(self.data.high[0]) + atr * 3.0 / 8.0


class WPRHistogramIndicator(Indicator):
    """Williams %R value, midpoint and color-state histogram."""

    lines = ("value", "midline", "color_state")
    params = {"wpr_period": 14, "high_level": -30, "low_level": -70}

    def __init__(self):
        self.addminperiod(self.p.wpr_period)

    def next(self):
        period = int(self.p.wpr_period)
        highest_high = max(float(self.data.high[-i]) for i in range(period))
        lowest_low = min(float(self.data.low[-i]) for i in range(period))
        close = float(self.data.close[0])
        denom = highest_high - lowest_low
        if abs(denom) <= 1e-12:
            value = -50.0
        else:
            value = -100.0 * (highest_high - close) / denom

        color = 1.0
        if value > float(self.p.high_level):
            color = 0.0
        elif value < float(self.p.low_level):
            color = 2.0

        self.lines.value[0] = value
        self.lines.midline[0] = -50.0
        self.lines.color_state[0] = color
