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
import datetime
import inspect
import io
import os.path

import backtrader as bt
from backtrader import (date2num, num2date, time2num, TimeFrame, dataseries,
                        metabase)

from backtrader.utils.py3 import with_metaclass, zip, range, string_types
from backtrader.utils import tzparse
from .dataseries import SimpleFilterWrapper
from .resamplerfilter import Resampler, Replayer
from .tradingcal import PandasMarketCalendar

# 这个元抽象类主要继承OHLCDateTime，然后在初始化的时候对数据的名称、时间、过滤器等进行一定的处理
class MetaAbstractDataBase(dataseries.OHLCDateTime.__class__):
    # _indcol的属性设置为一个空的字典
    _indcol = dict()

    def __init__(cls, name, bases, dct):
        '''
        Class has already been created ... register subclasses
        '''
        # Initialize the class
        # cls已经被创建出来了，进行初始化
        super(MetaAbstractDataBase, cls).__init__(name, bases, dct)
        # 如果cls的名字是空的，并且name不等于“DataBase",并且不是以"_"开始的，就把name作为key，cls作为value添加到cls的_indcol属性中
        if not cls.aliased and name != 'DataBase' and not name.startswith('_'):
            cls._indcol[name] = cls

    def dopreinit(cls, _obj, *args, **kwargs):
        # 进行preinit操作
        _obj, args, kwargs = super(MetaAbstractDataBase, cls).dopreinit(_obj, *args, **kwargs)
        # Find the owner and store it
        # findowner用于发现_obj的父类，但是是FeedBase的实例
        _obj._feed = metabase.findowner(_obj, FeedBase)
        # 初始化一个队列，用于存储从cerebro来的信息
        _obj.notifs = collections.deque()  # store notifications for cerebro
        # 从参数中获取_dataname的值
        _obj._dataname = _obj.p.dataname
        # 默认_name属性是空
        _obj._name = ''
        return _obj, args, kwargs

    def dopostinit(cls, _obj, *args, **kwargs):
        # 进行postinit操作
        _obj, args, kwargs = super(MetaAbstractDataBase, cls).dopostinit(_obj, *args, **kwargs)

        # Either set by subclass or the parameter or use the dataname (ticker)
        # 重新设置_name属性，如果_name属性不是空的，就保持，如果是空的，就让它等于参数中的name的值
        _obj._name = _obj._name or _obj.p.name
        # 如果_name属性值还是为空，并且参数dataname的值是字符串的话，就把_name设置为dataname值
        if not _obj._name and isinstance(_obj.p.dataname, string_types):
            _obj._name = _obj.p.dataname
        # _compression值等于参数compression的值
        _obj._compression = _obj.p.compression
        # _timeframe的值等于参数timeframe的值
        _obj._timeframe = _obj.p.timeframe
        # 开始的时间如果是datetime格式，就等于从sessionstart获取具体的时间，如果是None的话，等于最小的时间
        if isinstance(_obj.p.sessionstart, datetime.datetime):
            _obj.p.sessionstart = _obj.p.sessionstart.time()

        elif _obj.p.sessionstart is None:
            _obj.p.sessionstart = datetime.time.min
        # 结束的时间如果是datetime格式，就等于从sessionend获取具体的时间，如果是None的话，等于23：59：59.999990
        if isinstance(_obj.p.sessionend, datetime.datetime):
            _obj.p.sessionend = _obj.p.sessionend.time()

        elif _obj.p.sessionend is None:
            # remove 9 to avoid precision rounding errors
            _obj.p.sessionend = datetime.time(23, 59, 59, 999990)
        # 如果开始日期是date格式，如果没有hour的属性的话，就增加sessionstart的时间，把开始日期变成了日期+时间的格式
        if isinstance(_obj.p.fromdate, datetime.date):
            # push it to the end of the day, or else intraday
            # values before the end of the day would be gone
            if not hasattr(_obj.p.fromdate, 'hour'):
                _obj.p.fromdate = datetime.datetime.combine(
                    _obj.p.fromdate, _obj.p.sessionstart)
        # 如果结束日期是date格式，如果没有hour的属性的话，就增加sessionend的时间，把结束日期变成了日期+时间的格式
        if isinstance(_obj.p.todate, datetime.date):
            # push it to the end of the day, or else intraday
            # values before the end of the day would be gone
            if not hasattr(_obj.p.todate, 'hour'):
                _obj.p.todate = datetime.datetime.combine(
                    _obj.p.todate, _obj.p.sessionend)
        # 设置_barstack,_barstash两个属性作为队列，用于过滤操作
        _obj._barstack = collections.deque()  # for filter operations
        _obj._barstash = collections.deque()  # for filter operations
        # 设置_filters,_ffilters作为空的列表
        _obj._filters = list()
        _obj._ffilters = list()
        # 遍历参数中的filters，先判断是否是类，如果是类，就先实例化，如果实例中有last属性，就把这个过滤器传入到_ffilters中
        # 如果不是类，就直接把过滤器传入到_filters中
        for fp in _obj.p.filters:
            if inspect.isclass(fp):
                fp = fp(_obj)
                if hasattr(fp, 'last'):
                    _obj._ffilters.append((fp, [], {}))

            _obj._filters.append((fp, [], {}))

        return _obj, args, kwargs


