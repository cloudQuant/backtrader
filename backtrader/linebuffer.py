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
'''

.. module:: linebuffer

Classes that hold the buffer for a *line* and can operate on it
with appends, forwarding, rewinding, resetting and other

.. moduleauthor:: Daniel Rodriguez

'''
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import array
import collections
import datetime
from itertools import islice
import math

from .utils.py3 import range, with_metaclass, string_types

from .lineroot import LineRoot, LineSingle, LineMultiple
from . import metabase
from .utils import num2date, time2num


NAN = float('NaN')


class LineBuffer(LineSingle):
    '''
    LineBuffer defines an interface to an "array.array" (or list) in which
    index 0 points to the item which is active for input and output.

    Positive indices fetch values from the past (left hand side)
    Negative indices fetch values from the future (if the array has been
    extended on the right hand side)

    With this behavior no index has to be passed around to entities which have
    to work with the current value produced by other entities: the value is
    always reachable at "0".

    Likewise storing the current value produced by "self" is done at 0.

    Additional operations to move the pointer (home, forward, extend, rewind,
    advance getzero) are provided

    The class can also hold "bindings" to other LineBuffers. When a value
    is set in this class
    it will also be set in the binding.
    LineBuffer主要是用于定义一个操作array.array的接口，在调用line[0]的时候得到的是当前输入输出的活跃值，如果是在next中调用，line[0]就代表着当前时间点的值
    
    '''
    # 给LineBuffer定义了属性，他们的值分别为0和1
    UnBounded, QBuffer = (0, 1)

    # 初始化操作
    def __init__(self):
        self.lines = [self]                     # lines是一个包含自身的列表
        self.mode = self.UnBounded              # self.mode默认值是0
        self.bindings = list()                  # self.bindlings默认是一个列表
        self.reset()                            # 重置，调用的是自身的reset方法
        self._tz = None                         # 时区设置

    # 获取_idx的值
    def get_idx(self):
        return self._idx

    # 设置_idx的值
    def set_idx(self, idx, force=False):
        # if QBuffer and the last position of the buffer was reached, keep
        # it (unless force) as index 0. This allows resampling
        #  - forward adds a position, but the 1st one is discarded, the 0 is
        #  invariant
        # force supports replaying, which needs the extra bar to float
        # forward/backwards, because the last input is read, and after a
        # "backwards" is used to update the previous data. Unless the position
        # 0 was moved to the previous index, it would fail
        # 在设置idx的值得时候，根据两种状态来进行设置，如果是缓存模式(QBuffer),需要满足force等于True或者self._idx小于self.lenmark才能给self._idx重新赋值
        if self.mode == self.QBuffer:
            if force or self._idx < self.lenmark:
                self._idx = idx
        else:  # default: UnBounded
            self._idx = idx
    # property的用法，可以用于获取idx和设置idx
    idx = property(get_idx, set_idx)

    # 重置
    def reset(self):
        ''' Resets the internal buffer structure and the indices
        '''
        # 如果是缓存模式，保存的数据量是一定的，就会使用deque来保存数据，有一个最大的长度，超过这个长度的时候回踢出最前面的数据
        if self.mode == self.QBuffer:
            # add extrasize to ensure resample/replay work because they will
            # use backwards to erase the last bar/tick before delivering a new
            # bar The previous forward would have discarded the bar "period"
            # times ago and it will not come back. Having + 1 in the size
            # allows the forward without removing that bar
            self.array = collections.deque(maxlen=self.maxlen + self.extrasize)
            self.useislice = True
        else:
            self.array = array.array(str('d'))
            self.useislice = False
        # 默认最开始的时候lencount等于0,idx等于-1,extension等于0
        self.lencount = 0
        self.idx = -1
        self.extension = 0

    # 设置缓存相关的变量
    def qbuffer(self, savemem=0, extrasize=0):
        self.mode = self.QBuffer                            # 设置具体的模式
        self.maxlen = self._minperiod                       # 设置最大的长度
        self.extrasize = extrasize                          # 设置额外的量
        self.lenmark = self.maxlen - (not self.extrasize)   # 最大长度减去1,如果extrasize=0的话
        self.reset()                                        # 重置

    # 获取指标值
    def getindicators(self):
        return []

    # 最小缓存
    def minbuffer(self, size):
        '''The linebuffer must guarantee the minimum requested size to be
        available.

        In non-dqbuffer mode, this is always true (of course until data is
        filled at the beginning, there are less values, but minperiod in the
        framework should account for this.

        In dqbuffer mode the buffer has to be adjusted for this if currently
        less than requested
        '''
        # 如果不是缓存模式，或者最大的长度大于size，返回None
        if self.mode != self.QBuffer or self.maxlen >= size:
            return
        # 在缓存模式下，maxlen等于size
        self.maxlen = size
        # # 最大长度减去1,如果self.extrasize=0的话
        self.lenmark = self.maxlen - (not self.extrasize)
        # 重置
        self.reset()

    # 返回实际的长度
    def __len__(self):
        return self.lencount

    # 返回line缓存的数据的长度
    def buflen(self):
        ''' Real data that can be currently held in the internal buffer

        The internal buffer can be longer than the actual stored data to
        allow for "lookahead" operations. The real amount of data that is
        held/can be held in the buffer
        is returned
        '''
        return len(self.array) - self.extension

    # 获取值
    def __getitem__(self, ago):
        return self.array[self.idx + ago]

    # 获取数据的值，在策略中使用还是比较广泛的
    def get(self, ago=0, size=1):
        ''' Returns a slice of the array relative to *ago*

        Keyword Args:
            ago (int): Point of the array to which size will be added
            to return the slice size(int): size of the slice to return,
            can be positive or negative

        If size is positive *ago* will mark the end of the iterable and vice
        versa if size is negative

        Returns:
            A slice of the underlying buffer
        '''
        # 是否使用切片，如果使用按照下面的语法
        if self.useislice:
            start = self.idx + ago - size + 1
            end = self.idx + ago + 1
            return list(islice(self.array, start, end))
        
        # 如果不使用切片，直接截取
        return self.array[self.idx + ago - size + 1:self.idx + ago + 1]

    # 返回array真正的0处的变量值
    def getzeroval(self, idx=0):
        ''' Returns a single value of the array relative to the real zero
        of the buffer

        Keyword Args:
            idx (int): Where to start relative to the real start of the buffer
            size(int): size of the slice to return

        Returns:
            A slice of the underlying buffer
        '''
        return self.array[idx]

    # 返回array从idx开始，size个长度的数据
    def getzero(self, idx=0, size=1):
        ''' Returns a slice of the array relative to the real zero of the buffer

        Keyword Args:
            idx (int): Where to start relative to the real start of the buffer
            size(int): size of the slice to return

        Returns:
            A slice of the underlying buffer
        '''
        if self.useislice:
            return list(islice(self.array, idx, idx + size))

        return self.array[idx:idx + size]

    # 给array相关的值
    def __setitem__(self, ago, value):
        ''' Sets a value at position "ago" and executes any associated bindings

        Keyword Args:
            ago (int): Point of the array to which size will be added to return
            the slice
            value (variable): value to be set
        '''
        self.array[self.idx + ago] = value
        for binding in self.bindings:
            binding[ago] = value
            
    # 给array设置具体的值
    def set(self, value, ago=0):
        ''' Sets a value at position "ago" and executes any associated bindings

        Keyword Args:
            value (variable): value to be set
            ago (int): Point of the array to which size will be added to return
            the slice
        '''
        self.array[self.idx + ago] = value
        for binding in self.bindings:
            binding[ago] = value

    # 返回到最开始
    def home(self):
        ''' Rewinds the logical index to the beginning

        The underlying buffer remains untouched and the actual len can be found
        out with buflen
        '''
        self.idx = -1
        self.lencount = 0

    # 向前移动一位
    def forward(self, value=NAN, size=1):
        ''' Moves the logical index foward and enlarges the buffer as much as needed

        Keyword Args:
            value (variable): value to be set in new positins
            size (int): How many extra positions to enlarge the buffer
        '''
        self.idx += size
        self.lencount += size

        for i in range(size):
            self.array.append(value)

    # 向后移动一位
    def backwards(self, size=1, force=False):
        ''' Moves the logical index backwards and reduces the buffer as much as needed

        Keyword Args:
            size (int): How many extra positions to rewind and reduce the
            buffer
        '''
        # Go directly to property setter to support force
        self.set_idx(self._idx - size, force=force)
        self.lencount -= size
        for i in range(size):
            self.array.pop()

    # 把idx和lencount减少size
    def rewind(self, size=1):
        self.idx -= size
        self.lencount -= size

    # 把idx和lencount增加size
    def advance(self, size=1):
        ''' Advances the logical index without touching the underlying buffer

        Keyword Args:
            size (int): How many extra positions to move forward
        '''
        self.idx += size
        self.lencount += size

    # 向前扩展
    def extend(self, value=NAN, size=0):
        ''' Extends the underlying array with positions that the index will not reach

        Keyword Args:
            value (variable): value to be set in new positins
            size (int): How many extra positions to enlarge the buffer

        The purpose is to allow for lookahead operations or to be able to
        set values in the buffer "future"
        '''
        self.extension += size
        for i in range(size):
            self.array.append(value)

    # 增加另一条LineBuffer
    def addbinding(self, binding):
        ''' Adds another line binding

        Keyword Args:
            binding (LineBuffer): another line that must be set when this line
            becomes a value
        '''
        self.bindings.append(binding)
        # record in the binding when the period is starting (never sooner
        # than self)
        binding.updateminperiod(self._minperiod)

    # 获取从idx开始的全部数据
    def plot(self, idx=0, size=None):
        ''' Returns a slice of the array relative to the real zero of the buffer

        Keyword Args:
            idx (int): Where to start relative to the real start of the buffer
            size(int): size of the slice to return

        This is a variant of getzero which unless told otherwise returns the
        entire buffer, which is usually the idea behind plottint (all must
        plotted)

        Returns:
            A slice of the underlying buffer
        '''
        return self.getzero(idx, size or len(self))

    # 获取array的部分数据
    def plotrange(self, start, end):
        if self.useislice:
            return list(islice(self.array, start, end))

        return self.array[start:end]

    # 在once的时候，给每个binding设置array的变量
    def oncebinding(self):
        '''
        Executes the bindings when running in "once" mode
        '''
        larray = self.array
        blen = self.buflen()
        for binding in self.bindings:
            binding.array[0:blen] = larray[0:blen]

    # 把blinding转变成line
    def bind2lines(self, binding=0):
        '''
        Stores a binding to another line. "binding" can be an index or a name
        '''
        if isinstance(binding, string_types):
            line = getattr(self._owner.lines, binding)
        else:
            line = self._owner.lines[binding]

        self.addbinding(line)

        return self

    bind2line = bind2lines
    
    # 调用的时候返回一个自身的延迟版本或者时间周期改变版本
    def __call__(self, ago=None):
        '''Returns either a delayed verison of itself in the form of a
        LineDelay object or a timeframe adapting version with regards to a ago

        Param: ago (default: None)

          If ago is None or an instance of LineRoot (a lines object) the
          returned valued is a LineCoupler instance

          If ago is anything else, it is assumed to be an int and a LineDelay
          object will be returned
        '''
        from .lineiterator import LineCoupler
        if ago is None or isinstance(ago, LineRoot):
            return LineCoupler(self, ago)

        return LineDelay(self, ago)

    # 做一些操作
    def _makeoperation(self, other, operation, r=False, _ownerskip=None):
        return LinesOperation(self, other, operation, r=r,
                              _ownerskip=_ownerskip)

    # 对自身做操作
    def _makeoperationown(self, operation, _ownerskip=None):
        return LineOwnOperation(self, operation, _ownerskip=_ownerskip)

    # 设置时区
    def _settz(self, tz):
        self._tz = tz

    # 返回具体的日期-时间
    def datetime(self, ago=0, tz=None, naive=True):
        return num2date(self.array[self.idx + ago],
                        tz=tz or self._tz, naive=naive)

    # 返回具体的日期
    def date(self, ago=0, tz=None, naive=True):
        return num2date(self.array[self.idx + ago],
                        tz=tz or self._tz, naive=naive).date()

    # 返回具体的时间
    def time(self, ago=0, tz=None, naive=True):
        return num2date(self.array[self.idx + ago],
                        tz=tz or self._tz, naive=naive).time()

    # 返回时间相关的浮点数的整数部分
    def dt(self, ago=0):
        '''
        return numeric date part of datetimefloat
        '''
        return math.trunc(self.array[self.idx + ago])

    # 返回时间相关浮点数的小数部分
    def tm_raw(self, ago=0):
        '''
        return raw numeric time part of datetimefloat
        '''
        # This function is named raw because it retrieves the fractional part
        # without transforming it to time to avoid the influence of the day
        # count (integer part of coding)
        return math.modf(self.array[self.idx + ago])[0]

    # 把一个日期-时间格式的时间部分转化成浮点数
    def tm(self, ago=0):
        '''
        return numeric time part of datetimefloat
        '''
        # To avoid precision errors, this returns the fractional part after
        # having converted it to a datetime.time object to avoid precision
        # errors in comparisons
        return time2num(num2date(self.array[self.idx + ago]).time())

    # 对比数据中的日期-时间是否小于数据中的日期+other的大小
    def tm_lt(self, other, ago=0):
        '''
        return numeric time part of datetimefloat
        '''
        # To compare a raw "tm" part (fractional part of coded datetime)
        # with the tm of the current datetime, the raw "tm" has to be
        # brought in sync with the current "day" count (integer part) to avoid
        dtime = self.array[self.idx + ago]
        tm, dt = math.modf(dtime)

        return dtime < (dt + other)

    # 对比数据中的日期-时间是否小于等于数据中的日期+other的大小
    def tm_le(self, other, ago=0):
        '''
        return numeric time part of datetimefloat
        '''
        # To compare a raw "tm" part (fractional part of coded datetime)
        # with the tm of the current datetime, the raw "tm" has to be
        # brought in sync with the current "day" count (integer part) to avoid
        dtime = self.array[self.idx + ago]
        tm, dt = math.modf(dtime)

        return dtime <= (dt + other)

    # 对比数据中的日期-时间是否等于数据中的日期+other的大小
    def tm_eq(self, other, ago=0):
        '''
        return numeric time part of datetimefloat
        '''
        # To compare a raw "tm" part (fractional part of coded datetime)
        # with the tm of the current datetime, the raw "tm" has to be
        # brought in sync with the current "day" count (integer part) to avoid
        dtime = self.array[self.idx + ago]
        tm, dt = math.modf(dtime)

        return dtime == (dt + other)

    # 对比数据中的日期-时间是否大于数据中的日期+other的大小
    def tm_gt(self, other, ago=0):
        '''
        return numeric time part of datetimefloat
        '''
        # To compare a raw "tm" part (fractional part of coded datetime)
        # with the tm of the current datetime, the raw "tm" has to be
        # brought in sync with the current "day" count (integer part) to avoid
        dtime = self.array[self.idx + ago]
        tm, dt = math.modf(dtime)

        return dtime > (dt + other)

    # 对比数据中的日期-时间是否大于等于数据中的日期+other的大小
    def tm_ge(self, other, ago=0):
        '''
        return numeric time part of datetimefloat
        '''
        # To compare a raw "tm" part (fractional part of coded datetime)
        # with the tm of the current datetime, the raw "tm" has to be
        # brought in sync with the current "day" count (integer part) to avoid
        dtime = self.array[self.idx + ago]
        tm, dt = math.modf(dtime)

        return dtime >= (dt + other)

    # 把时间转化成日期-时间的形式，浮点数
    def tm2dtime(self, tm, ago=0):
        '''
        Returns the given ``tm`` in the frame of the (ago bars) datatime.

        Useful for external comparisons to avoid precision errors
        '''
        return int(self.array[self.idx + ago]) + tm

    # 把时间转化成日期-时间的形式，时间格式
    def tm2datetime(self, tm, ago=0):
        '''
        Returns the given ``tm`` in the frame of the (ago bars) datatime.

        Useful for external comparisons to avoid precision errors
        '''
        return num2date(int(self.array[self.idx + ago]) + tm)


