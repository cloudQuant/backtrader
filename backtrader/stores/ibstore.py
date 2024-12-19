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

import collections
from copy import copy
from datetime import date, datetime, timedelta
import inspect
import itertools
import random
import threading
import time

from ib.ext.Contract import Contract
import ib.opt as ibopt

from backtrader import TimeFrame, Position
from backtrader.metabase import MetaParams
from backtrader.utils.py3 import bytes, bstr, queue, with_metaclass, long
from backtrader.utils import AutoDict, UTC

bytes = bstr  # py2/3 need for ibpy


def _ts2dt(tstamp=None):
    # Transforms a RTVolume timestamp to a datetime object
    # 把timestamp转换成时间对象，如果没有指定时间戳的话，就返回当前的utc时间
    # 如果时间戳不是None，空值，False的时候，对时间戳进行处理，然后返回时间对象
    if not tstamp:
        return datetime.utcnow()
    # todo backtrader自带代码，1000出错了，改写成1，这样计算得到的utc时间比北京时间晚8个小时
    # 如果使用1000的话，得到的时间是1970年的
    # sec, msec = divmod(long(tstamp), 1000)
    sec, msec = divmod(long(tstamp), 1)
    usec = msec * 1000
    return datetime.utcfromtimestamp(sec).replace(microsecond=usec)


class RTVolume(object):
    '''Parses a tickString tickType 48 (RTVolume) event from the IB API into its
    constituent fields
    Supports using a "price" to simulate an RTVolume from a tickPrice event
    '''
    _fields = [
        ('price', float),
        ('size', int),
        ('datetime', _ts2dt),
        ('volume', int),
        ('vwap', float),
        ('single', bool)
    ]

    def __init__(self, rtvol='', price=None, tmoffset=None):
        # Use a provided string or simulate a list of empty tokens
        # 把接收到的tick数据进行分割
        tokens = iter(rtvol.split(';'))

        # Put the tokens as attributes using the corresponding func
        # 把分割后的tick数据进行数据转换，并赋值，这两段代码写的还算是比较精炼的
        for name, func in self._fields:
            setattr(self, name, func(next(tokens)) if rtvol else func())

        # If price was provided use it
        # 如果单独提供了price,就使用price,会覆盖从tick中接收的price
        if price is not None:
            self.price = price
        # 如果时间偏移量不是None的话，在现有的时间上加上时间偏移量
        if tmoffset is not None:
            self.datetime += tmoffset


class MetaSingleton(MetaParams):
    '''Metaclass to make a metaclassed class a singleton'''
    # todo 这个元类的用处理解还不是特别深，等到后续详细讲backtrader的元类的时候重新拉出来分析
    def __init__(cls, name, bases, dct):
        super(MetaSingleton, cls).__init__(name, bases, dct)
        cls._singleton = None

    def __call__(cls, *args, **kwargs):
        if cls._singleton is None:
            cls._singleton = (
                super(MetaSingleton, cls).__call__(*args, **kwargs))

        return cls._singleton


# Decorator to mark methods to register with ib.opt
def ibregister(f):
    f._ibregister = True
    return f


