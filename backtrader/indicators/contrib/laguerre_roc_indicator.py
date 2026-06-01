#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

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

    def next(self):
        """Calculate laguerre recursive values and output normalized ROC color."""
        if len(self.data) <= int(self.p.vperiod):
            self.lines.lroc[0] = 0.5
            self.lines.midline[0] = 0.5
            self.lines.color[0] = 2
            return
        reference = float(self.data.close[-int(self.p.vperiod)])
        if reference == 0:
            roc = float(self.p.point)
        else:
            roc = (float(self.data.close[0]) - reference) / reference + float(self.p.point)
        gamma = float(self.p.gamma)
        if not self._initialized:
            self._l0 = self._l1 = self._l2 = self._l3 = roc
            self._initialized = True
        l0_prev, l1_prev, l2_prev, l3_prev = self._l0, self._l1, self._l2, self._l3
        l0 = (1.0 - gamma) * roc + gamma * l0_prev
        l1 = -gamma * l0 + l0_prev + gamma * l1_prev
        l2 = -gamma * l1 + l1_prev + gamma * l2_prev
        l3 = -gamma * l2 + l2_prev + gamma * l3_prev
        cu = 0.0
        cd = 0.0
        if l0 >= l1:
            cu += l0 - l1
        else:
            cd += l1 - l0
        if l1 >= l2:
            cu += l1 - l2
        else:
            cd += l2 - l1
        if l2 >= l3:
            cu += l2 - l3
        else:
            cd += l3 - l2
        lroc = cu / (cu + cd) if (cu + cd) != 0 else 0.5
        color = 2
        if lroc > float(self.p.up_level):
            color = 4
        elif lroc > 0.5:
            color = 3
        if lroc < float(self.p.dn_level):
            color = 0
        elif lroc < 0.5:
            color = 1
        self.lines.lroc[0] = lroc
        self.lines.midline[0] = 0.5
        self.lines.color[0] = color
        self._l0, self._l1, self._l2, self._l3 = l0, l1, l2, l3