class MetaLineActions(LineBuffer.__class__):
    '''
    Metaclass for LineActions

    Scans the instance before init for LineBuffer (or parentclass LineSingle)
    instances to calculate the minperiod for this instance

    postinit it registers the instance to the owner (remember that owner has
    been found in the base Metaclass for LineRoot)
    '''
    # LineActions的元类，
    # 在初始化的时候扫描LineBuffer或者LineSingle的父类的实例，用于计算这个实例的最小周期
    # 在postinit的时候，把这个实例注册给父类，这个父类是在LineRoot中已经存在的
    _acache = dict()                # _acache看起来是缓存的意思
    _acacheuse = False              # _acachuse是否使用缓存                                                                                                                           


    @classmethod
    def cleancache(cls):
        '''类方法，清除实例中的缓存'''
        cls._acache = dict()

    @classmethod
    def usecache(cls, onoff):
        '''类方法，修改实例属性，决定是否使用缓存'''
        cls._acacheuse = onoff

    def __call__(cls, *args, **kwargs):
        if not cls._acacheuse:
            # 如果不使用缓存模式，直接调用相应的__call__方法
            return super(MetaLineActions, cls).__call__(*args, **kwargs)

        # implement a cache to avoid duplicating lines actions
        # 如果使用缓存模式，就实施一个缓存，避免重复的line行动，缓存的key使用的是cls，参数，关键字参数组成的一个元组，这个元组是可哈希的，可以作为字典的key
        ckey = (cls, tuple(args), tuple(kwargs.items()))  # tuples hashable
        # 如果缓存中存在这个ckey，调用的时候直接返回相应的值。如果不存在这个key，就忽略；如果ckey类型错误，就调用相应的__call__方法
        try:
            return cls._acache[ckey]
        except TypeError:  # something not hashable
            return super(MetaLineActions, cls).__call__(*args, **kwargs)
        except KeyError:
            pass  # hashable but not in the cache
        # 使用_obj保存调用__call__方法形成的对象，然后把ckey和_obj设置为缓存的值和value
        _obj = super(MetaLineActions, cls).__call__(*args, **kwargs)
        return cls._acache.setdefault(ckey, _obj)

    def dopreinit(cls, _obj, *args, **kwargs):
        # 调用dopreinit生成_obj,args,kwargs
        _obj, args, kwargs = \
            super(MetaLineActions, cls).dopreinit(_obj, *args, **kwargs)

        # 让_obj的属性_clock等于_obj的_owner，这个_owner通常是父类
        _obj._clock = _obj._owner  # default setting

        # 如果args[0]是LineRoot的子类，就让_obj的属性_clock等于args[0]
        if isinstance(args[0], LineRoot):
            _obj._clock = args[0]

        # Keep a reference to the datas for buffer adjustment purposes
        # 设置_obj的_datas的属性，如果args中的对象是LineRoot的子类，就保存到_datas的列表中
        _obj._datas = [x for x in args if isinstance(x, LineRoot)]

        # Do not produce anything until the operation lines produce something
        # 如果args中的对象是LineSingle的子类，就获取_minperiod,赋值给_minperiods
        _minperiods = [x._minperiod for x in args if isinstance(x, LineSingle)]
        # 如果args中的对象是LineMultiple的子类，就获取多条line的第一条,赋值给mlines
        mlines = [x.lines[0] for x in args if isinstance(x, LineMultiple)]
        # 把从单个line或者多个line对象中第一条line的最小周期汇总到一个list中
        _minperiods += [x._minperiod for x in mlines]
        # 如果_minperiods不是空的列表的话，就返回_minperiods中的最大值,否则就返回1,这行代码写的水平挺高的
        _minperiod = max(_minperiods or [1])
        # update own minperiod if needed
        # 如果需要就更新_obj的最小周期
        _obj.updateminperiod(_minperiod)
        # dopreinit的时候返回的处理过的_obj
        return _obj, args, kwargs

    def dopostinit(cls, _obj, *args, **kwargs):
        # dopostinit操作，看起来是增加指标相关的操作
        _obj, args, kwargs = \
            super(MetaLineActions, cls).dopostinit(_obj, *args, **kwargs)

        # register with _owner to be kicked later
        _obj._owner.addindicator(_obj)

        return _obj, args, kwargs


