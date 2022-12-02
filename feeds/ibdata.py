#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
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
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime

import backtrader as bt
from backtrader.feed import DataBase
from backtrader import TimeFrame, date2num, num2date
from backtrader.utils.py3 import (integer_types, queue, string_types,
                                  with_metaclass)
from backtrader.metabase import MetaParams
from backtrader.stores import ibstore


class MetaIBData(DataBase.__class__):
    def __init__(cls, name, bases, dct):
        '''Class has already been created ... register'''
        # Initialize the class
        super(MetaIBData, cls).__init__(name, bases, dct)

        # Register with the store
        ibstore.IBStore.DataCls = cls


class IBData(with_metaclass(MetaIBData, DataBase)):
    '''Interactive Brokers Data Feed.
    # 获取数据的时候，支持的dataname格式
    Supports the following contract specifications in parameter ``dataname``:

          - TICKER  # Stock type and SMART exchange
          - TICKER-STK  # Stock and SMART exchange
          - TICKER-STK-EXCHANGE  # Stock
          - TICKER-STK-EXCHANGE-CURRENCY  # Stock

          - TICKER-CFD  # CFD and SMART exchange
          - TICKER-CFD-EXCHANGE  # CFD
          - TICKER-CDF-EXCHANGE-CURRENCY  # Stock

          - TICKER-IND-EXCHANGE  # Index
          - TICKER-IND-EXCHANGE-CURRENCY  # Index

          - TICKER-YYYYMM-EXCHANGE  # Future
          - TICKER-YYYYMM-EXCHANGE-CURRENCY  # Future
          - TICKER-YYYYMM-EXCHANGE-CURRENCY-MULT  # Future
          - TICKER-FUT-EXCHANGE-CURRENCY-YYYYMM-MULT # Future

          - TICKER-YYYYMM-EXCHANGE-CURRENCY-STRIKE-RIGHT  # FOP
          - TICKER-YYYYMM-EXCHANGE-CURRENCY-STRIKE-RIGHT-MULT  # FOP
          - TICKER-FOP-EXCHANGE-CURRENCY-YYYYMM-STRIKE-RIGHT # FOP
          - TICKER-FOP-EXCHANGE-CURRENCY-YYYYMM-STRIKE-RIGHT-MULT # FOP

          - CUR1.CUR2-CASH-IDEALPRO  # Forex

          - TICKER-YYYYMMDD-EXCHANGE-CURRENCY-STRIKE-RIGHT  # OPT
          - TICKER-YYYYMMDD-EXCHANGE-CURRENCY-STRIKE-RIGHT-MULT  # OPT
          - TICKER-OPT-EXCHANGE-CURRENCY-YYYYMMDD-STRIKE-RIGHT # OPT
          - TICKER-OPT-EXCHANGE-CURRENCY-YYYYMMDD-STRIKE-RIGHT-MULT # OPT

    Params:

      - ``sectype`` (default: ``STK``)

        Default value to apply as *security type* if not provided in the
        ``dataname`` specification

        # 在指定名字的时候，如果没有设定证券类型，那么默认值是股票

      - ``exchange`` (default: ``SMART``)

        Default value to apply as *exchange* if not provided in the
        ``dataname`` specification
        # 如果没有在名字中指定的话，默认的交易所是“SMART”

      - ``currency`` (default: ``''``)

        Default value to apply as *currency* if not provided in the
        ``dataname`` specification
        # 如果没有在名字中指定的话，默认的货币种类是空字符串

      - ``historical`` (default: ``False``)

        If set to ``True`` the data feed will stop after doing the first
        download of data.

        The standard data feed parameters ``fromdate`` and ``todate`` will be
        used as reference.

        The data feed will make multiple requests if the requested duration is
        larger than the one allowed by IB given the timeframe/compression
        chosen for the data.

        # 如果这个参数设置的是True的话，将会在第一次下载数据之后停止更新数据。将会使用fromdate 和 todate
        # 作为指引，如果两个时间间隔大于一次IB允许请求的最大数据量，将会分很多次进行下载

      - ``what`` (default: ``None``)

        If ``None`` the default for different assets types will be used for
        historical data requests:

          - 'BID' for CASH assets
          - 'TRADES' for any other

        Use 'ASK' for the Ask quote of cash assets
        
        Check the IB API docs if another value is wished

        # what这个参数决定具体下载哪些数据，可能会根据不同的资产类型有所变化

      - ``rtbar`` (default: ``False``)

        If ``True`` the ``5 Seconds Realtime bars`` provided by Interactive
        Brokers will be used as the smalles tick. According to the
        documentation they correspond to real-time values (once collated and
        curated by IB)

        If ``False`` then the ``RTVolume`` prices will be used, which are based
        on receiving ticks. In the case of ``CASH`` assets (like for example
        EUR.JPY) ``RTVolume`` will always be used and from it the ``bid`` price
        (industry de-facto standard with IB according to the literature
        scattered over the Internet)

        Even if set to ``True``, if the data is resampled/kept to a
        timeframe/compression below Seconds/5, no real time bars will be used,
        because IB doesn't serve them below that level

        # 这个参数如果设置成True的话，将会获取5秒钟的实时K线，用作最小的tick数据。
        # 如果设置成False的话，会基于接受到的tick数据，将会使用RTVolume价格。如果是cash类资产，将会接收bid价格
        # 如果这个参数设置成True的，但是resample的周期在5秒钟以下，也不会使用实时K线数据

      - ``qcheck`` (default: ``0.5``)

        Time in seconds to wake up if no data is received to give a chance to
        resample/replay packets properly and pass notifications up the chain
        # 当没有数据接收到的时候，多少秒钟唤醒以便有机会合成新的k线

      - ``backfill_start`` (default: ``True``)

        Perform backfilling at the start. The maximum possible historical data
        will be fetched in a single request.
        # 在开始的时候进行数据填充，在一次请求中将会请求尽可能多的数据

      - ``backfill`` (default: ``True``)

        Perform backfilling after a disconnection/reconnection cycle. The gap
        duration will be used to download the smallest possible amount of data
        # 在一次断开连接和重新连接的过程中，将会执行填充。将会根据这个断开的时间间隔下载最小的数据量

      - ``backfill_from`` (default: ``None``)

        An additional data source can be passed to do an initial layer of
        backfilling. Once the data source is depleted and if requested,
        backfilling from IB will take place. This is ideally meant to backfill
        from already stored sources like a file on disk, but not limited to.
        # 从额外的数据源进行填充数据，如果这个数据源已经用完了，将会从IB获取数据进行填充。理想情况下
        # 这个额外的数据源最好已经存储在一个文件或者硬盘上了，但是也可以是其他方式

      - ``latethrough`` (default: ``False``)

        If the data source is resampled/replayed, some ticks may come in too
        late for the already delivered resampled/replayed bar. If this is
        ``True`` those ticks will bet let through in any case.

        Check the Resampler documentation to see who to take those ticks into
        account.

        This can happen especially if ``timeoffset`` is set to ``False``  in
        the ``IBStore`` instance and the TWS server time is not in sync with
        that of the local computer

        # 当合成K线之后，如果有新来的tick是否允许通过。
        # 当timeoffset设置成False的时候，本地时间可能和服务器时间有很大的差距，导致tick来晚的情况
        # 更愿意有可能发生。

      - ``tradename`` (default: ``None``)
        Useful for some specific cases like ``CFD`` in which prices are offered
        by one asset and trading happens in a different onel

        - SPY-STK-SMART-USD -> SP500 ETF (will be specified as ``dataname``)

        - SPY-CFD-SMART-USD -> which is the corresponding CFD which offers not
          price tracking but in this case will be the trading asset (specified
          as ``tradename``)

        # tradename是具体交易的资产的名字，
        # dataname与tradename如果不一样的话，
        # 那就是dataname获取数据，在tradename上进行交易

    The default values in the params are the to allow things like ```TICKER``,
    to which the parameter ``sectype`` (default: ``STK``) and ``exchange``
    (default: ``SMART``) are applied.

    Some assets like ``AAPL`` need full specification including ``currency``
    (default: '') whereas others like ``TWTR`` can be simply passed as it is.

      - ``AAPL-STK-SMART-USD`` would be the full specification for dataname

        Or else: ``IBData`` as ``IBData(dataname='AAPL', currency='USD')``
        which uses the default values (``STK`` and ``SMART``) and overrides
        the currency to be ``USD``

    '''
    params = (
        ('sectype', 'STK'),  # usual industry value
        ('exchange', 'SMART'),  # usual industry value
        ('currency', ''),
        ('rtbar', False),  # use RealTime 5 seconds bars
        ('historical', False),  # only historical download
        ('what', None),  # historical - what to show
        ('useRTH', False),  # historical - download only Regular Trading Hours
        ('qcheck', 0.5),  # timeout in seconds (float) to check for events
        ('backfill_start', True),  # do backfilling at the start
        ('backfill', True),  # do backfilling when reconnecting
        ('backfill_from', None),  # additional data source to do backfill from
        ('latethrough', False),  # let late samples through
        ('tradename', None),  # use a different asset as order target
    )

    _store = ibstore.IBStore

    # Minimum size supported by real-time bars
    RTBAR_MINSIZE = (TimeFrame.Seconds, 5)

    # States for the Finite State Machine in _load
    _ST_FROM, _ST_START, _ST_LIVE, _ST_HISTORBACK, _ST_OVER = range(5)

    # 时间差或者时间补偿
    def _timeoffset(self):
        return self.ib.timeoffset()

    # 获取时区
    def _gettz(self):
        # If no object has been provided by the user and a timezone can be
        # found via contractdtails, then try to get it from pytz, which may or
        # may not be available.

        # The timezone specifications returned by TWS seem to be abbreviations
        # understood by pytz, but the full list which TWS may return is not
        # documented and one of the abbreviations may fail
        # 如果用户没有自己指定时区，那么就需要使用pytz通过合约详细信息来获取时区
        tzstr = isinstance(self.p.tz, string_types)
        if self.p.tz is not None and not tzstr:
            return bt.utils.date.Localizer(self.p.tz)

        if self.contractdetails is None:
            return None  # nothing can be done

        try:
            import pytz  # keep the import very local
        except ImportError:
            return None  # nothing can be done

        tzs = self.p.tz if tzstr else self.contractdetails.m_timeZoneId

        if tzs == 'CST':  # reported by TWS, not compatible with pytz. patch it
            tzs = 'CST6CDT'

        try:
            tz = pytz.timezone(tzs)
        except pytz.UnknownTimeZoneError:
            return None  # nothing can be done

        # contractdetails there, import ok, timezone found, return it
        return tz

    # 是否是实时数据
    def islive(self):
        '''Returns ``True`` to notify ``Cerebro`` that preloading and runonce
        should be deactivated'''
        return not self.p.historical

    # 初始化
    def __init__(self, **kwargs):
        self.ib = self._store(**kwargs)
        self.precontract = self.parsecontract(self.p.dataname)
        self.pretradecontract = self.parsecontract(self.p.tradename)

    # 设置环境，接收到cerebro，并且把它传递到它所属的store
    def setenvironment(self, env):
        '''Receives an environment (cerebro) and passes it over to the store it
        belongs to'''
        super(IBData, self).setenvironment(env)
        env.addstore(self.ib)

    # 根据具体的数据名称生成合同
    def parsecontract(self, dataname):
        '''Parses dataname generates a default contract'''
        # Set defaults for optional tokens in the ticker string
        if dataname is None:
            return None

        exch = self.p.exchange
        curr = self.p.currency
        expiry = ''
        strike = 0.0
        right = ''
        mult = ''

        # split the ticker string
        tokens = iter(dataname.split('-'))

        # Symbol and security type are compulsory
        symbol = next(tokens)
        try:
            sectype = next(tokens)
        except StopIteration:
            sectype = self.p.sectype

        # security type can be an expiration date
        if sectype.isdigit():
            expiry = sectype  # save the expiration ate

            if len(sectype) == 6:  # YYYYMM
                sectype = 'FUT'
            else:  # Assume OPTIONS - YYYYMMDD
                sectype = 'OPT'

        if sectype == 'CASH':  # need to address currency for Forex
            symbol, curr = symbol.split('.')

        # See if the optional tokens were provided
        try:
            exch = next(tokens)  # on exception it will be the default
            curr = next(tokens)  # on exception it will be the default

            if sectype == 'FUT':
                if not expiry:
                    expiry = next(tokens)
                mult = next(tokens)

                # Try to see if this is FOP - Futures on OPTIONS
                right = next(tokens)
                # if still here this is a FOP and not a FUT
                sectype = 'FOP'
                strike, mult = float(mult), ''  # assign to strike and void

                mult = next(tokens)  # try again to see if there is any

            elif sectype == 'OPT':
                if not expiry:
                    expiry = next(tokens)
                strike = float(next(tokens))  # on exception - default
                right = next(tokens)  # on exception it will be the default

                mult = next(tokens)  # ?? no harm in any case

        except StopIteration:
            pass

        # Make the initial contract
        precon = self.ib.makecontract(
            symbol=symbol, sectype=sectype, exch=exch, curr=curr,
            expiry=expiry, strike=strike, right=right, mult=mult)

        return precon

    # 开始连接到IB ，获取真实的合约并且返回详细的合约信息
    def start(self):
        '''Starts the IB connecction and gets the real contract and
        contractdetails if it exists'''
        super(IBData, self).start()
        # Kickstart store and get queue to wait on
        self.qlive = self.ib.start(data=self)
        self.qhist = None

        self._usertvol = not self.p.rtbar
        tfcomp = (self._timeframe, self._compression)
        if tfcomp < self.RTBAR_MINSIZE:
            # Requested timeframe/compression not supported by rtbars
            self._usertvol = True

        self.contract = None
        self.contractdetails = None
        self.tradecontract = None
        self.tradecontractdetails = None

        if self.p.backfill_from is not None:
            self._state = self._ST_FROM
            self.p.backfill_from.setenvironment(self._env)
            self.p.backfill_from._start()
        else:
            self._state = self._ST_START  # initial state for _load
        self._statelivereconn = False  # if reconnecting in live state
        self._subcription_valid = False  # subscription state
        self._storedmsg = dict()  # keep pending live message (under None)

        if not self.ib.connected():
            return

        self.put_notification(self.CONNECTED)
        # get real contract details with real conId (contractId)
        cds = self.ib.getContractDetails(self.precontract, maxcount=1)
        if cds is not None:
            cdetails = cds[0]
            self.contract = cdetails.contractDetails.m_summary
            self.contractdetails = cdetails.contractDetails
        else:
            # no contract can be found (or many)
            self.put_notification(self.DISCONNECTED)
            return

        if self.pretradecontract is None:
            # no different trading asset - default to standard asset
            self.tradecontract = self.contract
            self.tradecontractdetails = self.contractdetails
        else:
            # different target asset (typical of some CDS products)
            # use other set of details
            cds = self.ib.getContractDetails(self.pretradecontract, maxcount=1)
            if cds is not None:
                cdetails = cds[0]
                self.tradecontract = cdetails.contractDetails.m_summary
                self.tradecontractdetails = cdetails.contractDetails
            else:
                # no contract can be found (or many)
                self.put_notification(self.DISCONNECTED)
                return

        if self._state == self._ST_START:
            self._start_finish()  # to finish initialization
            self._st_start()

    # 准备结束
    def stop(self):
        '''Stops and tells the store to stop'''
        super(IBData, self).stop()
        self.ib.stop()

    # 请求数据
    def reqdata(self):
        '''request real-time data. checks cash vs non-cash) and param useRT'''
        if self.contract is None or self._subcription_valid:
            return

        if self._usertvol:
            self.qlive = self.ib.reqMktData(self.contract, self.p.what)
        else:
            self.qlive = self.ib.reqRealTimeBars(self.contract)

        self._subcription_valid = True
        return self.qlive

    # 取消数据
    def canceldata(self):
        '''Cancels Market Data subscription, checking asset type and rtbar'''
        if self.contract is None:
            return

        if self._usertvol:
            self.ib.cancelMktData(self.qlive)
        else:
            self.ib.cancelRealTimeBars(self.qlive)

    # 是否具有实时数据
    def haslivedata(self):
        return bool(self._storedmsg or self.qlive)

    # 加载数据
    def _load(self):
        if self.contract is None or self._state == self._ST_OVER:
            return False  # nothing can be done

        while True:
            if self._state == self._ST_LIVE:
                try:
                    msg = (self._storedmsg.pop(None, None) or
                           self.qlive.get(timeout=self._qcheck))
                except queue.Empty:
                    if True:
                        return None

                # Code invalidated until further checking is done
                    if not self._statelivereconn:
                        return None  # indicate timeout situation

                    # Awaiting data and nothing came in - fake it up until now
                    dtend = self.num2date(date2num(datetime.datetime.utcnow()))
                    dtbegin = None
                    if len(self) > 1:
                        dtbegin = self.num2date(self.datetime[-1])

                    self.qhist = self.ib.reqHistoricalDataEx(
                        contract=self.contract,
                        enddate=dtend, begindate=dtbegin,
                        timeframe=self._timeframe,
                        compression=self._compression,
                        what=self.p.what, useRTH=self.p.useRTH, tz=self._tz,
                        sessionend=self.p.sessionend)

                    if self._laststatus != self.DELAYED:
                        self.put_notification(self.DELAYED)

                    self._state = self._ST_HISTORBACK

                    self._statelivereconn = False
                    continue  # to reenter the loop and hit st_historback

                if msg is None:  # Conn broken during historical/backfilling
                    self._subcription_valid = False
                    self.put_notification(self.CONNBROKEN)
                    # Try to reconnect
                    if not self.ib.reconnect(resub=True):
                        self.put_notification(self.DISCONNECTED)
                        return False  # failed

                    self._statelivereconn = self.p.backfill
                    continue

                if msg == -354:
                    self.put_notification(self.NOTSUBSCRIBED)
                    return False

                elif msg == -1100:  # conn broken
                    # Tell to wait for a message to do a backfill
                    # self._state = self._ST_DISCONN
                    self._subcription_valid = False
                    self._statelivereconn = self.p.backfill
                    continue

                elif msg == -1102:  # conn broken/restored tickerId maintained
                    # The message may be duplicated
                    if not self._statelivereconn:
                        self._statelivereconn = self.p.backfill
                    continue

                elif msg == -1101:  # conn broken/restored tickerId gone
                    # The message may be duplicated
                    self._subcription_valid = False
                    if not self._statelivereconn:
                        self._statelivereconn = self.p.backfill
                        self.reqdata()  # resubscribe
                    continue

                elif msg == -10225:  # Bust event occurred, current subscription is deactivated.
                    self._subcription_valid = False
                    if not self._statelivereconn:
                        self._statelivereconn = self.p.backfill
                        self.reqdata()  # resubscribe
                    continue

                elif isinstance(msg, integer_types):
                    # Unexpected notification for historical data skip it
                    # May be a "not connected not yet processed"
                    self.put_notification(self.UNKNOWN, msg)
                    continue

                # Process the message according to expected return type
                if not self._statelivereconn:
                    if self._laststatus != self.LIVE:
                        if self.qlive.qsize() <= 1:  # very short live queue
                            self.put_notification(self.LIVE)

                    if self._usertvol:
                        ret = self._load_rtvolume(msg)
                    else:
                        ret = self._load_rtbar(msg)
                    if ret:
                        return True

                    # could not load bar ... go and get new one
                    continue

                # Fall through to processing reconnect - try to backfill
                self._storedmsg[None] = msg  # keep the msg

                # else do a backfill
                if self._laststatus != self.DELAYED:
                    self.put_notification(self.DELAYED)

                dtend = None
                if len(self) > 1:
                    # len == 1 ... forwarded for the 1st time
                    # get begin date in utc-like format like msg.datetime
                    dtbegin = num2date(self.datetime[-1])
                elif self.fromdate > float('-inf'):
                    dtbegin = num2date(self.fromdate)
                else:  # 1st bar and no begin set
                    # passing None to fetch max possible in 1 request
                    dtbegin = None

                dtend = msg.datetime if self._usertvol else msg.time

                self.qhist = self.ib.reqHistoricalDataEx(
                    contract=self.contract, enddate=dtend, begindate=dtbegin,
                    timeframe=self._timeframe, compression=self._compression,
                    what=self.p.what, useRTH=self.p.useRTH, tz=self._tz,
                    sessionend=self.p.sessionend)

                self._state = self._ST_HISTORBACK
                self._statelivereconn = False  # no longer in live
                continue

            elif self._state == self._ST_HISTORBACK:
                msg = self.qhist.get()
                if msg is None:  # Conn broken during historical/backfilling
                    # Situation not managed. Simply bail out
                    self._subcription_valid = False
                    self.put_notification(self.DISCONNECTED)
                    return False  # error management cancelled the queue

                elif msg == -354:  # Data not subscribed
                    self._subcription_valid = False
                    self.put_notification(self.NOTSUBSCRIBED)
                    return False

                elif msg == -420:  # No permissions for the data
                    self._subcription_valid = False
                    self.put_notification(self.NOTSUBSCRIBED)
                    return False

                elif isinstance(msg, integer_types):
                    # Unexpected notification for historical data skip it
                    # May be a "not connected not yet processed"
                    self.put_notification(self.UNKNOWN, msg)
                    continue

                if msg.date is not None:
                    if self._load_rtbar(msg, hist=True):
                        return True  # loading worked

                    # the date is from overlapping historical request
                    continue

                # End of histdata
                if self.p.historical:  # only historical
                    self.put_notification(self.DISCONNECTED)
                    return False  # end of historical

                # Live is also wished - go for it
                self._state = self._ST_LIVE
                continue

            elif self._state == self._ST_FROM:
                if not self.p.backfill_from.next():
                    # additional data source is consumed
                    self._state = self._ST_START
                    continue

                # copy lines of the same name
                for alias in self.lines.getlinealiases():
                    lsrc = getattr(self.p.backfill_from.lines, alias)
                    ldst = getattr(self.lines, alias)

                    ldst[0] = lsrc[0]

                return True

            elif self._state == self._ST_START:
                if not self._st_start():
                    return False
    #
    def _st_start(self):
        if self.p.historical:
            self.put_notification(self.DELAYED)
            dtend = None
            if self.todate < float('inf'):
                dtend = num2date(self.todate)

            dtbegin = None
            if self.fromdate > float('-inf'):
                dtbegin = num2date(self.fromdate)

            self.qhist = self.ib.reqHistoricalDataEx(
                contract=self.contract, enddate=dtend, begindate=dtbegin,
                timeframe=self._timeframe, compression=self._compression,
                what=self.p.what, useRTH=self.p.useRTH, tz=self._tz,
                sessionend=self.p.sessionend)

            self._state = self._ST_HISTORBACK
            return True  # continue before

        # Live is requested
        if not self.ib.reconnect(resub=True):
            self.put_notification(self.DISCONNECTED)
            self._state = self._ST_OVER
            return False  # failed - was so

        self._statelivereconn = self.p.backfill_start
        if self.p.backfill_start:
            self.put_notification(self.DELAYED)

        self._state = self._ST_LIVE
        return True  # no return before - implicit continue

    # 把K线数据保存到line里面
    def _load_rtbar(self, rtbar, hist=False):
        # A complete 5 second bar made of real-time ticks is delivered and
        # contains open/high/low/close/volume prices
        # The historical data has the same data but with 'date' instead of
        # 'time' for datetime
        dt = date2num(rtbar.time if not hist else rtbar.date)
        if dt < self.lines.datetime[-1] and not self.p.latethrough:
            return False  # cannot deliver earlier than already delivered

        self.lines.datetime[0] = dt
        # Put the tick into the bar
        self.lines.open[0] = rtbar.open
        self.lines.high[0] = rtbar.high
        self.lines.low[0] = rtbar.low
        self.lines.close[0] = rtbar.close
        self.lines.volume[0] = rtbar.volume
        self.lines.openinterest[0] = 0

        return True

    # 把tick数据保存到line里面
    def _load_rtvolume(self, rtvol):
        # A single tick is delivered and is therefore used for the entire set
        # of prices. Ideally the
        # contains open/high/low/close/volume prices
        # Datetime transformation
        dt = date2num(rtvol.datetime)
        if dt < self.lines.datetime[-1] and not self.p.latethrough:
            return False  # cannot deliver earlier than already delivered

        self.lines.datetime[0] = dt

        # Put the tick into the bar
        tick = rtvol.price
        self.lines.open[0] = tick
        self.lines.high[0] = tick
        self.lines.low[0] = tick
        self.lines.close[0] = tick
        self.lines.volume[0] = rtvol.size
        self.lines.openinterest[0] = 0

        return True
