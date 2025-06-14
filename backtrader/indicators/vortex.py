#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import backtrader as bt


# vortex指标
class Vortex(bt.Indicator):
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
        h0l1 = abs(self.data.high(0) - self.data.low(-1))
        vm_plus = bt.ind.SumN(h0l1, period=self.p.period)

        l0h1 = abs(self.data.low(0) - self.data.high(-1))
        vm_minus = bt.ind.SumN(l0h1, period=self.p.period)

        h0c1 = abs(self.data.high(0) - self.data.close(-1))
        l0c1 = abs(self.data.low(0) - self.data.close(-1))
        h0l0 = abs(self.data.high(0) - self.data.low(0))

        tr = bt.ind.SumN(bt.Max(h0l0, h0c1, l0c1), period=self.p.period)

        self.l.vi_plus = vm_plus / tr
        self.l.vi_minus = vm_minus / tr