# 这个类是抽象数据基类，继承MetaAbstractDataBase和dataseries.OHLCDateTime
class AbstractDataBase(with_metaclass(MetaAbstractDataBase,
                                      dataseries.OHLCDateTime)):
    # 参数的初始化设置
    params = (
        ('dataname', None),
        ('name', ''),
        ('compression', 1),
        ('timeframe', TimeFrame.Days),
        ('fromdate', None),
        ('todate', None),
        ('sessionstart', None),
        ('sessionend', None),
        ('filters', []),
        ('tz', None),
        ('tzinput', None),
        ('qcheck', 0.0),  # timeout in seconds (float) to check for events
        ('calendar', None),
    )

    # 数据的八种不同的状态
    (CONNECTED, DISCONNECTED, CONNBROKEN, DELAYED,
     LIVE, NOTSUBSCRIBED, NOTSUPPORTED_TF, UNKNOWN) = range(8)

    # 通知的名字
    _NOTIFNAMES = [
        'CONNECTED', 'DISCONNECTED', 'CONNBROKEN', 'DELAYED',
        'LIVE', 'NOTSUBSCRIBED', 'NOTSUPPORTED_TIMEFRAME', 'UNKNOWN']

    # 类方法，获取数据的状态
    @classmethod
    def _getstatusname(cls, status):
        return cls._NOTIFNAMES[status]

    # 初始化下面的几个变量，在实盘中可能会使用到
    _compensate = None
    _feed = None
    _store = None

    _clone = False
    _qcheck = 0.0

    # 时间偏移
    _tmoffset = datetime.timedelta()

    # Set to non 0 if resampling/replaying
    # 是否抽样或者重播，如果不得话，设置成0
    resampling = 0
    replaying = 0

    # 是否已经开始
    _started = False

    def _start_finish(self):
        # A live feed (for example) may have learnt something about the
        # timezones after the start and that's why the date/time related
        # parameters are converted at this late stage
        # Get the output timezone (if any)
        # 获取具体的时区
        self._tz = self._gettz()
        # Lines have already been create, set the tz
        # 给时间设置具体的时区
        self.lines.datetime._settz(self._tz)

        # This should probably be also called from an override-able method
        # 本地化输入的时区
        self._tzinput = bt.utils.date.Localizer(self._gettzinput())

        # Convert user input times to the output timezone (or min/max)
        # 把用户输入的开始和结束时间转化为具体的数字，如果是None的话，开始时间是无限小的数字，结束时间是无限大的数字
        # 如果是具体的时间的话，就使用date2num转化为具体的数字
        if self.p.fromdate is None:
            self.fromdate = float('-inf')
        else:
            self.fromdate = self.date2num(self.p.fromdate)

        if self.p.todate is None:
            self.todate = float('inf')
        else:
            self.todate = self.date2num(self.p.todate)

        # FIXME: These two are never used and could be removed
        # 这两个是不会用到的，可以删除
        self.sessionstart = time2num(self.p.sessionstart)     
        self.sessionend = time2num(self.p.sessionend)         

        # 从参数中获取日历，如果日历是None的话，就从本地环境中寻找_tradingcal，如果是字符串的话，就使用PandasMarketCalendar
        self._calendar = cal = self.p.calendar
        if cal is None:
            self._calendar = self._env._tradingcal
        elif isinstance(cal, string_types):
            self._calendar = PandasMarketCalendar(calendar=cal)
        # 开始状态
        self._started = True

    def _start(self):
        self.start()
        # 如果还没进入到开始状态，先初始化，然后进入开始状态
        if not self._started:
            self._start_finish()

    def _timeoffset(self):
        # 时间偏移量
        return self._tmoffset

    # 返回下个交易日结束的时间格式的时间和数字格式的时间
    def _getnexteos(self):
        '''Returns the next eos using a trading calendar if available'''
        if self._clone:
            return self.data._getnexteos()

        if not len(self):
            return datetime.datetime.min, 0.0

        dt = self.lines.datetime[0]
        dtime = num2date(dt)
        if self._calendar is None:
            nexteos = datetime.datetime.combine(dtime, self.p.sessionend)
            nextdteos = self.date2num(nexteos)  # locl'ed -> utc-like
            nexteos = num2date(nextdteos)  # utc
            while dtime > nexteos:
                nexteos += datetime.timedelta(days=1)  # already utc-like

            nextdteos = date2num(nexteos)  # -> utc-like

        else:
            # returns times in utc
            _, nexteos = self._calendar.schedule(dtime, self._tz)
            nextdteos = date2num(nexteos)  # nextos is already utc

        return nexteos, nextdteos

    # 把tzinput进行解析，并返回
    def _gettzinput(self):
        '''Can be overriden by classes to return a timezone for input'''
        return tzparse(self.p.tzinput)

    # 把tz进行解析，并返回
    def _gettz(self):
        '''To be overriden by subclasses which may auto-calculate the
        timezone'''
        return tzparse(self.p.tz)

    # 把时间转化成数字，如果时区信息不是None的话，先把时间进行本地化，然后再转化
    def date2num(self, dt):
        if self._tz is not None:
            return date2num(self._tz.localize(dt))

        return date2num(dt)

    # 把数字转化成日期+时间
    def num2date(self, dt=None, tz=None, naive=True):
        if dt is None:
            return num2date(self.lines.datetime[0], tz or self._tz, naive)

        return num2date(dt, tz or self._tz, naive)

    # 是否具有实时数据，默认是没有，如果有实时数据，需要重写
    def haslivedata(self):
        return False  # must be overriden for those that can

    # 实盘数据进行抽样的时候，等待的时间间隔
    def do_qcheck(self, onoff, qlapse):
        # if onoff is True the data will wait p.qcheck for incoming live data
        # on its queue.
        qwait = self.p.qcheck if onoff else 0.0
        qwait = max(0.0, qwait - qlapse)
        self._qcheck = qwait

    # 是否是实时数据，默认是没有，如果有的话，cerebro会不在使用preload和runonce，因为一个实时数据需要
    # 一个个tick或者bar进行获取
    def islive(self):
        '''If this returns True, ``Cerebro`` will deactivate ``preload`` and
        ``runonce`` because a live data source must be fetched tick by tick (or
        bar by bar)'''
        return False

    # 如果最新的状态不等于当前状态，需要把信息添加到notifs中以便更新最新状态
    def put_notification(self, status, *args, **kwargs):
        '''Add arguments to notification queue'''
        if self._laststatus != status:
            self.notifs.append((status, args, kwargs))
            self._laststatus = status

    # 获取通知信息，保存到notifs中作为结果返回
    def get_notifications(self):
        '''Return the pending "store" notifications'''
        # The background thread could keep on adding notifications. The None
        # mark allows to identify which is the last notification to deliver
        # 添加一个None，获取到None了，就代表这个队列是空的了，信息已经取完
        self.notifs.append(None)  # put a mark
        notifs = list()
        while True:
            notif = self.notifs.popleft()
            if notif is None:  # mark is reached
                break
            notifs.append(notif)

        return notifs

    # 获取feed
    def getfeed(self):
        return self._feed

    # 缓存数据的量
    def qbuffer(self, savemem=0, replaying=False):
        extrasize = self.resampling or replaying
        for line in self.lines:
            line.qbuffer(savemem=savemem, extrasize=extrasize)

    # 开始，重新设置了_barstack，_barstash
    def start(self):
        self._barstack = collections.deque()
        self._barstash = collections.deque()
        self._laststatus = self.CONNECTED

    # 结束
    def stop(self):
        pass

    # 克隆数据
    def clone(self, **kwargs):
        return DataClone(dataname=self, **kwargs)

    # 复制数据并作为另外一个名字
    def copyas(self, _dataname, **kwargs):
        d = DataClone(dataname=self, **kwargs)
        d._dataname = _dataname
        d._name = _dataname
        return d

    # 设置环境
    def setenvironment(self, env):
        '''Keep a reference to the environment'''
        self._env = env

    # 获取环境
    def getenvironment(self):
        return self._env

    # 添加简单的过滤器
    def addfilter_simple(self, f, *args, **kwargs):
        fp = SimpleFilterWrapper(self, f, *args, **kwargs)
        self._filters.append((fp, fp.args, fp.kwargs))

    # 添加过滤器
    def addfilter(self, p, *args, **kwargs):
        if inspect.isclass(p):
            pobj = p(self, *args, **kwargs)
            self._filters.append((pobj, [], {}))

            if hasattr(pobj, 'last'):
                self._ffilters.append((pobj, [], {}))

        else:
            self._filters.append((p, args, kwargs))

    # 补偿
    def compensate(self, other):
        '''Call it to let the broker know that actions on this asset will
        compensate open positions in another'''

        self._compensate = other

    # 给非datetime的名称设置一个tick_+名称的属性为None，主要是在从高频率数据合成低频率数据的时候使用
    def _tick_nullify(self):
        # These are the updating prices in case the new bar is "updated"
        # and the length doesn't change like if a replay is happening or
        # a real-time data feed is in use and 1 minutes bars are being
        # constructed with 5 seconds updates
        for lalias in self.getlinealiases():
            if lalias != 'datetime':
                setattr(self, 'tick_' + lalias, None)

        self.tick_last = None

    # 如果tick_xxx相关的属性值是None的话，就要考虑使用bar的数据去填充
    def _tick_fill(self, force=False):
        # If nothing filled the tick_xxx attributes, the bar is the tick
        alias0 = self._getlinealias(0)
        if force or getattr(self, 'tick_' + alias0, None) is None:
            for lalias in self.getlinealiases():
                if lalias != 'datetime':
                    setattr(self, 'tick_' + lalias,
                            getattr(self.lines, lalias)[0])

            self.tick_last = getattr(self.lines, alias0)[0]

    # 获取未来一个bar的时间
    def advance_peek(self):
        if len(self) < self.buflen():
            return self.lines.datetime[1]  # return the future

        return float('inf')  # max date else

    # 把数据向前移动size
    def advance(self, size=1, datamaster=None, ticks=True):
        if ticks:
            self._tick_nullify()

        # Need intercepting this call to support datas with
        # different lengths (timeframes)
        self.lines.advance(size)

        if datamaster is not None:
            if len(self) > self.buflen():
                # if no bar can be delivered, fill with an empty bar
                self.rewind()
                self.lines.forward()
                return

            if self.lines.datetime[0] > datamaster.lines.datetime[0]:
                self.lines.rewind()
            else:
                if ticks:
                    self._tick_fill()
        elif len(self) < self.buflen():
            # a resampler may have advance us past the last point
            if ticks:
                self._tick_fill()

    # 调用next时，在数据上发生的事情
    def next(self, datamaster=None, ticks=True):
        # 如果数据长度大于缓存的数据长度，如果是ticks数据的话，调用_tick_nullify生成tick_xxx属性，然后调用load尝试获取下一个bar，如果获取到的ret是空的
        # 返回ret.如果主数据是None的话，如果是ticks数据的话，需要调用_tick_fill.
        # 如果自身的长度小于缓存的数据的长度，向前移动
        if len(self) >= self.buflen():
            if ticks:
                self._tick_nullify()

            # not preloaded - request next bar
            ret = self.load()
            if not ret:
                # if load cannot produce bars - forward the result
                return ret

            if datamaster is None:
                # bar is there and no master ... return load's result
                if ticks:
                    self._tick_fill()
                return ret
        else:
            self.advance(ticks=ticks)
        # 如果主数据不是None，如果当前数据的时间大于了主数据的时间，就需要向后调整；
        # 如果当前数据时间没有大于主数据的时间，并且数据还是ticks数据的话，就需要对当前数据进行填充数据
        # 如果主数据是None的话，并且数据还是ticks数据的话，就需要对当天数据进行填充数据
        # a bar is "loaded" or was preloaded - index has been moved to it
        if datamaster is not None:
            # there is a time reference to check against
            if self.lines.datetime[0] > datamaster.lines.datetime[0]:
                # can't deliver new bar, too early, go back
                self.rewind()
                return False
            else:
                if ticks:
                    self._tick_fill()

        else:
            if ticks:
                self._tick_fill()

        # tell the world there is a bar (either the new or the previous
        # 说明当前有一个bar
        return True

    # 预先加载数据
    def preload(self):
        # 加载数据
        while self.load():
            pass

        self._last()
        self.home()

    # 使用过滤器的最后一个机会
    def _last(self, datamaster=None):
        # Last chance for filters to deliver something
        
        ret = 0
        for ff, fargs, fkwargs in self._ffilters:
            ret += ff.last(self, *fargs, **fkwargs)

        doticks = False
        if datamaster is not None and self._barstack:
            doticks = True

        while self._fromstack(forward=True):
            # consume bar(s) produced by "last"s - adding room
            pass

        if doticks:
            self._tick_fill()

        return bool(ret)

    # 判断是否需要进行检查
    def _check(self, forcedata=None):
        ret = 0
        for ff, fargs, fkwargs in self._filters:
            if not hasattr(ff, 'check'):
                continue
            ff.check(self, _forcedata=forcedata, *fargs, **fkwargs)

    # 加载数据
    def load(self):
        
        while True:
            # move data pointer forward for new bar
            # 把数据指针向前移动一位
            self.forward()

            # 如果已经从self._barstack中获取了数据，保存到了line中，就直接返回True
            if self._fromstack():  # bar is available
                return True
            # 如果从self._barstash中获取不了数据，那么，就运行下面的代码
            if not self._fromstack(stash=True):
                # _load()返回的是False,下面的代码必然运行，但是似乎不用调用这个函数，也不用对下面进行判断，这两个语句似乎是多余的
                ###  暂时不能100%确定，后续注释完成代码之后再回来看这个    #fix
                _loadret = self._load()
                if not _loadret:  # no bar use force to make sure in exactbars
                    # the pointer is undone this covers especially (but not
                    # uniquely) the case in which the last bar has been seen
                    # and a backwards would ruin pointer accounting in the
                    # "stop" method of the strategy
                    self.backwards(force=True)  # undo data pointer

                    # return the actual returned value which may be None to
                    # signal no bar is available, but the data feed is not
                    # done. False means game over
                    return _loadret
                
            # 如果既没有从self._barstack中获取到bar，但是在self._barstash中获取到了bar,就需要对bar进行处理
            # Get a reference to current loaded time
            # 获取当前的时间
            dt = self.lines.datetime[0]

            # A bar has been loaded, adapt the time
            # 如果需要对输入的时间做时区的处理，那么就把数字转化成时间，然后把时间进行本地化，然后把时间转化成数字，更新当前的时间
            if self._tzinput:
                # Input has been converted at face value but it's not UTC in
                # the input stream
                dtime = num2date(dt)  # get it in a naive datetime
                # localize it
                dtime = self._tzinput.localize(dtime)  # pytz compatible-ized
                self.lines.datetime[0] = dt = date2num(dtime)  # keep UTC val

            # Check standard date from/to filters
            # 如果当前的时间小于开始的时间，向后退丢掉这个bar，然后继续
            if dt < self.fromdate:
                # discard loaded bar and carry on
                self.backwards()
                continue
            # 如果时间大于结束时间，向后退并撤销数据指针，并break
            if dt > self.todate:
                # discard loaded bar and break out
                self.backwards(force=True)
                break

            # Pass through filters
            # 遍历每个过滤器
            retff = False
            for ff, fargs, fkwargs in self._filters:
                # previous filter may have put things onto the stack
                # 如果self._barstack不是空的话
                if self._barstack:
                    # 进行self._barstack个长度的_fromstack函数调用，过滤器ff调用
                    for i in range(len(self._barstack)):
                        self._fromstack(forward=True)
                        retff = ff(self, *fargs, **fkwargs)
                # 如果self._barstack是空的话,调用一次过滤器
                else:
                    retff = ff(self, *fargs, **fkwargs)
                # 如果retff是真的话，跳出过滤器的循环
                if retff:  # bar removed from systemn
                    break  # out of the inner loop
            # 如果是真的话，继续
            if retff:  # bar removed from system - loop to get new bar
                continue  # in the greater loop

            # Checks let the bar through ... notify it
            return True
        # 结束循环，返回False,没有更多的bar或者到结束日期了
        # Out of the loop ... no more bars or past todate
        return False

    # 返回False的一个函数
    def _load(self):
        return False

    # 把bar的数据添加到self._barstack或者self._barstash中
    def _add2stack(self, bar, stash=False):
        '''Saves given bar (list of values) to the stack for later retrieval'''
        if not stash:
            self._barstack.append(bar)
        else:
            self._barstash.append(bar)

    # 获取bar的数据，保存到self._barstack或者self._barstash，并且提供了参数，可以删除bar
    def _save2stack(self, erase=False, force=False, stash=False):
        '''Saves current bar to the bar stack for later retrieval

        Parameter ``erase`` determines removal from the data stream
        '''
        
        bar = [line[0] for line in self.itersize()]
        if not stash:
            self._barstack.append(bar)
        else:
            self._barstash.append(bar)

        if erase:  # remove bar if requested
            self.backwards(force=force)

    # 这个注释有问题，这个函数是用于把bar的数据更新到具体的line上
    def _updatebar(self, bar, forward=False, ago=0):
        '''Load a value from the stack onto the lines to form the new bar

        Returns True if values are present, False otherwise
        '''
        if forward:
            self.forward()

        for line, val in zip(self.itersize(), bar):
            line[0 + ago] = val

    # 从self._barstack或者self._barstash获取数据，然后保存到line中，如果成功，就返回True，如果不成功，返回False
    def _fromstack(self, forward=False, stash=False):
        '''Load a value from the stack onto the lines to form the new bar

        Returns True if values are present, False otherwise
        '''
        # 当stash是False的时候，coll等于self._barstack,否则就是self._barstash
        coll = self._barstack if not stash else self._barstash
        # 如果coll是有数据的
        if coll:
            # 如果forward是True的话，就调用forward
            if forward:
                self.forward()
            # 给line增加数据
            for line, val in zip(self.itersize(), coll.popleft()):
                line[0] = val

            return True

        return False
    
    #  增加抽样过滤器
    def resample(self, **kwargs):
        self.addfilter(Resampler, **kwargs)

    # 增加重播过滤器
    def replay(self, **kwargs):
        self.addfilter(Replayer, **kwargs)


