#!/usr/bin/env python
"""DV2 Indicator Module - RSI(2) alternative.

This module provides the DV2 indicator developed by David Varadi
as an alternative to RSI(2).

Classes:
    DV2: DV2 indicator (RSI(2) alternative).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.dv2 = bt.indicators.DV2(self.data)

        def next(self):
            if self.dv2[0] > 50:
                self.buy()
"""

from . import SMA, Indicator, PercentRank

__all__ = ["DV2"]


class DV2(Indicator):
    """
    RSI(2) alternative
    Developed by David Varadi of http://cssanalytics.wordpress.com/

    This seems to be the *Bounded* version.

    See also:

      - http://web.archive.org/web/20131216100741/http://quantingdutchman.wordpress.com/2010/08/06/dv2-indicator-for-amibroker/

    """

    params = (
        ("period", 252),
        ("maperiod", 2),
        ("_movav", SMA),
    )
    lines = ("dv2",)

    def __init__(self):
        """Initialize the DV2 indicator calculation.

        Calculates:
        1. CHL = close / ((high + low) / 2)
        2. DVU = moving average of CHL
        3. DV2 = PercentRank(DVU) * 100
        """
        chl = self.data.close / ((self.data.high + self.data.low) / 2.0)
        dvu = self.p._movav(chl, period=self.p.maperiod)
        self.lines.dv2 = PercentRank(dvu, period=self.p.period) * 100
        super().__init__()
