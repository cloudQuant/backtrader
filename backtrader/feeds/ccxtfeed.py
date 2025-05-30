#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015, 2016, 2017 Daniel Rodriguez
# Copyright (C) 2017 Ed Bartosh
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
import time
from collections import deque
from datetime import datetime

import backtrader as bt
from backtrader.feed import DataBase
from backtrader.utils.py3 import queue
from backtrader.stores.ccxtstore import CCXTStore
from backtrader.utils.date import get_last_timeframe_timestamp


class MetaCCXTFeed(DataBase.__class__):
    def __init__(cls, name, bases, dct):
        """Class has already been created ... register"""
        # Initialize the class
        super(MetaCCXTFeed, cls).__init__(name, bases, dct)

        # Register with the store
        CCXTStore.DataCls = cls


class CCXTFeed(DataBase, metaclass=MetaCCXTFeed):
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

    _store = CCXTStore

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
        return True  代表从数据源获取数据成功
        return False 代表因为某种原因(比如历史数据源全部数据已经输出完毕)数据源关闭
        return None  代表暂时无法从数据源获取最新数据,但是以后会有(比如实时数据源中最新的bar还未生成)
        """
        if self._state == self._ST_OVER:
            return False
        #
        while True:
            if self._state == self._ST_LIVE:
                # ===========================================
                # 其实这段代码最好放到独立的工作线程中做,这里纯粹偷懒
                # 每隔一分钟就更新一次bar
                # 这段代码原作者写的有一些小问题，有一些其他周期的策略并不一定是每分钟更新一次
                timeframe = self._timeframe
                compression = self._compression
                # 如果是分钟级别
                if timeframe == 4:
                    time_diff = 60 * compression
                # 如果是日线级别
                elif timeframe == 5:
                    time_diff = 86400 * compression
                # 如果是其他周期，默认是一分钟
                else:
                    time_diff = 60
                # 因为本地时间和交易所时间可能有差距，所以需要考虑增加一个功能，把本地时间和交易所时间进行对齐
                # 我本地时间和交易所时间差70ms左右，所以，这里面我需要增加2s的延时，以方便接收到最新的bar
                # 大家需要根据自己的实际情况进行修改
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
        # 想要获取哪个时间粒度下的bar
        granularity = self.store.get_granularity(self._timeframe, self._compression)
        # 从哪个时间点开始获取bar
        if fromdate:
            self._last_ts = self.utc_to_ts(fromdate)
        # 每次获取bar数目的最高限制
        limit = max(
            3, self.p.ohlcv_limit
        )  # 最少不能少于三个,原因:每次头bar时间重复要忽略,尾bar未完整要去掉,只保留中间的,所以最少三个
        #
        while True:
            # 先获取数据长度
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
                # 获取的bar不能有空值
                if None in bar:
                    continue
                # bar的时间戳
                tstamp = bar[0]
                # 通过时间戳判断bar是否为新的bar
                if tstamp > self._last_ts:
                    self._data.put(bar)  # 将新的bar保存到队列中
                    self._last_ts = tstamp
                    self._last_update_bar_time = tstamp
                    # print(datetime.utcfromtimestamp(tstamp//1000))
            # 如果数据长度没有增长,那证明已经是当前最后一根bar,退出
            if dlen == self._data.qsize():
                break
            # 实时模式下,就没必须判断是否是最后一根bar,减少网络通信
            if livemode:
                break

    def _load_bar(self):
        try:
            bar = self._data.get(block=False)  # 不阻塞
        except queue.Empty:
            return None  # no data in the queue
        tstamp, open_, high, low, close, volume = bar
        dtime = datetime.utcfromtimestamp(tstamp // 1000)
        self.lines.datetime[0] = bt.date2num(dtime)
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
