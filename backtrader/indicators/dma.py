#!/usr/bin/env python
"""DMA Indicator Module - Dickson Moving Average.

This module provides the Dickson Moving Average (DMA) developed
by Nathan Dickson, combining ZeroLag and Hull moving averages.

Classes:
    DicksonMovingAverage: DMA indicator (aliases: DMA, DicksonMA).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.dma = bt.indicators.DMA(self.data.close, period=20, gainlimit=50, hperiod=7)

        def next(self):
            if self.data.close[0] > self.dma[0]:
                self.buy()
            elif self.data.close[0] < self.dma[0]:
                self.sell()
"""
import math

from . import MovingAverageBase, ZeroLagIndicator
from .ema import EMA
from .hma import HMA


class DicksonMovingAverage(MovingAverageBase):
    """By Nathan Dickson

    The *Dickson Moving Average* combines the ``ZeroLagIndicator`` (aka
    *ErrorCorrecting* or *EC*) by *Ehlers*, and the ``HullMovingAverage`` to
    try to deliver a result close to that of the *Jurik* Moving Averages

    Formula:
      - ec = ZeroLagIndicator(period, gainlimit)
      - hma = HullMovingAverage(hperiod)

      - dma = (ec + hma) / 2

      - The default moving average for the *ZeroLagIndicator* is EMA, but can
        be changed with the parameter ``_movav``

        ::note:: the passed moving average must calculate alpha (and 1 - alpha)
                and make them available as attributes ``alpha`` and ``alpha1``

      - The second moving average can be changed from *Hull* to anything else with
        the param *_hma*

    See also:
      - https://www.reddit.com/r/algotrading/comments/4xj3vh/dickson_moving_average
    """

    alias = (
        "DMA",
        "DicksonMA",
    )
    lines = ("dma",)
    params = (
        ("gainlimit", 50),
        ("hperiod", 7),
        ("_movav", EMA),
        ("_hma", HMA),
    )

    def _plotlabel(self):
        plabels = [self.p.period, self.p.gainlimit, self.p.hperiod]
        plabels += [self.p._movav] * self.p.notdefault("_movav")
        plabels += [self.p._hma] * self.p.notdefault("_hma")
        return plabels

    def __init__(self):
        """Initialize the Dickson Moving Average.

        Creates ZeroLag and Hull MA sub-indicators.
        """
        super().__init__()
        self.ec = ZeroLagIndicator(
            period=self.p.period, gainlimit=self.p.gainlimit, _movav=self.p._movav
        )
        self.hull = self.p._hma(period=self.p.hperiod)

    def next(self):
        """Calculate DMA for the current bar.

        Formula: DMA = (ZeroLag + HMA) / 2
        """
        self.lines.dma[0] = (self.ec[0] + self.hull[0]) / 2.0

    def once(self, start, end):
        """Calculate DMA in runonce mode."""
        ec_array = self.ec.lines[0].array
        hull_array = self.hull.lines[0].array
        larray = self.lines.dma.array

        while len(larray) < end:
            larray.append(0.0)

        for i in range(start, min(end, len(ec_array), len(hull_array))):
            ec_val = ec_array[i] if i < len(ec_array) else 0.0
            hull_val = hull_array[i] if i < len(hull_array) else 0.0

            if isinstance(ec_val, float) and math.isnan(ec_val):
                larray[i] = float("nan")
            elif isinstance(hull_val, float) and math.isnan(hull_val):
                larray[i] = float("nan")
            else:
                larray[i] = (ec_val + hull_val) / 2.0
