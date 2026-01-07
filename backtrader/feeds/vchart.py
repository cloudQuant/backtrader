#!/usr/bin/env python
"""Visual Chart Binary Data Feed Module - VisualChart binary files.

This module provides the VChartData feed for reading VisualChart
binary on-disk data files.

Classes:
    VChartData: Reads VisualChart binary data files.

Example:
    >>> data = bt.feeds.VChartData(dataname='data.fd')
    >>> cerebro.adddata(data)
"""
import datetime
import os.path
import struct

from .. import feed
from ..dataseries import TimeFrame
from ..utils import date2num


# Process Visual Chart binary data, supports daily or intraday data formats
class VChartData(feed.DataBase):
    """
    Support for `Visual Chart <www.visualchart.com>`_ binary on-disk files for
    both daily and intradaily formats.

    Note:

      - ``dataname``: to file or open file-like an object

        If a file-like object is passed, the ``timeframe`` parameter will be
        used to determine which is the actual timeframe.

        Else the file extension (``.fd`` for daily and ``.min`` for intraday)
        will be used.
    """

    def __init__(self):
        """Initialize the VChart data feed."""
        self.barfmt = None
        self.f = None
        self.barsize = None
        self.dtsize = None
        self.ext = None

    def start(self):
        """Start the VChart data feed.

        Opens the VisualChart binary file for reading.
        """
        super().start()

        # Not yet known if an extension is needed
        self.ext = ""

        if not hasattr(self.p.dataname, "read"):
            # assume is a string because it has no write method

            if self.p.dataname.endswith(".fd"):
                self.p.timeframe = TimeFrame.Days
            elif self.p.dataname.endswith(".min"):
                self.p.timeframe = TimeFrame.Minutes
            else:
                # Neither fd nor min ... just the code, assign extension
                if self.p.timeframe == TimeFrame.Days:
                    self.ext = ".fd"
                else:
                    self.ext = ".min"

        if self.p.timeframe >= TimeFrame.Days:
            self.barsize = 28
            self.dtsize = 1
            self.barfmt = "IffffII"
        else:
            self.dtsize = 2
            self.barsize = 32
            self.barfmt = "IIffffII"

        self.f = None
        if hasattr(self.p.dataname, "read"):
            # A file has been passed in (ex: from a GUI)
            self.f = self.p.dataname
        else:
            dataname = self.p.dataname + self.ext
            # Let an exception propagate
            self.f = open(dataname, "rb")

    def stop(self):
        """Stop the VChart data feed.

        Closes the open file handle.
        """
        if self.f is not None:
            self.f.close()
            self.f = None

    def _load(self):
        if self.f is None:
            return False

        # Let an exception propagate to let the caller know
        bardata = self.f.read(self.barsize)
        if not bardata:
            return False

        bdata = struct.unpack(self.barfmt, bardata)

        # Years are stored as if they had 500 days
        y, md = divmod(bdata[0], 500)
        # Months are stored as if they had 32 days
        m, d = divmod(md, 32)
        dt = datetime.datetime(y, m, d)

        if self.dtsize > 1:  # Minute Bars
            # Daily Time is stored in seconds
            hhmm, ss = divmod(bdata[1], 60)
            hh, mm = divmod(hhmm, 60)
            dt = dt.replace(hour=hh, minute=mm, second=ss)

        self.lines.datetime[0] = date2num(dt)

        o, h, low, c, v, oi = bdata[self.dtsize :]
        self.lines.open[0] = o
        self.lines.high[0] = h
        self.lines.low[0] = low
        self.lines.close[0] = c
        self.lines.volume[0] = v
        self.lines.openinterest[0] = oi

        return True


class VChartFeed(feed.FeedBase):
    """VisualChart feed class.

    Wrapper class for VChartData feed functionality.
    """

    DataCls = VChartData

    params = (("basepath", ""),) + DataCls.params._gettuple()

    def _getdata(self, dataname, **kwargs):
        maincode = dataname[0:2]
        subcode = dataname[2:6]

        datapath = os.path.join(
            self.p.basepath,
            "RealServer",
            "Data",
            maincode,
            subcode,
            dataname,  # 01 00XX
        )

        newkwargs = self.p._getkwargs()
        newkwargs.update(kwargs)
        kwargs["dataname"] = datapath
        return self.DataCls(**kwargs)
