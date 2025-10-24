#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import backtrader as bt
from . import MovAv
from .sma import SMA

__all__ = ["HaDelta", "haD", "haDelta"]


# HaDelta指标
class HaDelta(bt.Indicator):
    """Heikin Ashi Delta. Defined by Dan Valcu in his book "Heikin-Ashi: How to
    Trade Without Candlestick Patterns ".

    This indicator measures the difference between Heikin Ashi close and open of
    Heikin Ashi candles, the body of the candle.

    To get signals add haDelta smoothed by 3 period moving average.

    For correct use, the data for the indicator must have been previously
    passed by the Heikin Ahsi filter.

    Formula:
      - HaDelta = Heikin Ashi close - Heikin Ashi open
      - smoothed = movav(haDelta, period)

    """

    alias = ("haD",)

    lines = ("haDelta", "smoothed")

    params = (
        ("period", 3),
        ("movav", SMA),
        ("autoheikin", True),
    )

    plotinfo = dict(subplot=True)

    plotlines = dict(
        haDelta=dict(color="red"),
        smoothed=dict(color="grey", _fill_gt=(0, "green"), _fill_lt=(0, "red")),
    )

    def __init__(self):
        d = bt.ind.HeikinAshi(self.data) if self.p.autoheikin else self.data

        # Use lines.ha_close and lines.ha_open for HeikinAshi, close and open for regular data
        if self.p.autoheikin:
            self.lines.haDelta = hd = d.lines.ha_close - d.lines.ha_open
        else:
            self.lines.haDelta = hd = d.close - d.open
        self.lines.smoothed = self.p.movav(hd, period=self.p.period)
        super(HaDelta, self).__init__()


haD = HaDelta
haDelta = HaDelta  # Alias for tests
