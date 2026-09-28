#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
    RelativeStrengthIndex,
    SimpleMovingAverage,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "QQECloudIndicator",
]


def resolve_ma_class(name):
    """Resolve moving-average class from strategy configuration value."""
    mode = str(name).lower()
    if mode in {"mode_sma", "sma"}:
        return SimpleMovingAverage
    if mode in {
        "mode_ema",
        "ema",
        "mode_jjma",
        "jjma",
        "mode_jurx",
        "jurx",
        "mode_parma",
        "parma",
        "mode_t3",
        "t3",
        "mode_vidya",
        "vidya",
        "mode_ama",
        "ama",
    }:
        return ExponentialMovingAverage
    if mode in {"mode_smma", "smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


class QQECloudIndicator(Indicator):
    """Indicator computing smoothed QQE-like trend values from RSI.

    Args:
        rsi_period: RSI lookback period.
        sf: Smoothing factor for XRSI and momentum smoothers.
        darfactor: ATR-like factor used to offset trailing reference.
        xma_method: Moving-average method alias used for RSI smoothing.
        xphase: Unused legacy parameter preserved for compatibility.
    """

    lines = ("up", "down")
    params = (
        ("rsi_period", 14),
        ("sf", 5),
        ("darfactor", 4.236),
        ("xma_method", "sma"),
        ("xphase", 15),
    )

    def __init__(self):
        """Initialize RSI, smoothed RSI, and momentum smoothing components."""
        self._rsi = RelativeStrengthIndex(self.data.close, period=max(2, int(self.p.rsi_period)))
        ma_cls = resolve_ma_class(self.p.xma_method)
        self._xrsi = ma_cls(self._rsi, period=max(1, int(self.p.sf)))
        wilders_period = max(2, int(self.p.rsi_period) * 2 - 1)
        self._mom = abs(self._xrsi - self._xrsi(-1))
        self._xmom = ma_cls(self._mom, period=wilders_period)
        self._xxmom = ma_cls(self._xmom, period=wilders_period)
        self.addminperiod(int(self.p.rsi_period) + int(self.p.sf) + wilders_period * 2 + 5)

    def next(self):
        """Update output lines on each tick using previous envelope state."""
        xrsi = float(self._xrsi[0])
        prev_xrsi = float(self._xrsi[-1])
        dar = float(self._xxmom[0]) * float(self.p.darfactor)
        prev_tr = float(self.lines.down[-1]) if len(self) > 0 else 50.0
        if prev_tr != prev_tr:
            prev_tr = 50.0
        tr = prev_tr
        dv = tr
        if xrsi < tr:
            tr = xrsi + dar
            if prev_xrsi < dv and tr > dv:
                tr = dv
        elif xrsi > tr:
            tr = xrsi - dar
            if prev_xrsi > dv and tr < dv:
                tr = dv
        self.lines.up[0] = xrsi
        self.lines.down[0] = tr

    def once(self, start, end):
        """Vectorized indicator evaluation for vectorized Backtrader runs."""
        xrsi_array = self._xrsi.array
        xxmom_array = self._xxmom.array
        up_line = self.lines.up.array
        down_line = self.lines.down.array
        for line in (up_line, down_line):
            while len(line) < end:
                line.append(float("nan"))

        prev_tr = 50.0
        actual_end = min(end, len(xrsi_array), len(xxmom_array))
        for i in range(start, actual_end):
            xrsi = float(xrsi_array[i])
            prev_xrsi = float(xrsi_array[i - 1]) if i > 0 else xrsi
            dar = float(xxmom_array[i]) * float(self.p.darfactor)
            tr = prev_tr
            dv = tr
            if xrsi < tr:
                tr = xrsi + dar
                if prev_xrsi < dv and tr > dv:
                    tr = dv
            elif xrsi > tr:
                tr = xrsi - dar
                if prev_xrsi > dv and tr < dv:
                    tr = dv
            up_line[i] = xrsi
            down_line[i] = tr
            prev_tr = tr
