#!/usr/bin/env python
"""Channel and volatility-band indicators migrated from functional tests."""

from . import Indicator
from .atr import ATR
from .basicops import Highest, Lowest
from .ema import EMA

__all__ = [
    "ChandelierExitIndicator",
    "DonchianChannel",
    "DonchianChannelWarmup",
    "DonchianChannelIndicator",
    "KeltnerChannelIndicator",
]


class DonchianChannel(Indicator):
    """Donchian channel exposing both upper/lower and dch/dcl/dcm aliases."""

    lines = ("upper", "lower", "dch", "dcl", "dcm")
    params = {"period": 20}

    def __init__(self):
        period = max(2, int(self.p.period))
        upper = Highest(self.data.high, period=period)
        lower = Lowest(self.data.low, period=period)
        mid = (upper + lower) / 2
        self.lines.upper = upper
        self.lines.lower = lower
        self.lines.dch = upper
        self.lines.dcl = lower
        self.lines.dcm = mid


class DonchianChannelIndicator(DonchianChannel):
    """Compatibility alias for Donchian channel tests."""


class DonchianChannelWarmup(DonchianChannel):
    """Donchian channel variant preserving historical extra warm-up behavior."""

    def __init__(self):
        super().__init__()
        self.addminperiod(max(2, int(self.p.period)))


class KeltnerChannelIndicator(Indicator):
    """Keltner Channel using EMA middle line and ATR width."""

    lines = ("mid", "top", "bot")
    params = {"period": 20, "atr_mult": 2.0, "atr_period": 14}

    def __init__(self):
        self.l.mid = EMA(self.data.close, period=self.p.period)
        atr = ATR(self.data, period=self.p.atr_period)
        self.l.top = self.l.mid + self.p.atr_mult * atr
        self.l.bot = self.l.mid - self.p.atr_mult * atr


class ChandelierExitIndicator(Indicator):
    """Chandelier Exit volatility-based trailing stop levels."""

    lines = ("long", "short")
    params = {"period": 22, "multip": 3}
    plotinfo = {"subplot": False}

    def __init__(self):
        highest = Highest(self.data.high, period=self.p.period)
        lowest = Lowest(self.data.low, period=self.p.period)
        atr = self.p.multip * ATR(self.data, period=self.p.period)
        self.lines.long = highest - atr
        self.lines.short = lowest + atr
