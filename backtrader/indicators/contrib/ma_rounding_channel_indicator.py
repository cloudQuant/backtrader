#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ATR,
    EMA,
    SMA,
    Indicator,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "MARoundingChannelIndicator",
]


def resolve_ma_class(name):
    """Map MA method name to the corresponding Backtrader indicator class."""
    mode = str(name).lower()
    if mode in {"sma", "mode_sma"}:
        return SMA
    if mode in {"ema", "mode_ema"}:
        return EMA
    if mode in {"smma", "mode_smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


def resolve_price_line(data, mode):
    """Map a configured price selector string to feed line values."""
    price_mode = str(mode).lower()
    if price_mode in {"price_open", "open"}:
        return data.open
    if price_mode in {"price_high", "high"}:
        return data.high
    if price_mode in {"price_low", "low"}:
        return data.low
    if price_mode in {"price_median", "median"}:
        return (data.high + data.low) / 2.0
    if price_mode in {"price_typical", "typical"}:
        return (data.high + data.low + data.close) / 3.0
    if price_mode in {"price_weighted", "weighted"}:
        return (data.high + data.low + data.close + data.close) / 4.0
    if price_mode in {"price_simpl", "simpl"}:
        return (data.open + data.close) / 2.0
    if price_mode in {"price_quarter", "quarter"}:
        return (data.high + data.low + data.open + data.close) / 4.0
    if price_mode in {"price_trendfollow0", "trendfollow0"}:
        return (data.high + data.low + data.close + data.close) / 4.0
    if price_mode in {"price_trendfollow1", "trendfollow1"}:
        return (data.high + data.low + data.open + data.close + data.close) / 5.0
    return data.close


class MARoundingChannelIndicator(Indicator):
    """Indicator that derives rounded moving-average centerline and channel bounds."""

    lines = (
        "base",
        "upper",
        "lower",
    )
    params = (
        ("xma_method", "sma"),
        ("xlength", 12),
        ("xphase", 15),
        ("ipc", "price_close"),
        ("ma_round", 500),
        ("atr_period", 12),
        ("atr_factor", 1.0),
        ("chan_continuity", False),
    )

    def __init__(self):
        """Resolve MA and ATR dependencies and initialize rolling channel state."""
        ma_cls = resolve_ma_class(self.p.xma_method)
        price_line = resolve_price_line(self.data, self.p.ipc)
        self.ma = ma_cls(price_line, period=self.p.xlength)
        self.atr = ATR(self.data, period=self.p.atr_period)
        self._ma_ro = None
        self._prev_ma = None
        self._prev_dir = 0
        self._prev_range = 0.0
        self._prev_base = None
        self._prev_prev_base = None
        self._prev_upper = 0.0
        self._prev_lower = 0.0
        self.addminperiod(max(self.p.xlength, self.p.atr_period) + 3)

    def next(self):
        """Update channel base/upper/lower values from latest MA and ATR context."""
        if self._ma_ro is None:
            self._ma_ro = (
                float(self.data.close[0]) * 0.0 + self.data._dataname["close"].iloc[0] * 0.0
                if False
                else None
            )
        ma_ro = float(getattr(self.data, "_compression", 0) or 0)
        if not ma_ro:
            point = 0.01 if abs(float(self.data.close[0])) >= 1 else 0.0001
            ma_ro = point * float(self.p.ma_round)
        mov_ave0 = float(self.ma[0])
        if self._prev_ma is None:
            self._prev_ma = mov_ave0
        res1 = self._prev_base if self._prev_base is not None else mov_ave0
        if (
            mov_ave0 > self._prev_ma + ma_ro
            or mov_ave0 < self._prev_ma - ma_ro
            or mov_ave0 > res1 + ma_ro
            or mov_ave0 < res1 - ma_ro
            or (mov_ave0 > res1 and self._prev_dir == 1)
            or (mov_ave0 < res1 and self._prev_dir == -1)
        ):
            base = mov_ave0
        else:
            base = res1
        direction = 0
        if base < res1:
            direction = -1
        elif base > res1:
            direction = 1
        else:
            direction = self._prev_dir
        upper = 0.0
        lower = 0.0
        range0 = self._prev_range
        if base == res1:
            if self._prev_prev_base is None or res1 != self._prev_prev_base:
                range0 = float(self.atr[0]) * float(self.p.atr_factor)
            upper = base + range0
            lower = base - range0
        elif self.p.chan_continuity:
            upper = self._prev_upper
            lower = self._prev_lower
        self.lines.base[0] = base
        self.lines.upper[0] = upper
        self.lines.lower[0] = lower
        self._prev_dir = direction
        self._prev_ma = mov_ave0
        self._prev_range = range0
        self._prev_prev_base = self._prev_base
        self._prev_base = base
        self._prev_upper = upper
        self._prev_lower = lower
