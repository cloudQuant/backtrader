#!/usr/bin/env python
"""Yahoo Finance Data Feed Module - Yahoo CSV data parsing.

This module provides the YahooFinanceCSVData feed for parsing
pre-downloaded Yahoo Finance CSV files.

Classes:
    YahooFinanceCSVData: Parses Yahoo Finance format CSV files.

Example:
    >>> data = bt.feeds.YahooFinanceCSVData(dataname='yahoo.csv')
    >>> cerebro.adddata(data)
"""
import collections
import io
import itertools
from datetime import date, datetime

from .. import feed
from ..dataseries import TimeFrame
from ..utils import date2num


class YahooFinanceCSVData(feed.CSVDataBase):
    """
    Parses pre-downloaded Yahoo CSV Data Feeds (or locally generated if they
    comply to the Yahoo format)

    Specific parameters:

      - ``dataname``

        The filename to parse or a file-like object

      - ``reverse``

        It is assumed that locally stored files have the newest lines at the
        bottom

        If this is not the case, pass *reverse* = ``True``

      - ``adjclose`` (default: ``True``)
        Whether to use the dividend/split adjusted close and adjust all
        values according to it.

      - ``adjvolume`` (default: ``True``)
        Do also adjust ``volume`` if ``adjclose`` is also ``True``

      - ``round`` (default: ``True``)
        Whether to round the values to a specific number of decimals after
        having adjusted the close

      - ``roundvolume`` (default: ``0``)
        Round the resulting volume to the given number of decimals after having
        adjusted it

      - ``decimals`` (default: ``2``)
        Number of decimals to round to

      - ``swapcloses`` (default: ``False``)
        [2018-11-16] It would seem that the order of *close* and *adjusted
        close* is now fixed. The parameter is retained, in case the need to
        swap the columns again arose.

    """

    # Add a line
    lines = ("adjclose",)

    params = (
        ("reverse", False),
        ("adjclose", True),
        ("adjvolume", True),
        ("round", True),
        ("decimals", 2),
        ("roundvolume", False),
        ("swapcloses", False),
    )

    def start(self):
        super().start()
        # If reverse is False, return directly, don't run code below
        if not self.params.reverse:
            return

        # Yahoo sends data in reverse order and the file is still unreversed
        # Use deque double-ended queue, appending to left is much more efficient than list.
        # If file dates are reversed, data is reversed during transfer, so dates in new file are in correct order
        dq = collections.deque()
        for line in self.f:
            dq.appendleft(line)
        # Create a string buffer object, write queue data to file, move pointer to 0th character, close file, assign file to self.f
        f = io.StringIO(newline=None)
        f.writelines(dq)
        f.seek(0)
        self.f.close()
        self.f = f

    def _loadline(self, linetokens):
        # _loadline code is relatively familiar, all quite similar
        # A while loop
        while True:
            nullseen = False
            for tok in linetokens[1:]:
                if tok == "null":
                    nullseen = True
                    linetokens = self._getnextline()  # refetch tokens
                    if not linetokens:
                        return False  # cannot fetch, go away

                    # out of for to carry on wiwth while True logic
                    break

            if not nullseen:
                break  # can proceed
        # Counter, value increases by 1 when calling next(i)
        i = itertools.count(0)
        # Get time string
        dttxt = linetokens[next(i)]
        # Generate time
        dt = date(int(dttxt[0:4]), int(dttxt[5:7]), int(dttxt[8:10]))
        # Convert time to number
        dtnum = date2num(datetime.combine(dt, self.p.sessionend))
        # Assign value to datetime line
        self.lines.datetime[0] = dtnum
        # Get open, high, low, close, open interest
        o = float(linetokens[next(i)])
        h = float(linetokens[next(i)])
        low = float(linetokens[next(i)])
        c = float(linetokens[next(i)])
        self.lines.openinterest[0] = 0.0

        # 2018-11-16 ... Adjusted Close seems to always be delivered after
        # the close and before the volume columns
        # Get adjusted price
        adjustedclose = float(linetokens[next(i)])
        # Try to get volume, if not available, set to 0
        try:
            v = float(linetokens[next(i)])
        except Exception as e:  # cover the case in which volume is "null"
            print(e)
            v = 0.0
        # If swapping close price and adjusted close price, perform swap
        if self.p.swapcloses:  # swap closing prices if requested
            c, adjustedclose = adjustedclose, c
        # Calculate adjustment factor, the calculation method seems different from conventional usage, but not necessarily wrong
        adjfactor = c / adjustedclose

        # in v7 "adjusted prices" seem to be given, scale back for non adj
        # If price adjustment is needed, divide by adjustment factor
        if self.params.adjclose:
            o /= adjfactor
            h /= adjfactor
            low /= adjfactor
            c = adjustedclose
            # If the price goes down, volume must go up and viceversa
            # If adjusting volume, the logic here has some issues, but shouldn't affect usage as stock mergers may exist
            # todo pay attention to logic
            if self.p.adjvolume:
                v *= adjfactor
        # If rounding is needed, round the prices
        if self.p.round:
            decimals = self.p.decimals
            o = round(o, decimals)
            h = round(h, decimals)
            low = round(low, decimals)
            c = round(c, decimals)
        # Round the volume
        v = round(v, self.p.roundvolume)
        # Assign calculated data to corresponding lines
        self.lines.open[0] = o
        self.lines.high[0] = h
        self.lines.low[0] = low
        self.lines.close[0] = c
        self.lines.volume[0] = v
        self.lines.adjclose[0] = adjustedclose

        return True


