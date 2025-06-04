#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
module:: linebuffer

Classes that hold the buffer for a *line* and can operate on it
with appending, forwarding, rewinding, resetting and other

module author:: Daniel Rodriguez

"""
import array
import collections
import datetime
from itertools import islice
import math

from .utils.py3 import range, string_types

from .lineroot import LineRoot, LineSingle, LineMultiple
from . import metabase
from .utils import num2date, time2num


NAN = float("NaN")


class LineBuffer(LineSingle):
    """
    LineBuffer defines an interface to an "array.array" (or list) in which
    index 0 points to the item which is active for input and output.

    Positive indices fetch values from the past (left-hand side)
    Negative indices fetch values from the future (if the array has been
    extended on the right-hand side)

    With this behavior, no index has to be passed around to entities which have
    to work with the current value produced by other entities: the value is
    always reachable at "0".

    Likewise, storing the current value produced by "self" is done at 0.

    Additional operations to move the pointer (home, forward, extend, rewind,
    advance getzero) are provided

    The class can also hold "bindings" to other LineBuffers. When a value
    is set in this class,
    it will also be set in the binding.
    """

    # 给LineBuffer定义了属性，他们的值分别为0和1
    UnBounded, QBuffer = (0, 1)

    # 初始化操作
    def __init__(self):
        self.lenmark = None
        self.extrasize = None
        self.maxlen = None
        self.extension = None
        self.lencount = None
        self.useislice = None
        self.array = None
        self._idx = None
        self.lines = [self]  # lines是一个包含自身的列表
        self.mode = self.UnBounded  # self.mode默认值是0
        self.bindings = list()  # self.bindlings默认是一个列表
        self.reset()  # 重置，调用的是自身的reset方法
        self._tz = None  # 时区设置

    # 获取_idx的值
    def get_idx(self):
        return self._idx

    # 设置_idx的值
    def set_idx(self, idx, force=False):
        # If QBuffer and the last position of the buffer were reached, keep
        # it (unless force) as index 0. This allows resampling
        #  - forward adds a position. However, the 1st one is discarded, the 0 is
        #  invariant
        # force supports replaying, which needs the extra bar to float
        # forward/backwards, because the last input is read, and after a
        # "backwards" is used to update the previous data. Unless position
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
        """Resets the internal buffer structure and the indices"""
        # 如果是缓存模式，保存的数据量是一定的，就会使用deque来保存数据，有一个最大的长度，超过这个长度的时候回踢出最前面的数据
        if self.mode == self.QBuffer:
            # Add extrasize to ensure resample/replay work.They will
            # use backwards to erase the last bar/tick before delivering a new
            # bar The previous forward would have discarded the bar "period"
            # times ago, and it will not come back.
            # Having + 1 in the size
            # allows the forward without removing that bar
            self.array = collections.deque(maxlen=self.maxlen + self.extrasize)
            self.useislice = True
        else:
            self.array = array.array(str("d"))
            self.useislice = False
        # 默认最开始的时候lencount等于0,idx等于-1,extension等于0
        self.lencount = 0
        self.idx = -1
        self.extension = 0

    # 设置缓存相关的变量
    def qbuffer(self, savemem=0, extrasize=0):
        self.mode = self.QBuffer  # 设置具体的模式
        self.maxlen = self._minperiod  # 设置最大的长度
        self.extrasize = extrasize  # 设置额外的量
        self.lenmark = self.maxlen - (not self.extrasize)  # 最大长度减去1,如果extrasize=0的话
        self.reset()  # 重置

    # 获取指标值
    def getindicators(self):
        return []

    # 最小缓存
    def minbuffer(self, size):
        """The linebuffer must guarantee the minimum requested size to be
        available.

        In non-dqbuffer mode, this is always true (of course, until data is
        filled at the beginning, there are fewer values, but minperiod in the
        framework should account for this.

        In dqbuffer mode, the buffer has to be adjusted for this if currently
        less than requested
        """
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
        """Real data that can be currently held in the internal buffer

        The internal buffer can be longer than the actual stored data to
        allow for "lookahead" operations. The real amount of data that is
        held/can be held in the buffer
        is returned
        """
        return len(self.array) - self.extension

    # 获取值
    def __getitem__(self, ago):
        try:
            return self.array[self.idx + ago]
        except IndexError:
            # Handle out of bounds access gracefully
            array_len = len(self.array)
            requested_idx = self.idx + ago
            
            # If the array is empty, return NaN
            if array_len == 0:
                return float('nan')
            
            # If requesting beyond the end, return the last available value
            if requested_idx >= array_len:
                return self.array[-1] if array_len > 0 else float('nan')
            
            # If requesting before the beginning, return the first available value
            if requested_idx < 0:
                return self.array[0] if array_len > 0 else float('nan')
            
            # This shouldn't happen, but just in case
            return float('nan')

    # 获取数据的值，在策略中使用还是比较广泛的
    def get(self, ago=0, size=1):
        """Returns a slice of the array relative to *ago*

        Keyword Args:
            ago (int): Point of the array to which size will be added
            to return the slice size(int): size of the slice to return,
            can be positive or negative

        If size is positive *ago* will mark the end of the iterable and vice
        versa if size is negative

        Returns:
            A slice of the underlying buffer
        """
        # 是否使用切片，如果使用按照下面的语法
        if self.useislice:
            start = self.idx + ago - size + 1
            end = self.idx + ago + 1
            return list(islice(self.array, start, end))

        # 如果不使用切片，直接截取
        return self.array[self.idx + ago - size + 1 : self.idx + ago + 1]

    # 返回array真正的0处的变量值
    def getzeroval(self, idx=0):
        """Returns a single value of the array relative to the real zero
        of the buffer

        Keyword Args:
            idx (int): Where to start relative to the real start of the buffer
            size(int): size of the slice to return

        Returns:
            A slice of the underlying buffer
        """
        return self.array[idx]

    # 返回array从idx开始，size个长度的数据
    def getzero(self, idx=0, size=1):
        """Returns a slice of the array relative to the real zero of the buffer

        Keyword Args:
            idx (int): Where to start relative to the real start of the buffer
            size(int): size of the slice to return

        Returns:
            A slice of the underlying buffer
        """
        if self.useislice:
            return list(islice(self.array, idx, idx + size))

        return self.array[idx : idx + size]

    # 给array相关的值
    def __setitem__(self, ago, value):
        """Sets a value at position "ago" and executes any associated bindings

        Keyword Args:
            ago (int): Point of the array to which size will be added to return
            the slice
            value (variable): value to be set
        """
        try:
            self.array[self.idx + ago] = value
        except IndexError:
            # Handle out of bounds access gracefully
            array_len = len(self.array)
            requested_idx = self.idx + ago
            
            # If we're trying to set beyond the end of the array, extend it
            if requested_idx >= array_len:
                # Extend the array to accommodate the new index
                while len(self.array) <= requested_idx:
                    self.array.append(float('nan'))
                self.array[requested_idx] = value
            # If we're trying to set before the beginning, ignore it
            elif requested_idx < 0:
                # Cannot set before the beginning of the array
                pass
            else:
                # This shouldn't happen, but just in case
                pass
        
        # Execute bindings if the set was successful
        for binding in self.bindings:
            try:
                binding[ago] = value
            except (IndexError, AttributeError):
                # If binding fails, continue with other bindings
                pass

    # 给array设置具体的值
    def set(self, value, ago=0):
        """Sets a value at position "ago" and executes any associated bindings

        Keyword Args:
            value (variable): value to be set
            ago (int): Point of the array to which size will be added to return
            the slice
        """
        try:
            self.array[self.idx + ago] = value
        except IndexError:
            # Handle out of bounds access gracefully
            array_len = len(self.array)
            requested_idx = self.idx + ago
            
            # If we're trying to set beyond the end of the array, extend it
            if requested_idx >= array_len:
                # Extend the array to accommodate the new index
                while len(self.array) <= requested_idx:
                    self.array.append(float('nan'))
                self.array[requested_idx] = value
            # If we're trying to set before the beginning, ignore it
            elif requested_idx < 0:
                # Cannot set before the beginning of the array
                pass
            else:
                # This shouldn't happen, but just in case
                pass
        
        # Execute bindings if the set was successful
        for binding in self.bindings:
            try:
                binding[ago] = value
            except (IndexError, AttributeError):
                # If binding fails, continue with other bindings
                pass

    # 返回到最开始
    def home(self):
        """Rewinds the logical index to the beginning

        The underlying buffer remains untouched and the actual len can be found
        out with buflen
        """
        self.idx = -1
        self.lencount = 0

    # 向前移动一位
    def forward(self, value=NAN, size=1):
        """Moves the logical index foward and enlarges the buffer as much as needed

        Keyword Args:
            value (variable): value to be set in new positins
            size (int): How many extra positions to enlarge the buffer
        """
        self.idx += size
        self.lencount += size

        for i in range(size):
            self.array.append(value)

    # 向后移动一位
    def backwards(self, size=1, force=False):
        """Moves the logical index backwards and reduces the buffer as much as needed

        Keyword Args:
            size (int): How many extra positions to rewind and reduce the
            buffer
        """
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
        """Advances the logical index without touching the underlying buffer

        Keyword Args:
            size (int): How many extra positions to move forward
        """
        self.idx += size
        self.lencount += size

    # 向前扩展
    def extend(self, value=NAN, size=0):
        """Extends the underlying array with positions that the index will not reach

        Keyword Args:
            value (variable): value to be set in new positins
            size (int): How many extra positions to enlarge the buffer

        The purpose is to allow for lookahead operations or to be able to
        set values in the buffer "future"
        """
        self.extension += size
        for i in range(size):
            self.array.append(value)

    # 增加另一条LineBuffer
    def addbinding(self, binding):
        """Adds another line binding

        Keyword Args:
            binding (LineBuffer): another line that must be set when this line
            becomes a value
        """
        self.bindings.append(binding)
        # record in the binding when the period is starting (never sooner
        # than self)
        binding.updateminperiod(self._minperiod)

    # 获取从idx开始的全部数据
    def plot(self, idx=0, size=None):
        """Returns a slice of the array relative to the real zero of the buffer

        Keyword Args:
            idx (int): Where to start relative to the real start of the buffer
            size(int): size of the slice to return

        This is a variant of getzero that unless told otherwise returns the
        entire buffer, which is usually the idea behind plottint (all must
        be plotted)

        Returns:
            A slice of the underlying buffer
        """
        return self.getzero(idx, size or len(self))

    # 获取array的部分数据
    def plotrange(self, start, end):
        if self.useislice:
            return list(islice(self.array, start, end))

        return self.array[start:end]

    # 在once的时候，给每个binding设置array的变量
    def oncebinding(self):
        """
        Executes the bindings when running in "once" mode
        """
        larray = self.array
        blen = self.buflen()
        for binding in self.bindings:
            binding.array[0:blen] = larray[0:blen]

    # 把blinding转变成line
    def bind2lines(self, binding=0):
        """
        Stores a binding to another line. "Binding" can be an index or a name
        """
        if isinstance(binding, string_types):
            line = getattr(self._owner.lines, binding)
        else:
            line = self._owner.lines[binding]

        self.addbinding(line)

        return self

    bind2line = bind2lines

    def __call__(self, ago=None):
        """Returns either the current value (ago=None) or a delayed LineBuffer
        that fetches the value which is "ago" periods before. Useful to have
        the closing price 5 bars before: close(-5)
        """
        if ago is None:
            return self[0]
        return LineDelay(self, ago)

    def _makeoperation(self, other, operation, r=False, _ownerskip=None):
        return LinesOperation(self, other, operation, r=r)

    def _makeoperationown(self, operation, _ownerskip=None):
        return LineOwnOperation(self, operation)

    def _settz(self, tz):
        self._tz = tz

    def datetime(self, ago=0, tz=None, naive=True):
        return num2date(self[ago], tz or self._tz, naive)

    def date(self, ago=0, tz=None, naive=True):
        return num2date(self[ago], tz or self._tz, naive).date()

    def time(self, ago=0, tz=None, naive=True):
        return num2date(self[ago], tz or self._tz, naive).time()

    def dt(self, ago=0):
        """Alias to avoid the extra chars in "datetime" for this field"""
        return self.datetime(ago)

    def tm_raw(self, ago=0):
        """
        Returns a localtime/gmtime like time.struct_time object which is
        compatible with strftime formatting.

        The time zone of the struct_time is naive
        """
        return self.datetime(ago, naive=False).timetuple()

    def tm(self, ago=0):
        """
        Returns a localtime/gmtime like time.struct_time object which is
        compatible with strftime formatting.

        The time zone of the struct_time is naive
        """
        return self.datetime(ago, naive=True).timetuple()

    def tm_lt(self, other, ago=0):
        """
        Returns True if the time carried by this line's index "ago" is
        lower than the time carried by the "other" line
        """
        return self[ago] < other[0]

    def tm_le(self, other, ago=0):
        """
        Returns True if the time carried by this line's index "ago" is
        lower than or equal to the time carried by the "other" line
        """
        return self[ago] <= other[0]

    def tm_eq(self, other, ago=0):
        """
        Returns True if the time carried by this line's index "ago" is
        equal to the time carried by the "other" line
        """
        return self[ago] == other[0]

    def tm_gt(self, other, ago=0):
        """
        Returns True if the time carried by this line's index "ago" is
        greater than the time carried by the "other" line
        """
        return self[ago] > other[0]

    def tm_ge(self, other, ago=0):
        """
        Returns True if the time carried by this line's index "ago" is
        greater than or equal to the time carried by the "other" line
        """
        return self[ago] >= other[0]

    def tm2dtime(self, tm, ago=0):
        """
        Returns the passed tm (time.struct_time) in a datetime using the
        timezone (if any) of the line
        """
        return datetime.datetime(*tm[:6])

    def tm2datetime(self, tm, ago=0):
        """
        Returns the passed tm (time.struct_time) in a datetime using the
        timezone (if any) of the line
        """
        return datetime.datetime(*tm[:6])


# LineActions cache for performance
class LineActionsCache:
    """Cache system for LineActions to avoid repetitive calculations"""
    _cache = {}
    _cache_enabled = False

    @classmethod
    def enable_cache(cls, enable=True):
        cls._cache_enabled = enable

    @classmethod
    def clear_cache(cls):
        cls._cache.clear()

    @classmethod
    def get_cache_key(cls, *args):
        """Generate cache key from arguments"""
        return hash(tuple(id(arg) if hasattr(arg, '__hash__') else str(arg) for arg in args))


class LineActionsMixin:
    """Mixin to provide LineActions functionality without metaclass"""
    
    @classmethod
    def dopreinit(cls, _obj, *args, **kwargs):
        """Pre-initialization processing for LineActions"""
        # Calculate minperiod based on LineBuffer instances
        mindatas = 0
        minperstatus = MAXINT = 2 ** 31 - 1
        
        # Scan class members for LineBuffer instances
        for membername in dir(_obj):
            member = getattr(_obj, membername)
            if isinstance(member, (LineBuffer, LineSingle)):
                mindatas += 1
                if hasattr(member, '_minperiod'):
                    minperstatus = min(minperstatus, member._minperiod)
        
        # Set calculated minperiod
        if minperstatus != MAXINT:
            _obj._minperiod = minperstatus
        else:
            _obj._minperiod = max(mindatas, 1)
        
        return _obj, args, kwargs
    
    @classmethod
    def dopostinit(cls, _obj, *args, **kwargs):
        """Post-initialization processing for LineActions"""
        # Register with owner if available
        if hasattr(_obj, '_owner') and _obj._owner is not None:
            if hasattr(_obj._owner, 'addindicator'):
                _obj._owner.addindicator(_obj)
        
        return _obj, args, kwargs


class PseudoArray(object):
    def __init__(self, wrapped):
        self.wrapped = wrapped

    def __getitem__(self, key):
        return self.wrapped[key]

    @property
    def array(self):
        return self.wrapped.array


class LineActions(LineBuffer, LineActionsMixin, metabase.BaseMixin):
    '''
    Base class for *Line Clases* with different lines, derived from a
    LineBuffer
    '''
    
    _ltype = LineBuffer.IndType

    def getindicators(self):
        return []

    def qbuffer(self, savemem=0):
        super(LineActions, self).qbuffer(savemem=1)

    @staticmethod
    def arrayize(obj):
        if not hasattr(obj, "array"):
            if not hasattr(obj, "__getitem__"):
                return LineNum(obj)  # make it a LineNum
            if not hasattr(obj, "__len__"):
                return PseudoArray(obj)  # Can iterate (for once)

        return obj

    def _next(self):
        clock_len = len(self._clock)
        if clock_len > len(self):
            self.forward()

        if clock_len > self._minperiod:
            try:
                self.next()
            except StopIteration:
                self._clock._stop()

    def _once(self):
        self.forward(size=self._clock.buflen())
        self.home()

        start = self._minperiod - 1
        end = start + len(self._clock)
        self.once(start, end)

        self.home()
        self.advance(size=len(self._clock))
    
    @classmethod
    def cleancache(cls):
        """Clean the cache - called by cerebro"""
        LineActionsCache.clear_cache()
    
    @classmethod
    def usecache(cls, enable=True):
        """Enable or disable the cache"""
        LineActionsCache.enable_cache(enable)


def LineDelay(a, ago=0, **kwargs):
    if ago <= 0:
        return _LineDelay(a, ago, **kwargs)

    return _LineForward(a, ago)


def LineNum(num):
    return _LineDelay(PseudoArray(math.repeat(num)), 0)


class _LineDelay(LineActions):
    def __init__(self, a, ago):
        super(_LineDelay, self).__init__()
        self.a = self.arrayize(a)
        self.ago = ago

        # Need to add the delay to the period
        if hasattr(a, '_minperiod'):
            self.addminperiod(abs(ago))

    def next(self):
        self.lines[0][0] = self.a[self.ago]

    def once(self, start, end):
        # cache python dictionary lookups
        dst = self.lines[0].array
        src = self.a.array
        ago = self.ago

        for i in range(start, end):
            dst[i] = src[i + ago]


class _LineForward(LineActions):
    def __init__(self, a, ago):
        super(_LineForward, self).__init__()
        self.a = self.arrayize(a)
        self.ago = ago

        # Need to add the delay to the period
        if hasattr(a, '_minperiod'):
            self.addminperiod(ago)

    def next(self):
        self[0] = self.a[-self.ago]

    def once(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        src = self.a.array
        ago = self.ago

        for i in range(start, end):
            dst[i] = src[i - ago]


class LinesOperation(LineActions):
    def __init__(self, a, b, operation, r=False):
        super(LinesOperation, self).__init__()
        self.operation = operation
        self.a = a  # always a linebuffer-like object
        self.b = self.arrayize(b)
        self.r = r

        # ensure a is added if it's a lineiterator-like object
        # self.addminperiod(1) already done by the base class
        self.addminperiod(getattr(a, '_minperiod', 1))
        self.addminperiod(getattr(b, '_minperiod', 1))

    def next(self):
        # operation(float, other) ... expecting other to be a float
        if self.r:
            self[0] = self.operation(self.b[0], self.a[0])
        else:
            self[0] = self.operation(self.a[0], self.b[0])

    def once(self, start, end):
        if hasattr(self.b, 'array'):
            self._once_op(start, end)
        else:
            if isinstance(self.b, float):
                self._once_val_op_r(start, end) if self.r else self._once_val_op(start, end)
            else:
                self._once_time_op(start, end)

    def _once_op(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b.array
        op = self.operation

        for i in range(start, end):
            if self.r:
                dst[i] = op(srcb[i], srca[i])
            else:
                dst[i] = op(srca[i], srcb[i])

    def _once_time_op(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b[0]
        op = self.operation

        for i in range(start, end):
            if self.r:
                dst[i] = op(srcb, srca[i])
            else:
                dst[i] = op(srca[i], srcb)

    def _once_val_op(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b
        op = self.operation

        for i in range(start, end):
            dst[i] = op(srca[i], srcb)

    def _once_val_op_r(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b
        op = self.operation

        for i in range(start, end):
            dst[i] = op(srcb, srca[i])


class LineOwnOperation(LineActions):
    def __init__(self, a, operation):
        super(LineOwnOperation, self).__init__()
        self.operation = operation
        self.a = a

        self.addminperiod(getattr(a, '_minperiod', 1))

    def next(self):
        self[0] = self.operation(self.a[0])

    def once(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        op = self.operation

        for i in range(start, end):
            dst[i] = op(srca[i])
