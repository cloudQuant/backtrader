#!/usr/bin/env python
"""Renko Filter Module - Renko chart bars.

This module provides the Renko filter for converting price data
into Renko bricks for charting.

Classes:
    Renko: Creates Renko bars from price data.

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> data.addfilter(bt.filters.Renko(size=10))
    >>> cerebro.adddata(data)
"""
from . import Filter

__all__ = ["Renko"]


class Renko(Filter):
    """Modify the data stream to draw Renko bars (or bricks)

    Params:

      - ``hilo`` (default: *False*) Use high and low instead of close to decide
        if a new brick is needed

      - ``size`` (default: *None*) The size to consider for each brick

      - ``autosize`` (default: *20.0*) If *size* is *None*, this will be used
        to autocalculate the size of the bricks (simply dividing the current
        price by the given value)

      - ``dynamic`` (default: *False*) If *True* and using *autosize*, the size
        of the bricks will be recalculated when moving to a new brick. This
         will, of course, eliminate the perfect alignment of Renko bricks.

      - ``align`` (default: *1.0*) Factor used to align the price boundaries of
        the bricks. If the price is for example *3563.25* and *align* is
        *10.0*, the resulting aligned price will be *3560*. The calculation:

          - 3563.25 / 10.0 = 356.325
          - round it and remove the decimals -> 356
          - 356 * 10.0 -> 3560

      - ``roundstart`` (default: *True*) If *True*, round the initial start
        value to int. Else keep the original value, which should aid when
        backtesting penny stocks

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:chart_analysis:renko

    """

    params = (
        ("hilo", False),
        ("size", None),
        ("autosize", 20.0),
        ("dynamic", False),
        ("align", 1.0),
        ("roundstart", True),
    )

    def __init__(self, data, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        self._bot = None
        self._top = None
        self._size = None

    def nextstart(self, data):
        o = data.open[0]
        o = round(o / self.p.align, 0) * self.p.align  # aligned
        self._size = self.p.size or float(o // self.p.autosize)
        if self.p.roundstart:
            o = int(o)

        self._top = o + self._size
        self._bot = o - self._size

    def next(self, data):
        c = data.close[0]
        h = data.high[0]
        low = data.low[0]

        if self.p.hilo:
            hiprice = h
            loprice = low
        else:
            hiprice = loprice = c

        if hiprice >= self._top:
            # deliver a renko brick from top -> top + size
            self._bot = bot = self._top

            if self.p.size is None and self.p.dynamic:
                self._size = float(c // self.p.autosize)
                top = bot + self._size
                top = round(top / self.p.align, 0) * self.p.align  # aligned
            else:
                top = bot + self._size

            self._top = top

            data.open[0] = bot
            data.low[0] = bot
            data.high[0] = top
            data.close[0] = top
            data.volume[0] = 0.0
            data.openinterest[0] = 0.0
            return False  # length of data stream is unaltered

        elif loprice <= self._bot:
            # deliver a renko brick from bot -> bot - size
            self._top = top = self._bot

            if self.p.size is None and self.p.dynamic:
                self._size = float(c // self.p.autosize)
                bot = top - self._size
                bot = round(bot / self.p.align, 0) * self.p.align  # aligned
            else:
                bot = top - self._size

            self._bot = bot

            data.open[0] = top
            data.low[0] = top
            data.high[0] = bot
            data.close[0] = bot
            data.volume[0] = 0.0
            data.openinterest[0] = 0.0
            return False  # length of data stream is unaltered

        data.backwards()
        return True  # length of stream was changed, get new bar
