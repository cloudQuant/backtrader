#!/usr/bin/env python
"""Vortex Indicator Module - Vortex Movement Indicator.

This module provides the Vortex indicator, which measures trend movement
direction and identifies the start of a trend.

Classes:
    Vortex: Vortex Movement Indicator (Vortex).

Example:
    >>> class MyStrategy(bt.Strategy):
    ...     def __init__(self):
    ...         self.vortex = bt.indicators.Vortex(self.data, period=14)
    ...
    ...     def next(self):
    ...         if self.vortex.vi_plus[0] > self.vortex.vi_minus[0]:
    ...             self.buy()
"""
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
# Copyright (C) 2015-2020 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from .. import Indicator, Max, SumN

__all__ = ["Vortex"]


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

        Calculates the Vortex Movement Indicator components.
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
