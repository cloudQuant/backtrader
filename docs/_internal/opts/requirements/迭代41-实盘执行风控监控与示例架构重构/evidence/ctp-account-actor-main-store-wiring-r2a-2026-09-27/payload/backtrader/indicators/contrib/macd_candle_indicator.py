#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    MACD,
    Indicator,
)

__all__ = [
    "MacdCandleIndicator",
]


class MacdCandleIndicator(Indicator):
    """MACD-based candle indicator returning open/high/low/close values."""

    lines = ("macd_open", "macd_high", "macd_low", "macd_close", "color")
    params = (
        ("fast_ema_period", 12),
        ("slow_ema_period", 26),
        ("signal_period", 9),
        ("mode", "signal"),
    )

    def __init__(self):
        """Create MACD lines and register warmup period."""
        self.addminperiod(
            max(int(self.p.fast_ema_period), int(self.p.slow_ema_period))
            + int(self.p.signal_period)
            + 3
        )
        self.macd_open = MACD(
            self.data.open,
            period_me1=int(self.p.fast_ema_period),
            period_me2=int(self.p.slow_ema_period),
            period_signal=int(self.p.signal_period),
        )
        self.macd_high = MACD(
            self.data.high,
            period_me1=int(self.p.fast_ema_period),
            period_me2=int(self.p.slow_ema_period),
            period_signal=int(self.p.signal_period),
        )
        self.macd_low = MACD(
            self.data.low,
            period_me1=int(self.p.fast_ema_period),
            period_me2=int(self.p.slow_ema_period),
            period_signal=int(self.p.signal_period),
        )
        self.macd_close = MACD(
            self.data.close,
            period_me1=int(self.p.fast_ema_period),
            period_me2=int(self.p.slow_ema_period),
            period_signal=int(self.p.signal_period),
        )

    def _value(self, macd_obj):
        return float(macd_obj.signal[0]) if self.p.mode == "signal" else float(macd_obj.macd[0])

    def next(self):
        """Populate output candle components and derive color state per bar."""
        open_value = self._value(self.macd_open)
        high_value = self._value(self.macd_high)
        low_value = self._value(self.macd_low)
        close_value = self._value(self.macd_close)
        self.lines.macd_open[0] = open_value
        self.lines.macd_high[0] = high_value
        self.lines.macd_low[0] = low_value
        self.lines.macd_close[0] = close_value
        if open_value < close_value:
            color = 2
        elif open_value > close_value:
            color = 0
        else:
            color = 1
        self.lines.color[0] = color