class YahooLegacyCSV(YahooFinanceCSVData):
    """
    This is intended to load files which were downloaded before Yahoo
    discontinued the original service in May-2017
    Used to load data downloaded before May 2017
    """

    params = (("version", ""),)


class YahooFinanceCSV(feed.CSVFeedBase):
    DataCls = YahooFinanceCSVData


# todo Test this class when time permits to see if it still works, if so, try to add comments
class YahooFinanceData(YahooFinanceCSVData):
    # This is a method to directly crawl data from Yahoo
    """
    Executes a direct download of data from Yahoo servers for the given time
    range.

    Specific parameters (or specific meaning):

      - ``dataname``

        The ticker to download ('YHOO' for Yahoo own stock quotes)

      - ``proxies``

        A dict indicating which proxy to go through for the download as in
        {'http': 'http://myproxy.com'} or {'http': 'http://127.0.0.1:8080'}

      - ``period``

        The timeframe to download data in. Pass 'w' for weekly and 'm' for
        monthly.

      - ``reverse``

        [2018-11-16] The latest incarnation of Yahoo online downloads returns
        the data in the proper order. The default value of ``reverse`` for the
        online download is therefore set to ``False``

      - ``adjclose``

        Whether to use the dividend/split adjusted close and adjust all values
        according to it.

      - ``urlhist``

        The url of the historical quotes in Yahoo Finance used to gather a
        ``crumb`` authorization cookie for the download

      - ``urldown``

        The url of the actual download server

      - ``retries``

        Number of times (each) to try to get a ``crumb`` cookie and download
        the data

    """

    params = (
        ("proxies", {}),
        ("period", "d"),
        ("reverse", False),
        ("urlhist", "https://finance.yahoo.com/quote/{}/history"),
        ("urldown", "https://query1.finance.yahoo.com/v7/finance/download"),
        ("retries", 3),
    )

    def __init__(self):
        self.error = None

    def start_v7(self):
        try:
            import requests
        except ImportError:
            msg = (
                "The new Yahoo data feed requires to have the requests "
                "module installed. Please use pip install requests or "
                "the method of your choice"
            )
            raise Exception(msg)

        self.error = None
        url = self.p.urlhist.format(self.p.dataname)

        sesskwargs = dict()
        if self.p.proxies:
            sesskwargs["proxies"] = self.p.proxies

        crumb = None
        sess = requests.Session()
        for i in range(self.p.retries + 1):  # at least once
            resp = sess.get(url, **sesskwargs)
            if resp.status_code != requests.codes.ok:
                continue

            txt = resp.text
            i = txt.find("CrumbStore")
            if i == -1:
                continue
            i = txt.find("crumb", i)
            if i == -1:
                continue
            istart = txt.find('"', i + len("crumb") + 1)
            if istart == -1:
                continue
            istart += 1
            iend = txt.find('"', istart)
            if iend == -1:
                continue

            crumb = txt[istart:iend]
            crumb = crumb.encode("ascii").decode("unicode-escape")
            break

        if crumb is None:
            self.error = "Crumb not found"
            self.f = None
            return

        from ..utils.py3 import urlquote

        crumb = urlquote(crumb)

        # urldown/ticker?period1=posix1&period2=posix2&interval=1d&events=history&crumb=crumb

        # Try to download
        urld = f"{self.p.urldown}/{self.p.dataname}"

        urlargs = []
        posix = date(1970, 1, 1)
        if self.p.todate is not None:
            period2 = (self.p.todate.date() - posix).total_seconds()
            urlargs.append(f"period2={int(period2)}")

        if self.p.todate is not None:
            period1 = (self.p.fromdate.date() - posix).total_seconds()
            urlargs.append(f"period1={int(period1)}")

        intervals = {
            TimeFrame.Days: "1d",
            TimeFrame.Weeks: "1wk",
            TimeFrame.Months: "1mo",
        }

        urlargs.append(f"interval={intervals[self.p.timeframe]}")
        urlargs.append("events=history")
        urlargs.append(f"crumb={crumb}")

        urld = "{}?{}".format(urld, "&".join(urlargs))
        f = None
        for i in range(self.p.retries + 1):  # at least once
            resp = sess.get(urld, **sesskwargs)
            if resp.status_code != requests.codes.ok:
                continue

            ctype = resp.headers["Content-Type"]
            # Cover as many text types as possible for Yahoo changes
            if not ctype.startswith("text/"):
                self.error = "Wrong content type: %s" % ctype
                continue  # HTML returned? wrong url?

            # buffer everything from the socket into a local buffer
            try:
                # r.encoding = 'UTF-8'
                f = io.StringIO(resp.text, newline=None)
            except Exception as e:
                print(e)
                continue  # try again if possible

            break

        self.f = f

    def start(self):
        self.start_v7()

        # Prepared a "path" file -  CSV Parser can take over
        super().start()


class YahooFinance(feed.CSVFeedBase):
    DataCls = YahooFinanceData
    # Get specific parameters and form tuple
    params = DataCls.params._gettuple()
