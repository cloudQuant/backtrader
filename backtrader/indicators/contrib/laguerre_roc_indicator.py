#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from ...linebuffer import _factor_context_for_line, _reject_factor_infinity
from .. import Indicator

__all__ = [
    "LaguerreRocIndicator",
]


class LaguerreRocIndicator(Indicator):
    """Laguerre ROC indicator emitting value, midline, and color."""

    lines = ("lroc", "midline", "color")
    params = (
        ("vperiod", 5),
        ("gamma", 0.5),
        ("up_level", 0.75),
        ("dn_level", 0.25),
        ("point", 0.01),
    )

    def __init__(self):
        """Initialize rolling state and warm-up period."""
        self.addminperiod(int(self.p.vperiod) + 4)
        self._initialized = False
        self._l0 = self._l1 = self._l2 = self._l3 = None
        self._state_bar = None
        self._previous_state = None

    def next(self):
        """Calculate laguerre recursive values and output normalized ROC color."""
        if len(self.data) <= int(self.p.vperiod):
            self.lines.lroc[0] = 0.5
            self.lines.midline[0] = 0.5
            self.lines.color[0] = 2
            return
        if self._state_bar != len(self):
            self._previous_state = (
                self._initialized, self._l0, self._l1, self._l2, self._l3
            )
            self._state_bar = len(self)
        strict = _factor_context_for_line(self.lines.lroc) is not None

        def checked(value):
            if strict and math.isinf(value):
                _reject_factor_infinity(self.lines.lroc, value)
            return value

        reference = float(self.data.close[-int(self.p.vperiod)])
        current = float(self.data.close[0])
        if not math.isfinite(current) or not math.isfinite(reference):
            roc = float('nan')
        elif reference == 0:
            roc = float(self.p.point)
        else:
            delta = checked(current - reference)
            roc = checked(checked(delta / reference) + float(self.p.point))
        gamma = checked(float(self.p.gamma))
        initialized, l0_prev, l1_prev, l2_prev, l3_prev = self._previous_state
        if not initialized:
            l0_prev = l1_prev = l2_prev = l3_prev = roc
        l0 = checked(checked(checked(1.0 - gamma) * roc) + checked(gamma * l0_prev))
        l1 = checked(checked(checked(-gamma * l0) + l0_prev) + checked(gamma * l1_prev))
        l2 = checked(checked(checked(-gamma * l1) + l1_prev) + checked(gamma * l2_prev))
        l3 = checked(checked(checked(-gamma * l2) + l2_prev) + checked(gamma * l3_prev))
        cu = 0.0
        cd = 0.0
        if l0 >= l1:
            cu = checked(cu + checked(l0 - l1))
        else:
            cd = checked(cd + checked(l1 - l0))
        if l1 >= l2:
            cu = checked(cu + checked(l1 - l2))
        else:
            cd = checked(cd + checked(l2 - l1))
        if l2 >= l3:
            cu = checked(cu + checked(l2 - l3))
        else:
            cd = checked(cd + checked(l3 - l2))
        total = checked(cu + cd)
        lroc = checked(cu / total) if total != 0 else 0.5
        if not math.isfinite(lroc):
            color = float('nan')
        else:
            color = 2
            up_level = checked(float(self.p.up_level))
            if lroc > up_level:
                color = 4
            elif lroc > 0.5:
                color = 3
            dn_level = checked(float(self.p.dn_level))
            if lroc < dn_level:
                color = 0
            elif lroc < 0.5:
                color = 1
        self.lines.lroc[0] = lroc
        self.lines.midline[0] = 0.5
        self.lines.color[0] = color
        self._l0, self._l1, self._l2, self._l3 = l0, l1, l2, l3
        self._initialized = True
