#!/usr/bin/env python
import collections
import io
import itertools
from datetime import date, datetime

from .. import feed
from ..utils import date2num
from ..utils.py3 import urlquote

__all__ = ["QuandlCSV", "Quandl"]


# Process Quandl CSV data
class QuandlCSV(feed.CSVDataBase):
    """
    Parses pre-downloaded Quandl CSV Data Feeds (or locally generated if they
    comply to the Quandl format)

    Specific parameters:

      - ``dataname``: The filename to parse or a file-like object

      - ``reverse`` (default: ``False``)

        It is assumed that locally stored files have already been reversed
        during the download process

      - ``adjclose`` (default: ``True``)

        Whether to use the dividend/split adjusted close and adjust all
        values according to it.

      - ``round`` (default: ``False``)

        Whether to round the values to a specific number of decimals after
        having adjusted the close

      - ``decimals`` (default: ``2``)

        Number of decimals to round to
    """

    _online = False  # flag to avoid double reversal

    params = (
        ("reverse", False),
        ("adjclose", True),
        ("round", False),
        ("decimals", 2),
    )

    def start(self):
        super().start()

        if not self.params.reverse:
            return
        elif self._online:
            return  # revers is True but also online, managed with order = asc

        # Quandl data can be in reverse order -> reverse
        dq = collections.deque()
        for line in self.f:
            dq.appendleft(line)

        f = io.StringIO(newline=None)
        f.writelines(dq)
        f.seek(0)
        self.f.close()
        self.f = f

    def _loadline(self, linetokens):
        i = itertools.count(0)

        dttxt = linetokens[next(i)]  # YYYY-MM-DD
        dt = date(int(dttxt[0:4]), int(dttxt[5:7]), int(dttxt[8:10]))
        dtnum = date2num(datetime.combine(dt, self.p.sessionend))

        self.lines.datetime[0] = dtnum
        if self.p.adjclose:
            for _ in range(7):
                next(i)  # skip ohlcv, ex-dividend, split ratio

        o = float(linetokens[next(i)])
        h = float(linetokens[next(i)])
        low = float(linetokens[next(i)])
        c = float(linetokens[next(i)])
        v = float(linetokens[next(i)])
        self.lines.openinterest[0] = 0.0

        if self.p.round:
            decimals = self.p.decimals
            o = round(o, decimals)
            h = round(h, decimals)
            low = round(low, decimals)
            c = round(c, decimals)
            v = round(v, decimals)

        self.lines.open[0] = o
        self.lines.high[0] = h
        self.lines.low[0] = low
        self.lines.close[0] = c
        self.lines.volume[0] = v

        return True


class Quandl(QuandlCSV):
    """
    Executes a direct download of data from Quandl servers for the given time
    range.

    Specific parameters (or specific meaning):

      - ``dataname``

        The ticker to download ('YHOO', for example)

      - ``baseurl``

        The server url. Someone might decide to open a Quandl compatible
        service in the future.

      - ``proxies``

        A dict indicating which proxy to go through for the download as in
        {'http': 'http://myproxy.com'} or {'http': 'http://127.0.0.1:8080'}

      - ``buffered``

        If True, the entire socket connection will be buffered locally before
        parsing starts.

      - ``reverse``

        Quandl returns the value in descending order (newest first). If this is
        ``True`` (the default), the request will tell Quandl to return in
        ascending (oldest to newest) format

      - ``adjclose``

        Whether to use the dividend/split adjusted close and adjust all values
        according to it.

      - ``apikey``

        Apikey identification in case it may be needed

      - ``dataset``

        String identifying the dataset to query. Defaults to ``WIKI``

    """

    _online = True  # flag to avoid double reversal

    params = (
        ("baseurl", "https://www.quandl.com/api/v3/datasets"),
        ("proxies", {}),
        ("buffered", True),
        ("reverse", True),
        ("apikey", None),
        ("dataset", "WIKI"),
    )

    def __init__(self):
        self.error = None

    def start(self):
        self.error = None

        url = f"{self.p.baseurl}/{self.p.dataset}/{urlquote(self.p.dataname)}.csv"

        urlargs = []
        if self.p.reverse:
            urlargs.append("order=asc")

        if self.p.apikey is not None:
            urlargs.append(f"api_key={self.p.apikey}")

        if self.p.fromdate:
            dtxt = self.p.fromdate.strftime("%Y-%m-%d")
            urlargs.append(f"start_date={dtxt}")

        if self.p.todate:
            dtxt = self.p.todate.strftime("%Y-%m-%d")
            urlargs.append(f"end_date={dtxt}")

        if urlargs:
            url += "?" + "&".join(urlargs)

        from ..utils.py3 import ProxyHandler, build_opener, install_opener, urlopen

        if self.p.proxies:
            proxy = ProxyHandler(self.p.proxies)
            opener = build_opener(proxy)
            install_opener(opener)

        try:
            datafile = urlopen(url)
        except OSError as e:
            self.error = str(e)
            # leave us empty
            return

        if datafile.headers["Content-Type"] != "text/csv":
            self.error = "Wrong content type: %s" % datafile.headers
            return  # HTML returned? wrong url?

        if self.params.buffered:
            # buffer everything from the socket into a local buffer
            f = io.StringIO(datafile.read().decode("utf-8"), newline=None)
            datafile.close()
        else:
            f = datafile

        self.f = f

        # Prepared a "path" file -  CSV Parser can take over
        super().start()
