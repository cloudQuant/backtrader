#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from .indicator import Indicator

# Create different SIGNAL types
(
    SIGNAL_NONE,
    SIGNAL_LONGSHORT,
    SIGNAL_LONG,
    SIGNAL_LONG_INV,
    SIGNAL_LONG_ANY,
    SIGNAL_SHORT,
    SIGNAL_SHORT_INV,
    SIGNAL_SHORT_ANY,
    SIGNAL_LONGEXIT,
    SIGNAL_LONGEXIT_INV,
    SIGNAL_LONGEXIT_ANY,
    SIGNAL_SHORTEXIT,
    SIGNAL_SHORTEXIT_INV,
    SIGNAL_SHORTEXIT_ANY,
) = range(14)

# Different signal types
SignalTypes = [
    SIGNAL_NONE,
    SIGNAL_LONGSHORT,
    SIGNAL_LONG,
    SIGNAL_LONG_INV,
    SIGNAL_LONG_ANY,
    SIGNAL_SHORT,
    SIGNAL_SHORT_INV,
    SIGNAL_SHORT_ANY,
    SIGNAL_LONGEXIT,
    SIGNAL_LONGEXIT_INV,
    SIGNAL_LONGEXIT_ANY,
    SIGNAL_SHORTEXIT,
    SIGNAL_SHORTEXIT_INV,
    SIGNAL_SHORTEXIT_ANY,
]


# Inherit from Indicator, create a signal indicator
class Signal(Indicator):
    # Signal type
    SignalTypes = SignalTypes
    # Create a signal line
    lines = ("signal",)

    # Initialize
    def __init__(self):
        self.lines.signal = self.data0.lines[0]
        self.plotinfo.plotmaster = getattr(self.data0, "_clock", self.data0)