# DataBase类，直接继承的是抽象的DataBase
class DataBase(AbstractDataBase):
    pass


# FeedBase类
class FeedBase(with_metaclass(metabase.MetaParams, object)):
    # 更新FeedBase类的参数，初始化的时候是继承了DataBase的默认参数设置
    params = () + DataBase.params._gettuple()

    # 初始化的时候，datas设置成空的列表
    def __init__(self):
        self.datas = list()
        
    # 数据开始
    def start(self):
        for data in self.datas:
            data.start()
            
    # 数据结束
    def stop(self):
        for data in self.datas:
            data.stop()

    # 根据dataname获取数据，并把数据添加到self.datas中
    def getdata(self, dataname, name=None, **kwargs):
        # 获取参数中的参数名称、value，并保存到关键字参数中(默认字典)
        for pname, pvalue in self.p._getitems():
            kwargs.setdefault(pname, getattr(self.p, pname))

        kwargs['dataname'] = dataname
        data = self._getdata(**kwargs)

        data._name = name

        self.datas.append(data)
        return data

    def _getdata(self, dataname, **kwargs):
        # 设置关键字参数
        for pname, pvalue in self.p._getitems():
            kwargs.setdefault(pname, getattr(self.p, pname))
        # 增加一个dataname的key
        kwargs['dataname'] = dataname
        return self.DataCls(**kwargs)