class IBStore(with_metaclass(MetaSingleton, object)):
    '''Singleton class wrapping an ibpy ibConnection instance.

    The parameters can also be specified in the classes which use this store,
    like ``IBData`` and ``IBBroker``
    # 参数也可以在使用这个store的类里面，比如``IBData`` 和 ``IBBroker`` 中进行指定
    Params:

      - ``host`` (default:``127.0.0.1``): where IB TWS or IB Gateway are
        actually running. And although this will usually be the localhost, it
        must not be
        # host地址，通常情况下，在IB TWS 或者 IB Gateway 默认的host是本地地址，也就是127.0.0.1
        # 但是这个地址并不必然是这个默认的值

      - ``port`` (default: ``7496``): port to connect to. The demo system uses
        ``7497``
        # 端口号，通常情况下，实盘账户是7496，模拟账户是7497
      - ``clientId`` (default: ``None``): which clientId to use to connect to
        TWS.
        ``None``: generates a random id between 1 and 65535
        An ``integer``: will be passed as the value to use.
        # 设置一个clientid连接到TWS上，多账户管理的时候是需要的，知道是哪个id发出的信号之类的
        # 可以通过masterid获取各个id的情况，如果设置成None的话，将会生成一个在1到65535之间的随机数

      - ``notifyall`` (default: ``False``)

        If ``False`` only ``error`` messages will be sent to the
        ``notify_store`` methods of ``Cerebro`` and ``Strategy``.
        If ``True``, each and every message received from TWS will be notified
        # 当这个参数设置成False的时候，只有错误信息类型参会被传递到notify_store
        # 如果这个参数设置成True,所有的信息都会被传递到notify_store

      - ``_debug`` (default: ``False``)
        Print all messages received from TWS to standard output
        # 把从TWS接收到的所有信息都打印到标准输出。默认是不这样，当设置成True的时候，会打印所有信息
      - ``reconnect`` (default: ``3``)
        Number of attempts to try to reconnect after the 1st connection attempt
        fails
        Set it to a ``-1`` value to keep on reconnecting forever
        # 当第一次尝试连接失败之后，重新尝试连接的次数；默认是3次，如果设置-1的话，当连接失败之后，会一直尝试重连

      - ``timeout`` (default: ``3.0``)

        Time in seconds between reconnection attemps
        # 在每次重新连接之间，间隔的秒数，默认是3秒

      - ``timeoffset`` (default: ``True``)

        If True, the time obtained from ``reqCurrentTime`` (IB Server time)
        will be used to calculate the offset to localtime and this offset will
        be used for the price notifications (tickPrice events, for example for
        CASH markets) to modify the locally calculated timestamp.

        The time offset will propagate to other parts of the ``backtrader``
        ecosystem like the **resampling** to align resampling timestamps using
        the calculated offset.

        # 如果设置成True的话，使用reqCurrentTime方法从ib服务器请求到的时间将会和本地时间进行对比计算时间差，
        # 在进行价格通知的时候用这个时间差修正本地时间戳，并且这个时间差将会传递到backtrader的生态系统，比如
        # resample函数

      - ``timerefresh`` (default: ``60.0``)

        Time in seconds: how often the time offset has to be refreshed

        # 多久计算一次ib服务器和本地时间的差。默认是60秒计算一次

      - ``indcash`` (default: ``True``)

        Manage IND codes as if they were cash for price retrieval
        # 如果是为了价格检索的现金的时候，用于管理 IND codes
        # todo 暂时未能完全理解这个参数的含义
    '''

    # Set a base for the data requests (historical/realtime) to distinguish the
    # id in the error notifications from orders, where the basis (usually
    # starting at 1) is set by TWS

    REQIDBASE = 0x01000000

    BrokerCls = None  # broker class will autoregister
    DataCls = None  # data class will auto register

    # todo 把在代码init后面添加的类属性，放到init前面了

    # The _durations are meant to calculate the needed historical data to
    # perform backfilling at the start of a connetion or a connection is lost.
    # Using a timedelta as a key allows to quickly find out which bar size
    # bar size (values in the tuples int the dict) can be used.
    # 这个属性主要用于填充历史数据的时候快速计算需要补充多少个bar使用

    _durations = dict([
        # 60 seconds - 1 min
        ('60 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min')),

        # 120 seconds - 2 mins
        ('120 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins')),

        # 180 seconds - 3 mins
        ('180 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins')),

        # 300 seconds - 5 mins
        ('300 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins')),

        # 600 seconds - 10 mins
        ('600 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins')),

        # 900 seconds - 15 mins
        ('900 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins')),

        # 1200 seconds - 20 mins
        ('1200 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins')),

        # 1800 seconds - 30 mins
        ('1800 S',
         ('1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins')),

        # 3600 seconds - 1 hour
        ('3600 S',
         ('5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour')),

        # 7200 seconds - 2 hours
        ('7200 S',
         ('5 secs', '10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours')),

        # 10800 seconds - 3 hours
        ('10800 S',
         ('10 secs', '15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours')),

        # 14400 seconds - 4 hours
        ('14400 S',
         ('15 secs', '30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours')),

        # 28800 seconds - 8 hours
        ('28800 S',
         ('30 secs',
          '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours', '8 hours')),

        # 1 days
        ('1 D',
         ('1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours', '8 hours',
          '1 day')),

        # 2 days
        ('2 D',
         ('2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours', '8 hours',
          '1 day')),

        # 1 weeks
        ('1 W',
         ('3 mins', '5 mins', '10 mins', '15 mins',
          '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours', '8 hours',
          '1 day', '1 W')),

        # 2 weeks
        ('2 W',
         ('15 mins', '20 mins', '30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours', '8 hours',
          '1 day', '1 W')),

        # 1 months
        ('1 M',
         ('30 mins',
          '1 hour', '2 hours', '3 hours', '4 hours', '8 hours',
          '1 day', '1 W', '1 M')),

        # 2+ months
        ('2 M', ('1 day', '1 W', '1 M')),
        ('3 M', ('1 day', '1 W', '1 M')),
        ('4 M', ('1 day', '1 W', '1 M')),
        ('5 M', ('1 day', '1 W', '1 M')),
        ('6 M', ('1 day', '1 W', '1 M')),
        ('7 M', ('1 day', '1 W', '1 M')),
        ('8 M', ('1 day', '1 W', '1 M')),
        ('9 M', ('1 day', '1 W', '1 M')),
        ('10 M', ('1 day', '1 W', '1 M')),
        ('11 M', ('1 day', '1 W', '1 M')),

        # 1+ years
        ('1 Y', ('1 day', '1 W', '1 M')),
    ])

    # Sizes allow for quick translation from bar sizes above to actual
    # timeframes to make a comparison with the actual data
    _sizes = {
        'secs': (TimeFrame.Seconds, 1),
        'min': (TimeFrame.Minutes, 1),
        'mins': (TimeFrame.Minutes, 1),
        'hour': (TimeFrame.Minutes, 60),
        'hours': (TimeFrame.Minutes, 60),
        'day': (TimeFrame.Days, 1),
        'W': (TimeFrame.Weeks, 1),
        'M': (TimeFrame.Months, 1),
    }

    _dur2tf = {
        'S': TimeFrame.Seconds,
        'D': TimeFrame.Days,
        'W': TimeFrame.Weeks,
        'M': TimeFrame.Months,
        'Y': TimeFrame.Years,
    }



    params = (
        ('host', '127.0.0.1'),
        ('port', 7496),
        ('clientId', None),  # None generates a random clientid 1 -> 2^16
        ('notifyall', False),
        ('_debug', False),
        ('reconnect', 3),  # -1 forever, 0 No, > 0 number of retries
        ('timeout', 3.0),  # timeout between reconnections
        ('timeoffset', True),  # Use offset to server for timestamps if needed
        ('timerefresh', 60.0),  # How often to refresh the timeoffset
        ('indcash', True),  # Treat IND codes as CASH elements
    )

    @classmethod
    def getdata(cls, *args, **kwargs):
        '''Returns ``DataCls`` with args, kwargs'''
        # 类方法，获取数据
        return cls.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        '''Returns broker with *args, **kwargs from registered ``BrokerCls``'''
        # 类方法，获取broker
        return cls.BrokerCls(*args, **kwargs)

    def __init__(self):
        # 初始化IBStore
        super(IBStore, self).__init__()
        # 创建4个线程，并加锁
        self._lock_q = threading.Lock()  # sync access to _tickerId/Queues
        self._lock_accupd = threading.Lock()  # sync account updates
        self._lock_pos = threading.Lock()  # sync position updates
        self._lock_notif = threading.Lock()  # sync access to notif queue

        # Account list received
        # 给账户创建两个事件管理标志
        self._event_managed_accounts = threading.Event()
        self._event_accdownload = threading.Event()
        # 不在重新连接，默认是False
        self.dontreconnect = False  # for non-recoverable connect errors
        # cerebro的指针，用于产生通知
        self._env = None  # reference to cerebro for general notifications
        # broker实例，默认是None
        self.broker = None  # broker instance
        # 数据，默认是一个空列表
        self.datas = list()  # datas that have registered over start
        # 从数据或者cerebro中，请求开始
        self.ccount = 0  # requests to start (from cerebro or datas)
        # 创建一个线程并加锁，用于时间差或者时间补偿
        self._lock_tmoffset = threading.Lock()
        # 时间差或者时间补偿，默认是一个时间差值
        self.tmoffset = timedelta()  # to control time difference with server

        # Structures to hold datas requests
        # 保存数据请求的数据结构
        self.qs = collections.OrderedDict()  # key: tickerId -> queues
        self.ts = collections.OrderedDict()  # key: queue -> tickerId
        self.iscash = dict()  # tickerIds from cash products (for ex: EUR.JPY)
        self.histexreq = dict()  # holds segmented historical requests
        self.histfmt = dict()  # holds datetimeformat for request
        self.histsend = dict()  # holds sessionend (data time) for request
        self.histtz = dict()  # holds sessionend (data time) for request

        # 保存账户信息的数据结构
        self.acc_cash = AutoDict()  # current total cash per account
        self.acc_value = AutoDict()  # current total value per account
        self.acc_upds = AutoDict()  # current account valueinfos per account

        self.port_update = False  # indicate whether to signal to broker

        self.positions = collections.defaultdict(Position)  # actual positions
        # todo 没有明白，count后面为啥可以用self.REQIDBASE作为参数，直接拿出来用会报错
        self._tickerId = itertools.count(self.REQIDBASE)  # unique tickerIds
        self.orderid = None  # next possible orderid (will be itertools.count)
        # 保存cdetails的请求信息
        self.cdetails = collections.defaultdict(list)  # hold cdetails requests
        # 管理账户
        self.managed_accounts = list()  # received via managedAccounts
        # 通知的信息，用一个队列保存
        self.notifs = queue.Queue()  # store notifications for cerebro

        # Use the provided clientId or a random one
        # 生成clientId
        if self.p.clientId is None:
            self.clientId = random.randint(1, pow(2, 16) - 1)
        else:
            self.clientId = self.p.clientId

        # ibpy connection object
        # 使用ibpy连接到IB
        self.conn = ibopt.ibConnection(
            host=self.p.host, port=self.p.port, clientId=self.clientId)

        # register a printall method if requested
        # 如果是debug模式或者通知全部信息的模式，就把self.watcher注册到连接上
        if self.p._debug or self.p.notifyall:
            self.conn.registerAll(self.watcher)

        # Register decorated methods with the conn
        # 获取连接上的所有方法
        methods = inspect.getmembers(self, inspect.ismethod)
        for name, method in methods:
            # 如果这个方法是不可注册的，忽略
            if not getattr(method, '_ibregister', False):
                continue
            # 如果这个方法是可以注册的
            message = getattr(ibopt.message, name)
            # 那么就注册这个方法
            self.conn.register(method, message)


        # 这两个函数主要用于填充数据的时候快速计算需要多少个bar

        # This utility key function transforms a barsize into a:
        #   (Timeframe, Compression) tuple which can be sorted
        # 把bar size进行切割，比如 "3 mins",返回的结果为 （TimeFrame.Minutes, 3）
        def keyfn(x):
            n, t = x.split()
            tf, comp = self._sizes[t]
            return (tf, int(n) * comp)

        # This utility key function transforms a duration into a:
        #   (Timeframe, Compression) tuple which can be sorted
        # 把时间间隔进行切割转换，比如 1 D，返回结果为 （TimeFrame.Days，1）
        def key2fn(x):
            n, d = x.split()
            tf = self._dur2tf[d]
            return (tf, int(n))

        # Generate a table of reverse durations
        self.revdur = collections.defaultdict(list)
        # The table (dict) is a ONE to MANY relation of
        #   duration -> barsizes
        # Here it is reversed to get a ONE to MANY relation of
        #   barsize -> durations
        for duration, barsizes in self._durations.items():
            for barsize in barsizes:
                self.revdur[keyfn(barsize)].append(duration)

        # Once managed, sort the durations according to real duration and not
        # to the text form using the utility key above
        for barsize in self.revdur:
            self.revdur[barsize].sort(key=key2fn)

    # 开始
    def start(self, data=None, broker=None):
        self.reconnect(fromstart=True)  # reconnect should be an invariant

        # Datas require some processing to kickstart data reception
        if data is not None:
            self._env = data._env
            # For datas simulate a queue with None to kickstart co
            self.datas.append(data)

            # if connection fails, get a fake registration that will force the
            # datas to try to reconnect or else bail out
            return self.getTickerQueue(start=True)

        elif broker is not None:
            self.broker = broker
    # 结束
    def stop(self):
        try:
            self.conn.disconnect()  # disconnect should be an invariant
        except AttributeError:
            pass    # conn may have never been connected and lack "disconnect"

        # Unblock any calls set on these events
        self._event_managed_accounts.set()
        self._event_accdownload.set()

    # 打印信息到标准输出
    def logmsg(self, *args):
        # for logging purposes
        if self.p._debug:
            print(*args)
    # 注册之后，如果debug模式的话，会打印所有的信息，如果是通知所有信息模式的话，会把所有的信息传递给通知
    def watcher(self, msg):
        # will be registered to see all messages if debug is requested
        self.logmsg(str(msg))
        if self.p.notifyall:
            self.notifs.put((msg, tuple(msg.values()), dict(msg.items())))
    # 用于判断是否已经连接到TWS或者IB上
    def connected(self):
        # The isConnected method is available through __getattr__ indirections
        # and may not be present, which indicates that no connection has been
        # made because the subattribute sender has not yet been created, hence
        # the check for the AttributeError exception
        try:
            return self.conn.isConnected()
        except AttributeError:
            pass

        return False  # non-connected (including non-initialized)

    # 重新连接方法，这个方法必须是一个不变量，方便可以调用很多次
    def reconnect(self, fromstart=False, resub=False):
        # This method must be an invariant in that it can be called several
        # times from the same source and must be consistent. An exampler would
        # be 5 datas which are being received simultaneously and all request a
        # reconnect

        # Policy:
        #  - if dontreconnect has been set, no option to connect is possible
        #  - check connection and use the absence of isConnected as signal of
        #    first ever connection (add 1 to retries too)
        #  - Calculate the retries (forever or not)
        #  - Try to connct
        #  - If achieved and fromstart is false, the datas will be
        #    re-kickstarted to recreate the subscription

        # 设置第一次连接为False，如果现在是连接着的，如果resub是True的话，会调用self.stratdatas(),并返回True
        # 如果没有办法获取是否连接的状态，直接让firstconnect是True
        firstconnect = False
        try:
            if self.conn.isConnected():
                if resub:
                    self.startdatas()
                return True  # nothing to do
        except AttributeError:
            # Not connected, several __getattr__ indirections to
            # self.conn.sender.client.isConnected
            firstconnect = True
        # 如果不让重新连接，调用reconnect的时候，直接返回False
        if self.dontreconnect:
            return False

        # This is only invoked from the main thread by datas and therefore no
        # lock is needed to control synchronicity to it
        # 获取重新尝试的次数，如果尝试次数大于等于0,那么就给尝试次数+1(True=1)
        retries = self.p.reconnect
        if retries >= 0:
            retries += firstconnect
        # 如果尝试次数小于0或者尝试次数大于0的时候，会一直在while循环中，等到尝试次数等于0的时候结束
        while retries < 0 or retries:
            # 如果不是第一次尝试连接，那么，休息timeout秒后重新尝试连接
            if not firstconnect:
                time.sleep(self.p.timeout)
            # 设置firstconnect为False,方便下次连接的时候继续休息
            firstconnect = False
            # 如果连接成功了，如果fromstart是False或者resub是True的话，会调用self.startdatas()，然后返回True
            if self.conn.connect():
                if not fromstart or resub:
                    self.startdatas()
                return True  # connection successful
            # 如果retries大于0减去1,直到等于0跳出循环，或者return
            if retries > 0:
                retries -= 1
        # 如果重新连接到最后，也没有成功，那么把dontreconnect设置成True，返回结果为False,说明没有重新连接成功
        self.dontreconnect = True
        return False  # connection/reconnection failed

    # 请求订阅数据
    def startdatas(self):
        # kickstrat datas, not returning until all of them have been done
        ts = list()
        for data in self.datas:
            t = threading.Thread(target=data.reqdata)
            t.start()
            ts.append(t)

        for t in ts:
            t.join()

    # 停止订阅数据，并按照后进先出的顺序弹出数据
    def stopdatas(self):
        # stop subs and force datas out of the loop (in LIFO order)
        qs = list(self.qs.values())
        ts = list()
        for data in self.datas:
            t = threading.Thread(target=data.canceldata)
            t.start()
            ts.append(t)

        for t in ts:
            t.join()

        for q in reversed(qs):  # datamaster the last one to get a None
            q.put(None)

    # 获取队列中的通知信息
    def get_notifications(self):
        '''Return the pending "store" notifications'''
        # The background thread could keep on adding notifications. The None
        # mark allows to identify which is the last notification to deliver
        self.notifs.put(None)  # put a mark
        notifs = list()
        while True:
            notif = self.notifs.get()
            if notif is None:  # mark is reached
                break
            notifs.append(notif)

        return notifs

    # 注册相关的错误信息
    @ibregister
    def error(self, msg):
        # 100-199 Order/Data/Historical related
        # 200-203 tickerId and Order Related
        # 300-399 A mix of things: orders, connectivity, tickers, misc errors
        # 400-449 Seem order related again
        # 500-531 Connectivity/Communication Errors
        # 10000-100027 Mix of special orders/routing
        # 1100-1102 TWS connectivy to the outside
        # 1300- Socket dropped in client-TWS communication
        # 2100-2110 Informative about Data Farm status (id=-1)

        # All errors are logged to the environment (cerebro), because many
        # errors in Interactive Brokers are actually informational and many may
        # actually be of interest to the user
        # 这个地方感觉和原先的函数形成了互补，导致不论notifyall的参数是什么，信息都会放到self.notifs
        # todo 返回来确认下这个地方究竟有没有错误
        if not self.p.notifyall:
            self.notifs.put((msg, tuple(msg.values()), dict(msg.items())))

        # Manage those events which have to do with connection
        if msg.errorCode is None:
            # Usually received as an error in connection of just before disconn
            pass
        elif msg.errorCode in [200, 203, 162, 320, 321, 322]:
            # cdetails 200 security not found, notify over right queue
            # cdetails 203 security not allowed for acct
            try:
                q = self.qs[msg.id]
            except KeyError:
                pass  # should not happend but it can
            else:
                self.cancelQueue(q, True)

        elif msg.errorCode in [354, 420]:
            # 354 no subscription, 420 no real-time bar for contract
            # the calling data to let the data know ... it cannot resub
            try:
                q = self.qs[msg.id]
            except KeyError:
                pass  # should not happend but it can
            else:
                q.put(-msg.errorCode)
                self.cancelQueue(q)

        elif msg.errorCode == 10225:
            # 10225-Bust event occurred, current subscription is deactivated.
            # Please resubscribe real-time bars immediately.
            try:
                q = self.qs[msg.id]
            except KeyError:
                pass  # should not happend but it can
            else:
                q.put(-msg.errorCode)

        elif msg.errorCode == 326:  # not recoverable, clientId in use
            self.dontreconnect = True
            self.conn.disconnect()
            self.stopdatas()

        elif msg.errorCode == 502:
            # Cannot connect to TWS: port, config not open, tws off (504 then)
            self.conn.disconnect()
            self.stopdatas()

        elif msg.errorCode == 504:  # Not Connected for data op
            # Once for each data
            pass  # don't need to manage it

        elif msg.errorCode == 1300:
            # TWS has been closed. The port for a new connection is there
            # newport = int(msg.errorMsg.split('-')[-1])  # bla bla bla -7496
            self.conn.disconnect()
            self.stopdatas()

        elif msg.errorCode == 1100:
            # Connection lost - Notify ... datas will wait on the queue
            # with no messages arriving
            for q in self.ts:  # key: queue -> ticker
                q.put(-msg.errorCode)

        elif msg.errorCode == 1101:
            # Connection restored and tickerIds are gone
            for q in self.ts:  # key: queue -> ticker
                q.put(-msg.errorCode)

        elif msg.errorCode == 1102:
            # Connection restored and tickerIds maintained
            for q in self.ts:  # key: queue -> ticker
                q.put(-msg.errorCode)

        elif msg.errorCode < 500:
            # Given the myriad of errorCodes, start by assuming is an order
            # error and if not, the checks there will let it go
            if msg.id < self.REQIDBASE:
                if self.broker is not None:
                    self.broker.push_ordererror(msg)
            else:
                # Cancel the queue if a "data" reqId error is given: sanity
                q = self.qs[msg.id]
                self.cancelQueue(q, True)

    # 关闭连接
    @ibregister
    def connectionClosed(self, msg):
        # Sometmes this comes without 1300/502 or any other and will not be
        # seen in error hence the need to manage the situation independently
        self.conn.disconnect()
        self.stopdatas()

    # 管理账户
    @ibregister
    def managedAccounts(self, msg):
        # 1st message in the stream
        self.managed_accounts = msg.accountsList.split(',')
        self._event_managed_accounts.set()

        # Request time to avoid synchronization issues
        self.reqCurrentTime()

    # 请求当前时间
    def reqCurrentTime(self):
        self.conn.reqCurrentTime()

    # 考虑时间差之后的当前时间
    @ibregister
    def currentTime(self, msg):
        if not self.p.timeoffset:  # only if requested ... apply timeoffset
            return
        curtime = datetime.fromtimestamp(float(msg.time))
        with self._lock_tmoffset:
            self.tmoffset = curtime - datetime.now()

        threading.Timer(self.p.timerefresh, self.reqCurrentTime).start()

    # 获取当前的时间差或者时间补偿
    def timeoffset(self):
        with self._lock_tmoffset:
            return self.tmoffset

    # 下一个ticker的id
    def nextTickerId(self):
        # Get the next ticker using next on the itertools.count
        return next(self._tickerId)

    # 下一个有效的order id
    @ibregister
    def nextValidId(self, msg):
        # Create a counter from the TWS notified value to apply to orders
        self.orderid = itertools.count(msg.orderId)

    # 下一个order id
    def nextOrderId(self):
        # Get the next ticker using next on the itertools.count made with the
        # notified value from TWS
        return next(self.orderid)

    # 重新使用queue
    def reuseQueue(self, tickerId):
        '''Reuses queue for tickerId, returning the new tickerId and q'''
        with self._lock_q:
            # Invalidate tickerId in qs (where it is a key)
            q = self.qs.pop(tickerId, None)  # invalidate old
            iscash = self.iscash.pop(tickerId, None)

            # Update ts: q -> ticker
            tickerId = self.nextTickerId()  # get new tickerId
            self.ts[q] = tickerId  # Update ts: q -> tickerId
            self.qs[tickerId] = q  # Update qs: tickerId -> q
            self.iscash[tickerId] = iscash

        return tickerId, q

    # 获取ticker queue
    def getTickerQueue(self, start=False):
        '''Creates ticker/Queue for data delivery to a data feed'''
        q = queue.Queue()
        if start:
            q.put(None)
            return q

        with self._lock_q:
            tickerId = self.nextTickerId()
            self.qs[tickerId] = q  # can be managed from other thread
            self.ts[q] = tickerId
            self.iscash[tickerId] = False

        return tickerId, q

    # 取消队列
    def cancelQueue(self, q, sendnone=False):
        '''Cancels a Queue for data delivery'''
        # pop ts (tickers) and with the result qs (queues)
        tickerId = self.ts.pop(q, None)
        self.qs.pop(tickerId, None)

        self.iscash.pop(tickerId, None)

        if sendnone:
            q.put(None)

    # 判断是否是有效的queue，如果queue在self.ts中，返回True
    def validQueue(self, q):
        '''Returns (bool)  if a queue is still valid'''
        return q in self.ts  # queue -> ticker

    # 获取合约的详细信息
    def getContractDetails(self, contract, maxcount=None):
        cds = list()
        q = self.reqContractDetails(contract)
        while True:
            msg = q.get()
            if msg is None:
                break
            cds.append(msg)

        if not cds or (maxcount and len(cds) > maxcount):
            err = 'Ambiguous contract: none/multiple answers received'
            self.notifs.put((err, cds, {}))
            return None

        return cds

    # 请求合约信息
    def reqContractDetails(self, contract):
        # get a ticker/queue for identification/data delivery
        tickerId, q = self.getTickerQueue()
        self.conn.reqContractDetails(tickerId, contract)
        return q

    # 获取合约信息结束
    @ibregister
    def contractDetailsEnd(self, msg):
        '''Signal end of contractdetails'''
        self.cancelQueue(self.qs[msg.reqId], True)

    # 详细的合约信息，从TWS接收到
    @ibregister
    def contractDetails(self, msg):
        '''Receive answer and pass it to the queue'''
        self.qs[msg.reqId].put(msg)

    # 获取历史数据，方法参数和IB中请求历史数据的方法并不一致
    def reqHistoricalDataEx(self, contract, enddate, begindate,
                            timeframe, compression,
                            what=None, useRTH=False, tz='', sessionend=None,
                            tickerId=None):
        '''
        Extension of the raw reqHistoricalData proxy, which takes two dates
        rather than a duration, barsize and date

        It uses the IB published valid duration/barsizes to make a mapping and
        spread a historical request over several historical requests if needed
        '''
        # Keep a copy for error reporting purposes
        # 获取本地的变量，如果里面有self,删除
        kwargs = locals().copy()
        kwargs.pop('self', None)  # remove self, no need to report it

        # 如果时间周期小于秒，使用这个函数不支持，直接请求tick数据
        if timeframe < TimeFrame.Seconds:
            # Ticks are not supported
            return self.getTickerQueue(start=True)

        # 如果结束时间是None的话，用现在的时间作为结束时间
        if enddate is None:
            enddate = datetime.now()
        # 如果开始时间是None的话，请求最大的可以获取的时间长度，
        # 如果这个时间长度是None的话，认为没有这个周期的时间长度，然后调用函数获取tick数据
        # 如果这个时间长度不是None的话，计算barsize
        # 如果计算得到的barsize是None的话，认为没有这个周期的barsize,然后调用获取tick数据
        # 如果这两个都不是None的话，调用请求数据的函数，得到具体的历史数据
        if begindate is None:
            duration = self.getmaxduration(timeframe, compression)
            if duration is None:
                err = ('No duration for historical data request for '
                       'timeframe/compresison')
                self.notifs.put((err, (), kwargs))
                return self.getTickerQueue(start=True)

            barsize = self.tfcomp_to_size(timeframe, compression)
            if barsize is None:
                err = ('No supported barsize for historical data request for '
                       'timeframe/compresison')
                self.notifs.put((err, (), kwargs))
                return self.getTickerQueue(start=True)

            return self.reqHistoricalData(contract=contract, enddate=enddate,
                                          duration=duration, barsize=barsize,
                                          what=what, useRTH=useRTH, tz=tz,
                                          sessionend=sessionend)
        # Check if the requested timeframe/compression is supported by IB
        # 根据交易周期获取可以获取数据的长度，如果时间长度是None的话，直接调用tick数据
        durations = self.getdurations(timeframe, compression)
        if not durations:  # return a queue and put a None in it
            return self.getTickerQueue(start=True)

        # Get or reuse a queue
        # 如果时间周期不是None的话，
        # 如果tickerId是None的话，直接调用函数获取tickerId和q
        # 如果tickerId不是None的话，调用不同的函数获取tickerId和q
        if tickerId is None:
            tickerId, q = self.getTickerQueue()
        else:
            tickerId, q = self.reuseQueue(tickerId)  # reuse q for old tickerId

        # Get the best possible duration to reduce number of requests
        duration = None
        for dur in durations:
            intdate = self.dt_plus_duration(begindate, dur)
            if intdate >= enddate:
                intdate = enddate
                duration = dur  # begin -> end fits in single request
                break

        if duration is None:  # no duration large enough to fit the request
            duration = durations[-1]

            # Store the calculated data
            self.histexreq[tickerId] = dict(
                contract=contract, enddate=enddate, begindate=intdate,
                timeframe=timeframe, compression=compression,
                what=what, useRTH=useRTH, tz=tz, sessionend=sessionend)

        barsize = self.tfcomp_to_size(timeframe, compression)
        self.histfmt[tickerId] = timeframe >= TimeFrame.Days
        self.histsend[tickerId] = sessionend
        self.histtz[tickerId] = tz

        if contract.m_secType in ['CASH', 'CFD']:
            self.iscash[tickerId] = 1  # msg.field code
            if not what:
                what = 'BID'  # default for cash unless otherwise specified

        elif contract.m_secType in ['IND'] and self.p.indcash:
            self.iscash[tickerId] = 4  # msg.field code

        what = what or 'TRADES'

        self.conn.reqHistoricalData(
            tickerId,
            contract,
            bytes(intdate.strftime('%Y%m%d %H:%M:%S') + ' GMT'),
            bytes(duration),
            bytes(barsize),
            bytes(what),
            int(useRTH),
            2)  # dateformat 1 for string, 2 for unix time in seconds

        return q

    # 从IB上请求历史数据
    def reqHistoricalData(self, contract, enddate, duration, barsize,
                          what=None, useRTH=False, tz='', sessionend=None):
        '''Proxy to reqHistorical Data'''

        # get a ticker/queue for identification/data delivery
        tickerId, q = self.getTickerQueue()

        if contract.m_secType in ['CASH', 'CFD']:
            self.iscash[tickerId] = True
            if not what:
                what = 'BID'  # TRADES doesn't work
            elif what == 'ASK':
                self.iscash[tickerId] = 2
        else:
            what = what or 'TRADES'

        # split barsize "x time", look in sizes for (tf, comp) get tf
        tframe = self._sizes[barsize.split()[1]][0]
        self.histfmt[tickerId] = tframe >= TimeFrame.Days
        self.histsend[tickerId] = sessionend
        self.histtz[tickerId] = tz

        self.conn.reqHistoricalData(
            tickerId,
            contract,
            bytes(enddate.strftime('%Y%m%d %H:%M:%S') + ' GMT'),
            bytes(duration),
            bytes(barsize),
            bytes(what),
            int(useRTH),
            2)

        return q

    # 取消数据请求
    def cancelHistoricalData(self, q):
        '''Cancels an existing HistoricalData request

        Params:
          - q: the Queue returned by reqMktData
        '''
        with self._lock_q:
            self.conn.cancelHistoricalData(self.ts[q])
            self.cancelQueue(q, True)

    # 请求实时bar数据，默认请求的是5秒钟的历史数据
    def reqRealTimeBars(self, contract, useRTH=False, duration=5):
        '''Creates a request for (5 seconds) Real Time Bars

        Params:
          - contract: a ib.ext.Contract.Contract intance
          - useRTH: (default: False) passed to TWS
          - duration: (default: 5) passed to TWS, no other value works in 2016)

        Returns:
          - a Queue the client can wait on to receive a RTVolume instance
        '''
        # get a ticker/queue for identification/data delivery
        tickerId, q = self.getTickerQueue()

        # 20150929 - Only 5 secs supported for duration
        self.conn.reqRealTimeBars(
            tickerId,
            contract,
            duration,
            bytes('TRADES'),
            int(useRTH))

        return q

    # 取消请求历史数据
    def cancelRealTimeBars(self, q):
        '''Cancels an existing MarketData subscription

        Params:
          - q: the Queue returned by reqMktData
        '''
        with self._lock_q:
            tickerId = self.ts.get(q, None)
            if tickerId is not None:
                self.conn.cancelRealTimeBars(tickerId)

            self.cancelQueue(q, True)

    # 请求市场数据
    def reqMktData(self, contract, what=None):
        '''Creates a MarketData subscription

        Params:
          - contract: a ib.ext.Contract.Contract intance

        Returns:
          - a Queue the client can wait on to receive a RTVolume instance
        '''
        # get a ticker/queue for identification/data delivery
        tickerId, q = self.getTickerQueue()
        ticks = '233'  # request RTVOLUME tick delivered over tickString

        if contract.m_secType in ['CASH', 'CFD']:
            self.iscash[tickerId] = True
            ticks = ''  # cash markets do not get RTVOLUME
            if what == 'ASK':
                self.iscash[tickerId] = 2

        # q.put(None)  # to kickstart backfilling
        # Can request 233 also for cash ... nothing will arrive
        self.conn.reqMktData(tickerId, contract, bytes(ticks), False)
        return q

    # 取消请求市场数据
    def cancelMktData(self, q):
        '''Cancels an existing MarketData subscription

        Params:
          - q: the Queue returned by reqMktData
        '''
        with self._lock_q:
            tickerId = self.ts.get(q, None)
            if tickerId is not None:
                self.conn.cancelMktData(tickerId)

            self.cancelQueue(q, True)

    # 处理tick数据的相关函数
    @ibregister
    def tickString(self, msg):
        # Receive and process a tickString message
        # try正常执行了，else也会执行，try没有正常执行，else也不会执行
        if msg.tickType == 48:  # RTVolume
            try:
                rtvol = RTVolume(msg.value)
            except ValueError:  # price not in message ...
                pass
            else:
                # Don't need to adjust the time, because it is in "timestamp"
                # form in the message
                self.qs[msg.tickerId].put(rtvol)

    # 处理cash market的tick数据
    @ibregister
    def tickPrice(self, msg):
        '''Cash Markets have no notion of "last_price"/"last_size" and the
        tracking of the price is done (industry de-facto standard at least with
        the IB API) following the BID price

        A RTVolume which will only contain a price is put into the client's
        queue to have a consistent cross-market interface
        '''
        # Used for "CASH" markets
        # The price field has been seen to be missing in some instances even if
        # "field" is 1
        tickerId = msg.tickerId
        fieldcode = self.iscash[tickerId]
        if fieldcode:
            if msg.field == fieldcode:  # Expected cash field code
                try:
                    if msg.price == -1.0:
                        # seems to indicate the stream is halted for example in
                        # between 23:00 - 23:15 CET for FOREX
                        return
                except AttributeError:
                    pass

                try:
                    rtvol = RTVolume(price=msg.price, tmoffset=self.tmoffset)
                    # print('rtvol with datetime:', rtvol.datetime)
                except ValueError:  # price not in message ...
                    pass
                else:
                    self.qs[tickerId].put(rtvol)

    # 获取实时bar信息
    @ibregister
    def realtimeBar(self, msg):
        '''Receives x seconds Real Time Bars (at the time of writing only 5
        seconds are supported)

        Not valid for cash markets
        '''
        # Get a naive localtime object
        msg.time = datetime.utcfromtimestamp(float(msg.time))
        self.qs[msg.reqId].put(msg)

    # 获取历史数据信息
    @ibregister
    def historicalData(self, msg):
        '''Receives the events of a historical data request'''
        # For multi-tiered downloads we'd need to rebind the queue to a new
        # tickerId (in case tickerIds are not reusable) and instead of putting
        # None, issue a new reqHistData with the new data and move formward
        tickerId = msg.reqId
        q = self.qs[tickerId]
        if msg.date.startswith('finished-'):
            self.histfmt.pop(tickerId, None)
            self.histsend.pop(tickerId, None)
            self.histtz.pop(tickerId, None)
            kargs = self.histexreq.pop(tickerId, None)
            if kargs is not None:
                self.reqHistoricalDataEx(tickerId=tickerId, **kargs)
                return

            msg.date = None
            self.cancelQueue(q)
        else:
            dtstr = msg.date  # Format when string req: YYYYMMDD[  HH:MM:SS]
            if self.histfmt[tickerId]:
                sessionend = self.histsend[tickerId]
                dt = datetime.strptime(dtstr, '%Y%m%d')
                dteos = datetime.combine(dt, sessionend)
                tz = self.histtz[tickerId]
                if tz:
                    dteostz = tz.localize(dteos)
                    dteosutc = dteostz.astimezone(UTC).replace(tzinfo=None)
                    # When requesting for example daily bars, the current day
                    # will be returned with the already happened data. If the
                    # session end were added, the new ticks wouldn't make it
                    # through, because they happen before the end of time
                else:
                    dteosutc = dteos

                if dteosutc <= datetime.utcnow():
                    dt = dteosutc

                msg.date = dt
            else:
                msg.date = datetime.utcfromtimestamp(long(dtstr))

        q.put(msg)


    # 获取交易周期的时间长度
    def getdurations(self,  timeframe, compression):
        key = (timeframe, compression)
        if key not in self.revdur:
            return []

        return self.revdur[key]

    # 获取交易周期的最大时间长度
    def getmaxduration(self, timeframe, compression):
        key = (timeframe, compression)
        try:
            return self.revdur[key][-1]
        except (KeyError, IndexError):
            pass

        return None

    # 把timeframe和compression转换成 barsize
    def tfcomp_to_size(self, timeframe, compression):
        if timeframe == TimeFrame.Months:
            return '{} M'.format(compression)

        if timeframe == TimeFrame.Weeks:
            return '{} W'.format(compression)

        if timeframe == TimeFrame.Days:
            if not compression % 7:
                return '{} W'.format(compression // 7)

            return '{} day'.format(compression)

        if timeframe == TimeFrame.Minutes:
            if not compression % 60:
                hours = compression // 60
                return ('{} hour'.format(hours)) + ('s' * (hours > 1))

            return ('{} min'.format(compression)) + ('s' * (compression > 1))

        if timeframe == TimeFrame.Seconds:
            return '{} secs'.format(compression)

        # Microseconds or ticks
        return None

    #
    def dt_plus_duration(self, dt, duration):
        size, dim = duration.split()
        size = int(size)
        if dim == 'S':
            return dt + timedelta(seconds=size)

        if dim == 'D':
            return dt + timedelta(days=size)

        if dim == 'W':
            return dt + timedelta(days=size * 7)

        if dim == 'M':
            month = dt.month - 1 + size  # -1 to make it 0 based, readd below
            years, month = divmod(month, 12)
            return dt.replace(year=dt.year + years, month=month + 1)

        if dim == 'Y':
            return dt.replace(year=dt.year + size)

        return dt  # could do nothing with it ... return it intact

    def calcdurations(self, dtbegin, dtend):
        '''Calculate a duration in between 2 datetimes'''
        duration = self.histduration(dtbegin, dtend)

        if duration[-1] == 'M':
            m = int(duration.split()[0])
            m1 = min(2, m)  # (2, 1) -> 1, (2, 7) -> 2. Bottomline: 1 or 2
            m2 = max(1, m1)  # m1 can only be 1 or 2
            checkdur = '{} M'.format(m2)
        elif duration[-1] == 'Y':
            checkdur = '1 Y'
        else:
            checkdur = duration
        # todo 此处代码上有bug,改为下面的
        # sizes = self._durations[checkduration]
        sizes = self._durations[checkdur]
        return duration, sizes

    # 计算两个时间之间的时间长度和barsize
    def calcduration(self, dtbegin, dtend):
        '''Calculate a duration in between 2 datetimes. Returns single size'''
        duration, sizes = self._calcdurations(dtbegin, dtend)
        return duration, sizes[0]

    # 根据IB 历史数据API的限制，返回两个日期之间最小可能的时间长度
    def histduration(self, dt1, dt2):
        # Given two dates calculates the smallest possible duration according
        # to the table from the Historical Data API limitations provided by IB
        #
        # Seconds: 'x S' (x: [60, 120, 180, 300, 600, 900, 1200, 1800, 3600,
        #                     7200, 10800, 14400, 28800])
        # Days: 'x D' (x: [1, 2]
        # Weeks: 'x W' (x: [1, 2])
        # Months: 'x M' (x: [1, 11])
        # Years: 'x Y' (x: [1])

        td = dt2 - dt1  # get a timedelta for calculations

        # First: array of secs
        tsecs = td.total_seconds()
        secs = [60, 120, 180, 300, 600, 900, 1200, 1800, 3600, 7200, 10800,
                14400, 28800]

        idxsec = bisect.bisect_left(secs, tsecs)
        if idxsec < len(secs):
            return '{} S'.format(secs[idxsec])

        tdextra = bool(td.seconds or td.microseconds)  # over days/weeks

        # Next: 1 or 2 days
        days = td.days + tdextra
        if td.days <= 2:
            return '{} D'.format(days)

        # Next: 1 or 2 weeks
        weeks, d = divmod(td.days, 7)
        weeks += bool(d or tdextra)
        if weeks <= 2:
            return '{} W'.format(weeks)

        # Get references to dt components
        y2, m2, d2 = dt2.year, dt2.month, dt2.day
        y1, m1, d1 = dt1.year, dt1.month, dt2.day

        H2, M2, S2, US2 = dt2.hour, dt2.minute, dt2.second, dt2.microsecond
        H1, M1, S1, US1 = dt1.hour, dt1.minute, dt1.second, dt1.microsecond

        # Next: 1 -> 11 months (11 incl)
        months = (y2 * 12 + m2) - (y1 * 12 + m1) + (
            (d2, H2, M2, S2, US2) > (d1, H1, M1, S1, US1))
        if months <= 1:  # months <= 11
            return '1 M'  # return '{} M'.format(months)
        elif months <= 11:
            return '2 M'  # cap at 2 months to keep the table clean

        # Next: years
        # y = y2 - y1 + (m2, d2, H2, M2, S2, US2) > (m1, d1, H1, M1, S1, US1)
        # return '{} Y'.format(y)

        return '1 Y'  # to keep the table clean

    # 根据需要，创建合约
    def makecontract(self, symbol, sectype, exch, curr,
                     expiry='', strike=0.0, right='', mult=1):
        '''returns a contract from the parameters without check'''

        contract = Contract()
        contract.m_symbol = bytes(symbol)
        contract.m_secType = bytes(sectype)
        contract.m_exchange = bytes(exch)
        if curr:
            contract.m_currency = bytes(curr)
        if sectype in ['FUT', 'OPT', 'FOP']:
            contract.m_expiry = bytes(expiry)
        if sectype in ['OPT', 'FOP']:
            contract.m_strike = strike
            contract.m_right = bytes(right)
        if mult:
            contract.m_multiplier = bytes(mult)
        return contract

    # 取消订单
    def cancelOrder(self, orderid):
        '''Proxy to cancelOrder'''
        self.conn.cancelOrder(orderid)

    # 下单
    def placeOrder(self, orderid, contract, order):
        '''Proxy to placeOrder'''
        self.conn.placeOrder(orderid, contract, order)

    # 接收到 openOrder的状态
    @ibregister
    def openOrder(self, msg):
        '''Receive the event ``openOrder`` events'''
        self.broker.push_orderstate(msg)

    # 接收到执行的细节
    @ibregister
    def execDetails(self, msg):
        '''Receive execDetails'''
        self.broker.push_execution(msg.execution)

    # 接受到orderStatus的事件
    @ibregister
    def orderStatus(self, msg):
        '''Receive the event ``orderStatus``'''
        self.broker.push_orderstatus(msg)

    # 接受到手续费用报告的事件
    @ibregister
    def commissionReport(self, msg):
        '''Receive the event commissionReport'''
        self.broker.push_commissionreport(msg.commissionReport)

    # 请求当前的持仓
    def reqPositions(self):
        '''Proxy to reqPositions'''
        self.conn.reqPositions()

    # 持仓，还没有实施
    @ibregister
    def position(self, msg):
        '''Receive event positions'''
        pass  # Not implemented yet

    # 请求更新账户
    def reqAccountUpdates(self, subscribe=True, account=None):
        '''Proxy to reqAccountUpdates

        If ``account`` is ``None``, wait for the ``managedAccounts`` message to
        set the account codes
        '''
        if account is None:
            self._event_managed_accounts.wait()
            account = self.managed_accounts[0]

        self.conn.reqAccountUpdates(subscribe, bytes(account))

    # 账户信息更新完毕
    @ibregister
    def accountDownloadEnd(self, msg):
        # Signals the end of an account update
        # the event indicates it's over. It's only false once, and can be used
        # to find out if it has at least been downloaded once
        self._event_accdownload.set()
        if False:
            if self.port_update:
                self.broker.push_portupdate()

                self.port_update = False

    # 更新投资组合
    @ibregister
    def updatePortfolio(self, msg):
        # Lock access to the position dicts. This is called in sub-thread and
        # can kick in at any time
        with self._lock_pos:
            if not self._event_accdownload.is_set():  # 1st event seen
                position = Position(msg.position, msg.averageCost)
                self.positions[msg.contract.m_conId] = position
            else:
                position = self.positions[msg.contract.m_conId]
                if not position.fix(msg.position, msg.averageCost):
                    err = ('The current calculated position and '
                           'the position reported by the broker do not match. '
                           'Operation can continue, but the trades '
                           'calculated in the strategy may be wrong')

                    self.notifs.put((err, (), {}))

                # Flag signal to broker at the end of account download
                # self.port_update = True
                self.broker.push_portupdate()

    # 获取账户持仓
    def getposition(self, contract, clone=False):
        # Lock access to the position dicts. This is called from main thread
        # and updates could be happening in the background
        with self._lock_pos:
            position = self.positions[contract.m_conId]
            if clone:
                return copy(position)

            return position

    # 更新账户价值
    @ibregister
    def updateAccountValue(self, msg):
        # Lock access to the dicts where values are updated. This happens in a
        # sub-thread and could kick it at anytime
        with self._lock_accupd:
            try:
                value = float(msg.value)
            except ValueError:
                value = msg.value

            self.acc_upds[msg.accountName][msg.key][msg.currency] = value

            if msg.key == 'NetLiquidation':
                # NetLiquidationByCurrency and currency == 'BASE' is the same
                self.acc_value[msg.accountName] = value
            elif msg.key == 'TotalCashBalance' and msg.currency == 'BASE':
                self.acc_cash[msg.accountName] = value
    # 获取所有账户价值信息
    def get_acc_values(self, account=None):
        '''Returns all account value infos sent by TWS during regular updates
        Waits for at least 1 successful download

        If ``account`` is ``None`` then a dictionary with accounts as keys will
        be returned containing all accounts

        If account is specified or the system has only 1 account the dictionary
        corresponding to that account is returned
        '''
        # Wait for at least 1 account update download to have been finished
        # before the account infos can be returned to the calling client
        if self.connected():
            self._event_accdownload.wait()
        # Lock access to acc_cash to avoid an event intefering
        with self._updacclock:
            if account is None:
                # wait for the managedAccount Messages
                if self.connected():
                    self._event_managed_accounts.wait()

                if not self.managed_accounts:
                    return self.acc_upds.copy()

                elif len(self.managed_accounts) > 1:
                    return self.acc_upds.copy()

                # Only 1 account, fall through to return only 1
                account = self.managed_accounts[0]

            try:
                return self.acc_upds[account].copy()
            except KeyError:
                pass

            return self.acc_upds.copy()

    # 获取账户的净的清算价值
    def get_acc_value(self, account=None):
        '''Returns the net liquidation value sent by TWS during regular updates
        Waits for at least 1 successful download

        If ``account`` is ``None`` then a dictionary with accounts as keys will
        be returned containing all accounts

        If account is specified or the system has only 1 account the dictionary
        corresponding to that account is returned
        '''
        # Wait for at least 1 account update download to have been finished
        # before the value can be returned to the calling client
        if self.connected():
            self._event_accdownload.wait()
        # Lock access to acc_cash to avoid an event intefering
        with self._lock_accupd:
            if account is None:
                # wait for the managedAccount Messages
                if self.connected():
                    self._event_managed_accounts.wait()

                if not self.managed_accounts:
                    return float()

                elif len(self.managed_accounts) > 1:
                    return sum(self.acc_value.values())

                # Only 1 account, fall through to return only 1
                account = self.managed_accounts[0]

            try:
                return self.acc_value[account]
            except KeyError:
                pass

            return float()

    # 获取账户的总的现金价值
    def get_acc_cash(self, account=None):
        '''Returns the total cash value sent by TWS during regular updates
        Waits for at least 1 successful download

        If ``account`` is ``None`` then a dictionary with accounts as keys will
        be returned containing all accounts

        If account is specified or the system has only 1 account the dictionary
        corresponding to that account is returned
        '''
        # Wait for at least 1 account update download to have been finished
        # before the cash can be returned to the calling client
        if self.connected():
            self._event_accdownload.wait()
        # Lock access to acc_cash to avoid an event intefering
        with self._lock_accupd:
            if account is None:
                # wait for the managedAccount Messages
                if self.connected():
                    self._event_managed_accounts.wait()

                if not self.managed_accounts:
                    return float()

                elif len(self.managed_accounts) > 1:
                    return sum(self.acc_cash.values())

                # Only 1 account, fall through to return only 1
                account = self.managed_accounts[0]

            try:
                return self.acc_cash[account]
            except KeyError:
                pass
