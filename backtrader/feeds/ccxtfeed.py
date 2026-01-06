#!/usr/bin/env python

import time
from datetime import datetime

from backtrader.feed import DataBase
from backtrader.stores import ccxtstore
from backtrader.utils.py3 import queue

from ..utils import date2num


class CCXTFeed(DataBase):
    """
    CryptoCurrency eXchange Trading Library Data Feed.
    Params:
      - ``historical`` (default: ``False``)
        If set to ``True`` the data feed will stop after doing the first
        download of data.
        The standard data feed parameters ``fromdate`` and ``todate`` will be
        used as reference.
      - ``backfill_start`` (default: ``True``)
        Perform backfilling at the start. The maximum possible historical data
        will be fetched in a single request.

    Changes From Ed's pacakge

        - Added option to send some additional fetch_ohlcv_params. Some exchanges (e.g., Bitmex)
          support sending some additional fetch parameters.
        - Added drop_newest option to avoid loading incomplete candles where exchanges
          do not support sending ohlcv params to prevent returning partial data

    """

    params = (
        ("historical", False),  # only historical download
        ("backfill_start", False),  # do backfill at the start
        ("fetch_ohlcv_params", {}),
        ("ohlcv_limit", 20),
        ("drop_newest", False),
        ("debug", False),
    )

    _store = ccxtstore.CCXTStore

    # States for the Finite State Machine in _load
    _ST_LIVE, _ST_HISTORBACK, _ST_OVER = range(3)

    # def __init__(self, exchange, symbol, ohlcv_limit=None, config={}, retries=5):
    def __init__(self, **kwargs):
        # self.store = CCXTStore(exchange, config, retries)
        self._state = None
        self.store = self._store(**kwargs)
        self._data = queue.Queue()  # data queue for price data
        self._last_id = ""  # last processed trade id for ohlcv
        self._last_ts = self.utc_to_ts(datetime.utcnow())  # last processed timestamp for ohlcv
        self._last_update_bar_time = 0

    def utc_to_ts(self, dt):
        fromdate = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute)
        epoch = datetime(1970, 1, 1)
        return int((fromdate - epoch).total_seconds() * 1000)

    def start(
        self,
    ):
        DataBase.start(self)
        if self.p.fromdate:
            self._state = self._ST_HISTORBACK
            self.put_notification(self.DELAYED)
            self._update_bar(self.p.fromdate)
        else:
            self._state = self._ST_LIVE
            self.put_notification(self.LIVE)

    def _load(self):
        """
        return True means successfully got data from data source
        return False means data source closed for some reason (e.g., historical data source finished outputting all data)
        return None means temporarily cannot get latest data from data source, but will have later (e.g., latest bar in live data source not yet generated)
        """
        if self._state == self._ST_OVER:
            return False
        #
        while True:
            if self._state == self._ST_LIVE:
                # ===========================================
                # This code is best placed in an independent worker thread, purely lazy here
                # Update bar every minute
                # There are some small issues with the original author's code, some strategies with other timeframes don't necessarily update every minute
                timeframe = self._timeframe
                compression = self._compression
                # If minute timeframe
                if timeframe == 4:
                    time_diff = 60 * compression
                # If daily timeframe
                elif timeframe == 5:
                    time_diff = 86400 * compression
                # If other timeframes, default is one minute
                else:
                    time_diff = 60
                # Because local time and exchange time may have a gap, need to consider adding a function to align local time with exchange time
                # My local time and exchange time differ by about 70ms, so I need to add 2s delay here to facilitate receiving the latest bar
                # Everyone needs to modify according to their actual situation
                nts = time.time()
                if nts - self._last_update_bar_time / 1000 >= time_diff + 2:
                    # nts = get_last_timeframe_timestamp(int(nts), time_diff)
                    # # print(f"上个bar结束时间为:{datetime.fromtimestamp(nts)}")
                    # self._last_update_bar_time = nts
                    self._update_bar(livemode=True)
                # ===========================================
                return self._load_bar()
            elif self._state == self._ST_HISTORBACK:
                ret = self._load_bar()
                if ret:
                    return ret
                else:
                    # End of historical data
                    if self.p.historical:  # only historical
                        self.put_notification(self.DISCONNECTED)
                        self._state = self._ST_OVER
                        return False  # end of historical
                    else:
                        self._state = self._ST_LIVE
                        self.put_notification(self.LIVE)
                        continue

    def _update_bar(self, fromdate=None, livemode=False):
        """Fetch OHLCV data into self._data queue"""
        # Which time granularity to get bars for
        granularity = self.store.get_granularity(self._timeframe, self._compression)
        # From which time point to start getting bars
        if fromdate:
            self._last_ts = self.utc_to_ts(fromdate)
        # Maximum limit on number of bars to get each time
        limit = max(
            3, self.p.ohlcv_limit
        )  # Minimum cannot be less than three, reason: each time the first bar time is duplicated and needs to be ignored, the last bar is incomplete and needs to be removed, only keep the middle ones, so minimum three
        #
        while True:
            # First get data length
            dlen = self._data.qsize()
            #
            bars = sorted(
                self.store.fetch_ohlcv(
                    self.p.dataname,
                    timeframe=granularity,
                    since=self._last_ts,
                    limit=limit,
                    params=self.p.fetch_ohlcv_params,
                )
            )
            # print([datetime.fromtimestamp(i[0]/1000) for i in bars])
            # Check to see if dropping the latest candle will help with
            # exchanges which return partial data
            if self.p.drop_newest and len(bars) > 0:
                del bars[-1]
            #
            for bar in bars:
                # Retrieved bar cannot have empty values
                if None in bar:
                    continue
                # Bar timestamp
                tstamp = bar[0]
                # Determine if bar is new bar through timestamp
                if tstamp > self._last_ts:
                    self._data.put(bar)  # Save new bar to queue
                    self._last_ts = tstamp
                    self._last_update_bar_time = tstamp
                    # print(datetime.utcfromtimestamp(tstamp//1000))
            # If data length hasn't grown, it proves to be the current last bar, exit
            if dlen == self._data.qsize():
                break
            # In live mode, no need to check if it's the last bar, reduce network communication
            if livemode:
                break

    def _load_bar(self):
        try:
            bar = self._data.get(block=False)  # non-blocking
        except queue.Empty:
            return None  # no data in the queue
        tstamp, open_, high, low, close, volume = bar
        dtime = datetime.utcfromtimestamp(tstamp // 1000)
        self.lines.datetime[0] = date2num(dtime)
        self.lines.open[0] = open_
        self.lines.high[0] = high
        self.lines.low[0] = low
        self.lines.close[0] = close
        self.lines.volume[0] = volume
        return True

    def haslivedata(self):
        return self._state == self._ST_LIVE and not self._data.empty()

    def islive(self):
        return not self.p.historical
