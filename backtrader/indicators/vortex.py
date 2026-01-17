#!/usr/bin/env python
"""Vortex Indicator Module - Vortex trend indicator.

This module provides the Vortex indicator for identifying trend
direction and strength.

Classes:
    Vortex: Vortex indicator with VI+ and VI- lines.

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.vortex = bt.indicators.Vortex(self.data, period=14)

        def next(self):
            # VI+ crossing above VI- indicates uptrend
            if self.vortex.vi_plus[0] > self.vortex.vi_minus[0]:
                self.buy()
            # VI- crossing above VI+ indicates downtrend
            elif self.vortex.vi_minus[0] > self.vortex.vi_plus[0]:
                self.sell()
"""
from . import Indicator, Max, SumN


class Vortex(Indicator):
    """
    See:
      - http://www.vortexindicator.com/VFX_VORTEX.PDF

    """

    lines = (
        "vi_plus",
        "vi_minus",
    )

    params = (("period", 14),)

    plotlines = dict(vi_plus=dict(_name="+VI"), vi_minus=dict(_name="-VI"))

    def __init__(self):
        """Initialize the Vortex indicator.

        Sets up VI+ and VI- calculations based on True Range and
        directional movement.
        """
        h0l1 = abs(self.data.high(0) - self.data.low(-1))
        vm_plus = SumN(h0l1, period=self.p.period)

        l0h1 = abs(self.data.low(0) - self.data.high(-1))
        vm_minus = SumN(l0h1, period=self.p.period)

        h0c1 = abs(self.data.high(0) - self.data.close(-1))
        l0c1 = abs(self.data.low(0) - self.data.close(-1))
        h0l0 = abs(self.data.high(0) - self.data.low(0))

        tr = SumN(Max(h0l0, h0c1, l0c1), period=self.p.period)

        self.l.vi_plus = vm_plus / tr
        self.l.vi_minus = vm_minus / tr
