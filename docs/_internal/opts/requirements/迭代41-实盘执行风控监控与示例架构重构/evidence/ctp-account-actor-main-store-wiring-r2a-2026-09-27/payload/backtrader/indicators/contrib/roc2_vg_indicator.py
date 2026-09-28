#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "ROC2VGIndicator",
]


def _calc_roc(price, prev_price, roc_type):
    if prev_price == 0:
        return 0.0
    if roc_type == 1:  # MOM
        return price - prev_price
    if roc_type == 2:  # ROC
        return ((price / prev_price) - 1) * 100
    if roc_type == 3:  # ROCP
        return (price - prev_price) / prev_price
    if roc_type == 4:  # ROCR
        return price / prev_price
    if roc_type == 5:  # ROCR100
        return (price / prev_price) * 100
    return (price - prev_price) / prev_price


class ROC2VGIndicator(Indicator):
    """Reconstructs ROC2_VG indicator.

    DRAW_FILLING between ROC1 and ROC2.
    Buffer 0 = ROC1 (period1, type1), Buffer 1 = ROC2 (period2, type2).
    """

    lines = ("roc1", "roc2")
    params = (
        ("roc_period1", 8),
        ("roc_type1", 1),
        ("roc_period2", 14),
        ("roc_type2", 1),
    )

    def __init__(self):
        """Initialize ROC periods and required minimum history window."""
        self._p1 = int(self.p.roc_period1)
        self._p2 = int(self.p.roc_period2)
        self._t1 = int(self.p.roc_type1)
        self._t2 = int(self.p.roc_type2)
        self.addminperiod(max(self._p1, self._p2) + 2)

    def next(self):
        """Populate ``roc1`` and ``roc2`` for the current bar."""
        price = float(self.data.close[0])

        if self._p1 < len(self.data):
            prev1 = float(self.data.close[-self._p1])
        else:
            prev1 = price
        self.lines.roc1[0] = _calc_roc(price, prev1, self._t1)

        if self._p2 < len(self.data):
            prev2 = float(self.data.close[-self._p2])
        else:
            prev2 = price
        self.lines.roc2[0] = _calc_roc(price, prev2, self._t2)