class PseudoArray(object):
    '''伪array,访问任何的index的时候都会返回来wrapped,使用.array会返回自身'''
    def __init__(self, wrapped):
        self.wrapped = wrapped

    def __getitem__(self, key):
        return self.wrapped

    @property
    def array(self):
        return self


class LineActions(with_metaclass(MetaLineActions, LineBuffer)):
    '''
    Base class derived from LineBuffer intented to defined the
    minimum interface to make it compatible with a LineIterator by
    providing operational _next and _once interfaces.

    The metaclass does the dirty job of calculating minperiods and registering
    '''
    # 继承LineBuffer和MetaLineActions的基础类，定义了一个最小的接口，通过提供_next和_once来兼容LineIterator的操作
    # 这个类还用于计算最小周期和注册

    _ltype = LineBuffer.IndType       # 用于获取这个line的类型，line的类型最开始来自于LineRoot

    def getindicators(self):
        '''获取指标值，返回的是空的列表'''
        return []

    def qbuffer(self, savemem=0):
        '''设置最小的缓存量'''
        super(LineActions, self).qbuffer(savemem=savemem)
        for data in self._datas:
            data.minbuffer(size=self._minperiod)

    @staticmethod
    def arrayize(obj):
        '''把obj进行array化'''
        # 如果obj属于LineRoot的子类
        if isinstance(obj, LineRoot):
            # 如果是多条的line,返回第一条line,否则返回的是line
            if not isinstance(obj, LineSingle):
                obj = obj.lines[0]  # get 1st line from multiline
        # 如果obj不属于LineRoot的子类，就使用PseudoArray进行初始化，形成一个假的array
        else:
            obj = PseudoArray(obj)

        return obj

    def _next(self):
        clock_len = len(self._clock)    # 获取时钟的长度
        # 如果时钟大于自身的长度，那么自身就需要往前进一步
        if clock_len > len(self):
            self.forward()
        # 如果时钟长度大于最小周期了，就开始运行next
        if clock_len > self._minperiod:
            self.next()
        # 如果时钟长度正好等于最小周期，就调用依次nextstart
        elif clock_len == self._minperiod:
            # only called for the 1st value
            self.nextstart()
        # 如果时钟长度小于最小周期，就调用prenext
        else:
            self.prenext()

    def _once(self):
        # 调用once的时候进行的操作
        self.forward(size=self._clock.buflen())                 # 向前移动size位
        self.home()                                             # 返回原来，idx和count变为0 

        self.preonce(0, self._minperiod - 1)                    # preconce操作
        self.oncestart(self._minperiod - 1, self._minperiod)    # oncestart操作
        self.once(self._minperiod, self.buflen())               # once操作

        self.oncebinding()                                      # oncebindling操作