# CSVDataBase的元类，继承自DataBase，在postinit的时候，给_obj设置_name属性
class MetaCSVDataBase(DataBase.__class__):
    def dopostinit(cls, _obj, *args, **kwargs):
        # Before going to the base class to make sure it overrides the default
        # 如果参数中没有名字并且_name属性是空的话，从数据文件的名称得到一个具体的名字
        if not _obj.p.name and not _obj._name:
            _obj._name, _ = os.path.splitext(os.path.basename(_obj.p.dataname))

        _obj, args, kwargs = \
            super(MetaCSVDataBase, cls).dopostinit(_obj, *args, **kwargs)

        return _obj, args, kwargs


class CSVDataBase(with_metaclass(MetaCSVDataBase, DataBase)):
    '''
    Base class for classes implementing CSV DataFeeds

    The class takes care of opening the file, reading the lines and
    tokenizing them.

    Subclasses do only need to override:

      - _loadline(tokens)

    The return value of ``_loadline`` (True/False) will be the return value
    of ``_load`` which has been overriden by this base class
    '''
    # 数据默认是None
    f = None
    # 设置具体的参数
    params = (('headers', True), ('separator', ','),)

    # 获取数据并简单处理
    def start(self):
        super(CSVDataBase, self).start()
        # 如果数据是None的话
        if self.f is None:
            # 如果参数中dataname具有readline属性，那么就说明dataname是一个数据，直接f等于参数中的数据
            if hasattr(self.p.dataname, 'readline'):
                self.f = self.p.dataname
            # 如果没有readline属性的话，说明dataname是一个地址，那么就根据这个地址打开文件，获取数据
            else:
                # Let an exception propagate to let the caller know
                self.f = io.open(self.p.dataname, 'r')
        # 如果有headers的话，就读取一行，跳过headers
        if self.p.headers:
            self.f.readline()  # skip the headers
        # 每一行数据的分隔符
        self.separator = self.p.separator

    # 停止
    def stop(self):
        super(CSVDataBase, self).stop()
        # 如果数据文件不是None，就关闭文件，并设置成None
        if self.f is not None:
            self.f.close()
            self.f = None

    # 提前load数据
    def preload(self):
        # load数据
        while self.load():
            pass
        # 结束load之后的设置
        self._last()
        self.home()

        # preloaded - no need to keep the object around - breaks multip in 3.x
        # 关闭数据文件，并设置成None
        self.f.close()
        self.f = None

    # 加载一行数据
    def _load(self):
        # 如果数据文件是None，返回False,如果读取不到line了，返回False,对line进行处理，调用_loadline进行加载
        if self.f is None:
            return False

        # Let an exception propagate to let the caller know
        line = self.f.readline()

        if not line:
            return False

        line = line.rstrip('\n')
        linetokens = line.split(self.separator)
        return self._loadline(linetokens)

    # 获取下一行数据
    def _getnextline(self):
        # 这个函数和上一个很类似，只是上一个函数获取了linetokens多了一个_loadline的调用
        if self.f is None:
            return None

        # Let an exception propagate to let the caller know
        line = self.f.readline()

        if not line:
            return None

        line = line.rstrip('\n')
        linetokens = line.split(self.separator)
        return linetokens


