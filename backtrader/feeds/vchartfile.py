#!/usr/bin/env python
"""VChartFile Data Feed Module - VisualChart file interface.

This module provides the VChartFile feed for reading VisualChart
binary on-disk files using market codes.

Classes:
    VChartFile: VisualChart binary file feed by market code.

Example:
    >>> data = bt.feeds.VChartFile(dataname='015ES')
    >>> cerebro.adddata(data)
"""
import os.path
from datetime import datetime
from struct import unpack

from .. import stores
from ..dataseries import TimeFrame
from ..feed import DataBase
from ..utils import date2num  # avoid dict lookups


class VChartFile(DataBase):
    """
    Support for `Visual Chart <www.visualchart.com>`_ binary on-disk files for
    both daily and intradaily formats.

    Note:

      - ``dataname``: Market code displayed by Visual Chart. Example: 015ES for
        EuroStoxx 50 continuous future
    """

    def __init__(self, **kwargs):
        """Initialize the VChartFile data feed.

        Args:
            **kwargs: Keyword arguments for data feed configuration.
        """
        super().__init__(**kwargs)
        # Handle original metaclass registration functionality
        if hasattr(stores, "VChartFile"):
            stores.VChartFile.DataCls = self.__class__

        self.f = None
        self._barfmt = None
        self._dtsize = None
        self._barsize = None
        self._store = None

    def start(self):
        """Start the VChartFile data feed.

        Opens the VisualChart binary file for reading.
        """
        super().start()
        if self._store is None:
            self._store = stores.VChartFile()
            self._store.start()

        self._store.start(data=self)

        # Choose extension and extraction/calculation parameters
        if self.p.timeframe < TimeFrame.Minutes:
            ext = ".tck"  # seconds will still need resampling
            # FIXME: find reference to tick counter for format
        elif self.p.timeframe < TimeFrame.Days:
            ext = ".min"
            self._dtsize = 2
            self._barsize = 32
            self._barfmt = "IIffffII"
        else:
            ext = ".fd"
            self._barsize = 28
            self._dtsize = 1
            self._barfmt = "IffffII"

        # Construct a full path
        basepath = self._store.get_datapath()

        # Example: 01 + 0 + 015ES + .fd -> 010015ES.fd
        dataname = "01" + "0" + self.p.dataname + ext
        # 015ES -> 0 + 015 -> 0015
        mktcode = "0" + self.p.dataname[0:3]

        # basepath/0015/010015ES.fd
        path = os.path.join(basepath, mktcode, dataname)
        try:
            self.f = open(path, "rb")
        except OSError:
            self.f = None

    def stop(self):
        """Stop the VChartFile data feed.

        Closes the open file handle.
        """
        if self.f is not None:
            self.f.close()
            self.f = None

    def _load(self):
        if self.f is None:
            return False  # cannot load more

        try:
            bardata = self.f.read(self._barsize)
        except OSError:
            self.f = None  # cannot return, nullify file
            return False  # cannot load more

        if not bardata or len(bardata) < self._barsize:
            self.f = None  # cannot return, nullify file
            return False  # cannot load more

        try:
            bdata = unpack(self._barfmt, bardata)
        except Exception as e:
            print(e)
            self.f = None
            return False

        # First Date
        y, md = divmod(bdata[0], 500)  # Years stored as if they had 500 days
        m, d = divmod(md, 32)  # Months stored as if they had 32 days
        dt = datetime(y, m, d)

        # Time
        if self._dtsize > 1:  # Minute Bars
            # Daily Time is stored in seconds
            hhmm, ss = divmod(bdata[1], 60)
            hh, mm = divmod(hhmm, 60)
            dt = dt.replace(hour=hh, minute=mm, second=ss)
        else:  # Daily Bars
            dt = datetime.combine(dt, self.p.sessionend)

        self.lines.datetime[0] = date2num(dt)  # Store time

        # Get the rest of the fields
        o, h, low, c, v, oi = bdata[self._dtsize :]
        self.lines.open[0] = o
        self.lines.high[0] = h
        self.lines.low[0] = low
        self.lines.close[0] = c
        self.lines.volume[0] = v
        self.lines.openinterest[0] = oi

        return True  # a bar has been successfully loaded