def LineDelay(a, ago=0, **kwargs):
    # line向前和向后的操作，如果ago小于0,就使用_LineSelay,如果ago大于0,就使用_LineForward
    if ago <= 0:
        return _LineDelay(a, ago, **kwargs)

    return _LineForward(a, ago, **kwargs)


def LineNum(num):
    # 对一个具体的num，先实现一个伪的array，然后调用LineDelay,这个是在lineiterator中调用的
    return LineDelay(PseudoArray(num))


class _LineDelay(LineActions):
    '''
    Takes a LineBuffer (or derived) object and stores the value from
    "ago" periods effectively delaying the delivery of data
    '''
    # 对LineBuffer对象或者其子类操作，在delay数据的时候能够有效的保存ago周期前的数据
    def __init__(self, a, ago):
        super(_LineDelay, self).__init__()
        self.a = a
        self.ago = ago

        # Need to add the delay to the period. "ago" is 0 based and therefore
        # we need to pass and extra 1 which is the minimum defined period for
        # any data (which will be substracted inside addminperiod)
        self.addminperiod(abs(ago) + 1)

    def next(self):
        # 在每次next的时候通过调用a的self.ago的index的值，然后添加到self这个line上面
        self[0] = self.a[self.ago]

    def once(self, start, end):
        # cache python dictionary lookups
        # 调用once的时候，根据a的数据,生成对应的ago前的数据形成的array
        dst = self.array
        src = self.a.array
        ago = self.ago

        for i in range(start, end):
            dst[i] = src[i + ago]