class CSVFeedBase(FeedBase):
    # 设置参数
    params = (('basepath', ''),) + CSVDataBase.params._gettuple()
    # 获取数据
    def _getdata(self, dataname, **kwargs):
        return self.DataCls(dataname=self.p.basepath + dataname,
                            **self.p._getkwargs())

# 数据克隆
class DataClone(AbstractDataBase):
    
    # _clone属性设置为True
    _clone = True
    
    # 初始化，data等于参数中的dataname的值,_datename等于data的_dataname属性值
    # 然后copy日期、时间、交易间隔、compression的参数
    def __init__(self):
        self.data = self.p.dataname
        self._dataname = self.data._dataname

        # Copy date/session parameters
        self.p.fromdate = self.p.fromdate
        self.p.todate = self.p.todate
        self.p.sessionstart = self.data.p.sessionstart
        self.p.sessionend = self.data.p.sessionend

        self.p.timeframe = self.data.p.timeframe
        self.p.compression = self.data.p.compression

    def _start(self):
        # redefine to copy data bits from guest data
        self.start()

        # Copy tz infos
        self._tz = self.data._tz
        self.lines.datetime._settz(self._tz)

        self._calendar = self.data._calendar

        # input has already been converted by guest data
        self._tzinput = None  # no need to further converr

        # Copy dates/session infos
        self.fromdate = self.data.fromdate
        self.todate = self.data.todate

        # FIXME: if removed from guest, remove here too
        self.sessionstart = self.data.sessionstart    
        self.sessionend = self.data.sessionend        

    # 开始
    def start(self):
        super(DataClone, self).start()
        self._dlen = 0
        self._preloading = False

    # preload数据
    def preload(self):
        self._preloading = True
        super(DataClone, self).preload()
        self.data.home()  # preloading data was pushed forward
        self._preloading = False

    # load数据
    def _load(self):
        # assumption: the data is in the system
        # simply copy the lines
        # 如果准备preload的话，运行下面的代码，一点点copy具体的数据
        if self._preloading:
            # data is preloaded, we are preloading too, can move
            # forward until have full bar or data source is exhausted
            # 数据向前
            self.data.advance()
            # 如果当前的数据大于了数据的缓存的长度，返回False
            if len(self.data) > self.data.buflen():
                return False
            # 如果当前的数据长度没有大于缓存的数据长度，那么就设置line的数据为dline的数据
            for line, dline in zip(self.lines, self.data.lines):
                line[0] = dline[0]
            # 设置成功之后返回True
            return True

        # Not preloading
        # 这句语法不怎么高效，换成len(self.data)<=self._dlen，可能可以少做一个判断
        if len(self.data) <= self._dlen: 
        # if not (len(self.data) > self._dlen): # backtrader自带
            # Data not beyond last seen bar
            return False

        # 数据长度加1
        self._dlen += 1

        # 设置line的数据为dline的数据
        for line, dline in zip(self.lines, self.data.lines):
            line[0] = dline[0]

        return True
    
    # 向前移动size的量
    def advance(self, size=1, datamaster=None, ticks=True):
        self._dlen += size
        super(DataClone, self).advance(size, datamaster, ticks=ticks)
