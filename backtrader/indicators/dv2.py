#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from . import Indicator, SMA, PercentRank


__all__ = ["DV2"]


# RSI指标的替代品
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
        chl = self.data.close / ((self.data.high + self.data.low) / 2.0)
        dvu = self.p._movav(chl, period=self.p.maperiod)
        self.lines.dv2 = PercentRank(dvu, period=self.p.period) * 100
        super(DV2, self).__init__()
