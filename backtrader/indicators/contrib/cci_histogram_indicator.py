#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    CommodityChannelIndex,
    Indicator,
)

__all__ = [
    "CCIHistogramIndicator",
]


class CCIHistogramIndicator(Indicator):
    """CCI-based colour-state indicator classifying CCI into three zones.

    Lines
    -----
    cci : float
        Commodity Channel Index value.
    color_state : float
        0.0 = overbought (CCI > high_level), 1.0 = neutral, 2.0 = oversold.
    hist_base : float
        Always 0.0 (placeholder for histogram baseline).
    """

    lines = ("cci", "color_state", "hist_base")
    params = (
        ("cci_period", 14),
        ("high_level", 100),
        ("low_level", -100),
    )

    def __init__(self):
        """Initialise indicator state: attach CCI sub-indicator and set minimum period."""
        cci = CommodityChannelIndex(self.data, period=int(self.p.cci_period))
        self.lines.cci = cci
        self.addminperiod(int(self.p.cci_period) + 2)

    def next(self):
        """Classify current CCI value into colour state (0=overbought, 1=neutral, 2=oversold)."""
        cci_value = float(self.lines.cci[0])
        color = 1.0
        if cci_value > float(self.p.high_level):
            color = 0.0
        elif cci_value < float(self.p.low_level):
            color = 2.0
        self.lines.color_state[0] = color
        self.lines.hist_base[0] = 0.0