class _LineForward(LineActions):
    '''
    Takes a LineBuffer (or derived) object and stores the value from
    "ago" periods from the future
    '''
    # 跟_LineDelay对应
    def __init__(self, a, ago):
        super(_LineForward, self).__init__()
        self.a = a
        self.ago = ago

        # Need to add the delay to the period. "ago" is 0 based and therefore
        # we need to pass and extra 1 which is the minimum defined period for
        # any data (which will be substracted inside addminperiod)
        # self.addminperiod(abs(ago) + 1)
        if ago > self.a._minperiod:
            self.addminperiod(ago - self.a._minperiod + 1)

    def next(self):
        self[-self.ago] = self.a[0]

    def once(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        src = self.a.array
        ago = self.ago

        for i in range(start, end):
            dst[i - ago] = src[i]


class LinesOperation(LineActions):

    '''
    Holds an operation that operates on a two operands. Example: mul

    It will "next"/traverse the array applying the operation on the
    two operands and storing the result in self.

    To optimize the operations and avoid conditional checks the right
    next/once is chosen using the operation direction (normal or reversed)
    and the nature of the operands (LineBuffer vs non-LineBuffer)

    In the "once" operations "map" could be used as in:

        operated = map(self.operation, srca[start:end], srcb[start:end])
        self.array[start:end] = array.array(str(self.typecode), operated)

    No real execution time benefits were appreciated and therefore the loops
    have been kept in place for clarity (although the maps are not really
    unclear here)
    '''
    # 对两条line进行操作，a是line，b是line或者时间或者数字,operation是操作方法，r代表是否对a和b反转
    def __init__(self, a, b, operation, r=False):
        super(LinesOperation, self).__init__()

        self.operation = operation                              # 操作方法
        self.a = a  # always a linebuffer                       # a是line
        self.b = b                                              # 保存b

        self.r = r                                              # r代表是否对a,b进行反转
        self.bline = isinstance(b, LineBuffer)                  # 判断b是否是line         
        self.btime = isinstance(b, datetime.time)               # 判断b是否是时间
        self.bfloat = not self.bline and not self.btime         # 判断b是否是浮点数
        # 如果反转，就互换a,b的值
        if r:
            self.a, self.b = b, a

    def next(self):
        # 对line的所有数据进行操作
        # 如果a和b都是line
        if self.bline:
            self[0] = self.operation(self.a[0], self.b[0])
        # 如果b不是line的情况下，如果没有互换a,b的值
        elif not self.r:
            # 如果b不是时间，那么，b是浮点数，直接进行操作
            if not self.btime:
                self[0] = self.operation(self.a[0], self.b)
            # 如果b是时间，那么就把a转化为时间，然后和b进行操作
            else:
                self[0] = self.operation(self.a.time(), self.b)
        # 如果互换了a,b的值，此时a是时间或者浮点数，b是line,感觉这里面需要考虑要不要增加判断a是否是时间的操作，后面代码中进行控制也可以，这里面目前来看，代码逻辑层面不是很完善
        else:
            self[0] = self.operation(self.a, self.b[0])

    def once(self, start, end):
        # 对line的部分数据进行操作
        # 如果b是line，就调用_once_op函数
        if self.bline:
            self._once_op(start, end)
        # 如果r是False，a,b没有互换
        elif not self.r:
            # 如果b不是时间，调用_once_val_op
            if not self.btime:
                self._once_val_op(start, end)
            # 如果b是时间，调用_once_time_op
            else:
                self._once_time_op(start, end)
        # 如果a,b进行了互换，那么就调用_onve_val_op_r
        else:
            self._once_val_op_r(start, end)

    def _once_op(self, start, end):
        # cache python dictionary lookups
        # a和b都是line的情况下的操作
        dst = self.array
        srca = self.a.array
        srcb = self.b.array
        op = self.operation

        for i in range(start, end):
            dst[i] = op(srca[i], srcb[i])

    def _once_time_op(self, start, end):
        # cache python dictionary lookups
        # a是line，b是时间下的操作
        dst = self.array
        srca = self.a.array
        srcb = self.b
        op = self.operation
        tz = self._tz

        for i in range(start, end):
            dst[i] = op(num2date(srca[i], tz=tz).time(), srcb)

    def _once_val_op(self, start, end):
        # cache python dictionary lookups
        # a是line，b是浮点数的情况下的操作，这里默认了b只能是浮点数，不能是时间
        dst = self.array
        srca = self.a.array
        srcb = self.b
        op = self.operation

        for i in range(start, end):
            dst[i] = op(srca[i], srcb)

    def _once_val_op_r(self, start, end):
        # cache python dictionary lookups
        # 这里对a和b进行了互换，b是line，a是float或者时间，但是代码里面默认了a应该是float，逻辑判断的时候要注意。
        dst = self.array
        srca = self.a
        srcb = self.b.array
        op = self.operation

        for i in range(start, end):
            dst[i] = op(srca, srcb[i])


class LineOwnOperation(LineActions):
    '''
    Holds an operation that operates on a single operand. Example: abs

    It will "next"/traverse the array applying the operation and storing
    the result in self
    '''
    # 对line自身进行操作
    def __init__(self, a, operation):
        super(LineOwnOperation, self).__init__()

        self.operation = operation
        self.a = a

    def next(self):
        # 对line的所有数据进行操作
        self[0] = self.operation(self.a[0])

    def once(self, start, end):
        # cache python dictionary lookups
        # 对line的一部分数据进行操作
        dst = self.array
        srca = self.a.array
        op = self.operation

        for i in range(start, end):
            dst[i] = op(srca[i])
