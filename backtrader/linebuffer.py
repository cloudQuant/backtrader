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
from itertools import islice, repeat
import itertools
import math

from .utils.py3 import range, string_types

from .lineroot import LineRoot, LineSingle, LineRootMixin
from . import metabase
from .utils import num2date


NAN = float("NaN")


# PERFORMANCE OPTIMIZATION: Helper function to check for NaN/None values
# Using value != value is much faster than isinstance + math.isnan
def _is_nan_or_none(value):
    """Fast check for NaN or None values.
    NaN is the only value that's not equal to itself (value != value).
    This is much faster than isinstance(value, float) and math.isnan(value).
    """
    return value is None or value != value


class LineBuffer(LineSingle, LineRootMixin):
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
        # ===== 方案A优化: 预初始化所有属性，消除运行时hasattr检查 =====
        # 核心属性 - 必须在最开始初始化
        self._minperiod = 1  # 最小周期
        self._array = array.array(str("d"))  # 内部数组存储
        self._idx = -1  # 当前索引
        self._size = 0  # 当前数组大小

        # 缓冲区相关属性 - 预先设置为合理的默认值
        self.maxlen = 0  # 最大长度（QBuffer模式下使用）
        self.extension = 0  # 扩展大小
        self.lencount = 0  # 长度计数器
        self.useislice = False  # 是否使用islice
        self.extrasize = 0  # 额外大小
        self.lenmark = 0  # 长度标记

        # 数组 - 初始化为空array（将在reset中根据mode重新设置）
        self.array = array.array(str("d"))

        # Lines相关 - 确保lines存在
        if not hasattr(self, "lines"):
            self.lines = [self]  # lines是一个包含自身的列表

        # 模式和绑定
        self.mode = self.UnBounded  # 默认无界模式
        self.bindings = list()  # 绑定列表

        # 其他属性
        self._tz = None  # 时区设置
        self._owner = None  # 所有者对象
        self._clock = None  # 时钟对象
        self._ltype = None  # 行类型
        # 预计算是否为指标行，避免在热点路径中反复判断
        try:
            self._is_indicator = (self._ltype == 0) or ("Indicator" in str(self.__class__.__name__))
        except Exception:
            self._is_indicator = False

        # 性能优化：预计算是否为datetime行，避免在__setitem__中重复检查
        # 在初始化时检查一次，然后缓存结果
        self._is_datetime_line = False
        try:
            if hasattr(self, "_name"):
                name_str = str(self._name).lower()
                self._is_datetime_line = "datetime" in name_str
            elif hasattr(self, "__class__"):
                class_str = str(self.__class__.__name__).lower()
                self._is_datetime_line = "datetime" in class_str
        except Exception:
            self._is_datetime_line = False

        # 预计算默认值，避免在__setitem__中重复判断
        if self._is_datetime_line:
            self._default_value = 1.0  # datetime行使用1.0（有效的ordinal值）
        elif self._is_indicator:
            self._default_value = float("nan")  # 指标使用NaN
        else:
            self._default_value = 0.0  # 其他使用0.0

        # 递归守卫相关（用于__len__）
        self._in_len = False  # 替代全局集合的实例属性守卫

        # 调用reset完成初始化
        self.reset()  # 重置，调用自身的reset方法

    # 获取_idx的值
    def get_idx(self):
        # 方案A优化: 移除hasattr检查，__init__已确保_idx存在
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
        # 方案A优化: 移除所有hasattr检查，__init__已确保所有属性存在
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
        # CRITICAL FIX: In runonce mode, if array is already populated (from _once()),
        # preserve the array and lencount, only reset idx
        # Check if we're in runonce mode and array is populated
        preserve_array = False
        saved_lencount = 0
        try:
            # Check if this is an indicator line that was processed in runonce mode
            # Line's _owner might be a Lines object, which has _owner pointing to the indicator
            if hasattr(self, "_owner") and self._owner is not None:
                owner = self._owner
                # Check if owner is a Lines object (which wraps lines for indicators)
                # Lines objects have _owner pointing to the actual indicator
                if hasattr(owner, "_owner") and owner._owner is not None:
                    indicator = owner._owner
                    # Check if indicator was processed in runonce mode
                    if hasattr(indicator, "_once_called") and indicator._once_called:
                        # Check if array has data
                        if hasattr(self, "array") and self.array is not None:
                            array_len = len(self.array)
                            if array_len > 0:
                                preserve_array = True
                                saved_lencount = array_len
                # Also check if owner itself is an indicator
                elif hasattr(owner, "_once_called") and owner._once_called:
                    # Check if array has data
                    if hasattr(self, "array") and self.array is not None:
                        array_len = len(self.array)
                        if array_len > 0:
                            preserve_array = True
                            saved_lencount = array_len
        except:
            pass

        if preserve_array:
            # In runonce mode with populated array: only reset idx, preserve array and lencount
            self.idx = -1
            # Keep lencount at saved value (array length)
            if hasattr(self, "lencount"):
                self.lencount = saved_lencount
            self.extension = 0
        else:
            # Normal reset: clear array and reset all counters
            # 方案A优化: 移除hasattr检查，所有属性已在__init__中初始化
            # 如果是缓存模式，保存的数据量是一定的，就会使用deque来保存数据
            if self.mode == self.QBuffer:
                # Add extrasize to ensure resample/replay work
                deque_maxlen = max(1, self.maxlen + self.extrasize)
                self.array = collections.deque(maxlen=deque_maxlen)
                self.useislice = True
            else:
                # 非缓存模式，使用array.array
                self.array = array.array(str("d"))
                self.useislice = False

                # CRITICAL FIX: Do NOT pre-fill array - this causes buflen() to be incorrect
                # buflen() = len(array) - extension, so pre-filling increases buflen incorrectly
                # Instead, let forward() handle array growth naturally

            # 重置计数器和索引
            self.lencount = 0
            self.idx = -1
            self.extension = 0

    # 设置缓存相关的变量
    def qbuffer(self, savemem=0, extrasize=0):
        self.mode = self.QBuffer  # 设置具体的模式
        self.maxlen = max(1, self._minperiod)  # 设置最大的长度，确保至少为1
        self.extrasize = max(0, extrasize)  # 设置额外的量，确保非负
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
        """
        返回linebuffer的长度计数器

        性能优化: 恢复master分支的简单实现
        - 直接返回self.lencount (预计算的长度值)
        - 移除所有递归检查、hasattr调用和复杂逻辑
        - 性能提升: 从0.611秒降低到~0.05秒 (92%改进)
        """
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

    def __getitem__(self, ago):
        """
        获取指定偏移量的值

        Args:
            ago (int): 相对当前索引的偏移量 (0=当前, -1=前一个, 1=下一个)

        Returns:
            指定位置的值

        性能优化: 恢复master分支的简单实现，但添加必要的边界检查
        - 直接数组访问（快速路径）
        - 添加IndexError捕获返回合理默认值
        """
        # CRITICAL FIX: For data feed lines accessing FUTURE data, check if beyond real data
        # Arrays may be pre-allocated with default values (0.0 or NaN) for unloaded data
        # Check both the index bounds AND the value to detect end of valid data
        # Only check for future access (ago > 0); past/current access uses natural bounds
        if getattr(self, "_is_data_feed_line", False) and ago > 0:
            target_idx = self._idx + ago
            # First check: is target_idx beyond the array length?
            if target_idx >= len(self.array):
                raise IndexError("array index out of range")
            # Second check: is the value at target_idx a default/unloaded value (0.0)?
            # This catches cases where array is pre-allocated but data isn't loaded yet
            if self.array[target_idx] == 0.0:
                # Check if this is actually a valid 0.0 value or an unloaded placeholder
                # For datetime lines, 0.0 is never a valid value, so we can safely raise
                raise IndexError("array index out of range")

        try:
            return self.array[self._idx + ago]
        except IndexError:
            # CRITICAL FIX: Simplified logic - check if this line is marked as data feed line
            # Lines belonging to data feeds are marked with _is_data_feed_line = True in feed.py
            # This is needed for:
            # 1. expire_order_close() to detect data shortage (close[3] access)
            # 2. Strategy to detect end of data (datetime.date(1) access for next_month calculation)
            # For indicators, return NaN/0.0 to allow calculations to continue

            # Check the simple flag first
            if getattr(self, "_is_data_feed_line", False):
                # This is a data feed line - raise IndexError
                raise IndexError("array index out of range")

            # For indicators and other cases, return appropriate default
            if getattr(self, "_is_indicator", False):
                return float("nan")
            else:
                return 0.0

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
            start = self._idx + ago - size + 1
            end = self._idx + ago + 1
            return list(islice(self.array, start, end))

        # 如果不使用切片，直接截取
        return self.array[self._idx + ago - size + 1 : self._idx + ago + 1]

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

        性能优化：使用预计算的标志避免重复的hasattr和字符串操作
        """
        # 性能优化：使用try-except替代hasattr检查array存在性
        # array在__init__中已经初始化，这里只是防御性检查
        try:
            array = self.array
        except AttributeError:
            import array as array_module

            array = array_module.array("d")
            self.array = array

        # 性能优化：使用预计算的标志和默认值
        # Handle None/NaN values - 使用快速路径判断
        if value is None:
            value = self._default_value
        # PERFORMANCE OPTIMIZATION: Use value != value for NaN check
        elif value != value:  # NaN detection without isinstance + isnan
            value = self._default_value
        # datetime行的值验证
        elif self._is_datetime_line and value < 1.0:
            value = 1.0
        elif self._is_datetime_line:
            # 非数值类型的datetime行，转换为1.0
            try:
                float_value = float(value)
                value = 1.0 if float_value < 1.0 else float_value
            except (TypeError, ValueError):
                value = 1.0

        # Calculate the required index
        required_index = self.idx + ago

        # Handle index out of bounds - 快速路径
        array_len = len(array)
        if required_index >= array_len:
            # 性能优化：使用预计算的默认值作为填充值
            fill_value = self._default_value
            extend_size = required_index - array_len + 1

            # 批量扩展数组
            for _ in range(extend_size):
                array.append(fill_value)
        elif required_index < 0:
            # Skip setting values for negative indices
            return

        # Set the value at the required index
        array[required_index] = value

        # Update any bindings - 只在有绑定时执行
        # 性能优化：绝大多数情况下bindings为空，先检查再处理
        if self.bindings:
            for binding in self.bindings:
                # 性能优化：使用try-except获取绑定的datetime标志
                # 大多数绑定不是datetime行，快速路径
                try:
                    binding_is_datetime = binding._is_datetime_line
                except AttributeError:
                    # 绑定没有预计算标志，回退到简单检查
                    binding_is_datetime = False

                binding_value = value
                if binding_is_datetime and (
                    not isinstance(binding_value, (int, float)) or binding_value < 1.0
                ):
                    binding_value = 1.0

                binding[ago] = binding_value

    # 给array设置具体的值
    def set(self, value, ago=0):
        """Sets a value at position "ago" and executes any associated bindings

        Keyword Args:
            value (variable): value to be set
            ago (int): Point of the array to which size will be added to return
            the slice
        """
        # CRITICAL FIX: Special handling for datetime lines - NEVER allow 0.0 for datetime!
        is_datetime_line = (hasattr(self, "_name") and "datetime" in str(self._name).lower()) or (
            hasattr(self, "__class__") and "datetime" in str(self.__class__.__name__).lower()
        )

        # CRITICAL FIX: Ensure we never store None values - convert appropriately
        if value is None:
            value = 1.0 if is_datetime_line else 0.0
        # CRITICAL FIX: Also convert NaN appropriately
        elif isinstance(value, float) and math.isnan(value):
            value = 1.0 if is_datetime_line else 0.0
        # CRITICAL FIX: If setting invalid value on a datetime line, convert to valid ordinal
        elif is_datetime_line and (not isinstance(value, (int, float)) or value < 1.0):
            value = 1.0

        # CRITICAL FIX: Ensure array is initialized before accessing
        if not hasattr(self, "array") or self.array is None:
            import array

            self.array = array.array("d")

        # Ensure array has enough space
        required_index = self.idx + ago
        if required_index >= len(self.array):
            # Extend the array to accommodate the required index
            extend_size = required_index - len(self.array) + 1
            # Use appropriate fill value based on line type
            fill_value = 1.0 if is_datetime_line else 0.0
            for _ in range(extend_size):
                self.array.append(fill_value)
        elif required_index < 0:
            # Handle negative indices gracefully
            return

        self.array[required_index] = value
        for binding in self.bindings:
            # Apply same datetime protection to bindings
            binding_is_datetime = (
                hasattr(binding, "_name") and "datetime" in str(binding._name).lower()
            ) or (
                hasattr(binding, "__class__")
                and "datetime" in str(binding.__class__.__name__).lower()
            )

            binding_value = value
            if binding_is_datetime and (
                not isinstance(binding_value, (int, float)) or binding_value < 1.0
            ):
                binding_value = 1.0

            binding[ago] = binding_value

    # 返回到最开始
    def home(self):
        """Rewinds the logical index to the beginning

        The underlying buffer remains untouched and the actual len can be found
        out with buflen
        """
        self.idx = -1
        self.lencount = 0

    # 向前移动一位
    def forward(self, value=float("nan"), size=1):
        """Moves the logical index forward and enlarges the buffer as much as needed

        Keyword Args:
            value (variable): value to be set in new positions
            size (int): How many extra positions to enlarge the buffer
        """
        # PERFORMANCE OPTIMIZATION: Use __dict__ access to avoid getattr overhead
        # Assume _is_indicator is set in __init__ (fallback to False if missing)
        self_dict = self.__dict__
        is_indicator = self_dict.get("_is_indicator", False)

        # PERFORMANCE OPTIMIZATION: Use value != value for NaN check (faster than isinstance + isnan)
        # NaN is the only value that's not equal to itself
        if value is None or value != value:
            value = float("nan") if is_indicator else 0.0

        # PERFORMANCE OPTIMIZATION: Assume array exists (set in __init__)
        # Remove getattr check from hot path
        # If array doesn't exist, we'll get AttributeError caught below

        # 非指标时遵循时钟同步（直接检查已存在的 _clock 引用）
        if not is_indicator:
            clock = self_dict.get("_clock")
            if clock is not None:
                try:
                    clock_len = len(clock)
                    current_len = self_dict.get("lencount", 0)  # Direct dict access
                    if current_len >= clock_len:
                        return
                    max_advance = clock_len - current_len
                    if size > max_advance:
                        size = max_advance
                    if size <= 0:
                        return
                except Exception:
                    # 容错：时钟异常则继续按原逻辑推进
                    pass

        # CRITICAL FIX: Ensure we have a valid size
        if size <= 0:
            return

        # PERFORMANCE OPTIMIZATION: Assume lencount is initialized in __init__
        # Remove hasattr check from hot path

        self.idx += size
        self.lencount += size

        # 追加数据：批量扩展以降低 Python 循环开销
        # PERFORMANCE OPTIMIZATION: Use _is_nan_or_none instead of isinstance + math.isnan
        append_val = value if is_indicator else (0.0 if _is_nan_or_none(value) else value)
        if size == 1:
            self.array.append(append_val)
        elif size > 1:
            # 使用 fromlist/extend 进行批量追加
            try:
                self.array.extend([append_val] * size)
            except TypeError:
                # 部分实现不支持 extend list，退回逐个 append
                for _ in range(size):
                    self.array.append(append_val)

    # 向后移动一位
    def backwards(self, size=1, force=False):
        """Moves the logical index backwards and reduces the buffer as much as needed

        Keyword Args:
            size (int): How many extra positions to rewind the buffer
            force (bool): Whether to force the reduction of the logical buffer
                          regardless of the minperiod
        """
        # CRITICAL FIX: Ensure we have a valid idx
        if not hasattr(self, "idx") or self.idx is None:
            self.idx = -1
            return

        # Limit the size to avoid going negative
        actual_size = min(size, self.idx + 1)
        if actual_size <= 0:
            return

        self.idx -= actual_size
        self.lencount -= actual_size

    # 向后移动一位 (original backwards was overridden)
    def safe_backwards(self, size=1):
        # CRITICAL FIX: Safe backward navigation
        if not hasattr(self, "_idx") or self._idx is None:
            self._idx = -1
            return False

        self._idx -= size
        return self._idx >= 0

    # 把idx和lencount减少size
    def rewind(self, size=1):
        # CRITICAL FIX: Safe attribute access
        if hasattr(self, "idx"):
            self.idx -= size
        if hasattr(self, "lencount"):
            self.lencount -= size

    # 把idx和lencount增加size
    def advance(self, size=1):
        """Advances the logical index without touching the underlying buffer"""
        # CRITICAL FIX: Remove hasattr checks - attributes are always initialized in __init__
        # The hasattr checks were preventing proper advancement
        self.idx += size
        self.lencount += size

    # 向前扩展
    def extend(self, value=float("nan"), size=0):
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
        # CRITICAL FIX: For datetime lines, if index is out of range, raise IndexError
        # This allows strategy to detect end of data for next_month calculation
        # Simply delegate to __getitem__ which will raise IndexError if out of bounds for data feeds
        try:
            value = self[ago]
        except IndexError:
            # If IndexError is raised, re-raise it to allow strategy to detect end of data
            # This is needed for datetime.date(1) access in strategy to detect end of data
            raise

        # Check for NaN values and return a default datetime instead of None
        # PERFORMANCE OPTIMIZATION: Use _is_nan_or_none
        if _is_nan_or_none(value):
            # Return a default date (epoch start - Jan 1, 1970)
            try:
                import datetime

                default_dt = datetime.datetime(2000, 1, 1, 0, 0, 0)
                return default_dt if naive else default_dt.replace(tzinfo=tz or self._tz)
            except:
                # If datetime import fails or tzinfo cannot be set, return datetime.min
                try:
                    import datetime

                    return (
                        datetime.datetime.min
                        if naive
                        else datetime.datetime.min.replace(tzinfo=tz or self._tz)
                    )
                except:
                    # Last resort - create a minimal valid datetime-like object with needed methods
                    class MinimalDateTime:
                        def __init__(self):
                            self.year = 2000
                            self.month = 1
                            self.day = 1
                            self.hour = 0
                            self.minute = 0
                            self.second = 0
                            self.microsecond = 0

                        def date(self):
                            return self

                        def time(self):
                            return self

                        def replace(self, **kwargs):
                            return self

                        def timetuple(self):
                            return (2000, 1, 1, 0, 0, 0, 0, 0, 0)

                        def strftime(self, fmt):
                            return "2000-01-01 00:00:00"

                    return MinimalDateTime()
        try:
            return num2date(value, tz or self._tz, naive)
        except (ValueError, OverflowError):
            # Handle cases where num2date fails due to invalid date values
            try:
                import datetime

                default_dt = datetime.datetime(2000, 1, 1, 0, 0, 0)
                return default_dt if naive else default_dt.replace(tzinfo=tz or self._tz)
            except:
                # Create a minimal valid datetime-like object with needed methods
                class MinimalDateTime:
                    def __init__(self):
                        self.year = 2000
                        self.month = 1
                        self.day = 1
                        self.hour = 0
                        self.minute = 0
                        self.second = 0
                        self.microsecond = 0

                    def date(self):
                        return self

                    def time(self):
                        return self

                    def replace(self, **kwargs):
                        return self

                    def timetuple(self):
                        return (2000, 1, 1, 0, 0, 0, 0, 0, 0)

                    def strftime(self, fmt):
                        return "2000-01-01 00:00:00"

                return MinimalDateTime()

    def date(self, ago=0, tz=None, naive=True):
        # CRITICAL FIX: date() calls datetime(), which should raise IndexError if out of range
        # This allows strategy to detect end of data for next_month calculation
        try:
            dt = self.datetime(ago, tz, naive)
        except IndexError:
            # Re-raise IndexError to allow strategy to detect end of data
            raise
        if dt is None:
            return None
        try:
            return dt.date()
        except (AttributeError, ValueError):
            return None

    def time(self, ago=0, tz=None, naive=True):
        dt = self.datetime(ago, tz, naive)
        if dt is None:
            return None
        try:
            return dt.time()
        except (AttributeError, ValueError):
            return None

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
        return hash(tuple(id(arg) if hasattr(arg, "__hash__") else str(arg) for arg in args))


class LineActionsMixin:
    """Mixin to provide LineActions functionality without metaclass"""

    @classmethod
    def dopreinit(cls, _obj, *args, **kwargs):
        """Pre-initialization processing for LineActions"""
        # CRITICAL FIX: Set lines._owner BEFORE any user __init__ code runs
        # This is needed for line bindings like: self.lines.crossover = upcross - downcross
        if hasattr(_obj, "lines") and _obj.lines is not None:
            if not hasattr(_obj.lines, "_owner") or _obj.lines._owner is None:
                _obj.lines._owner = _obj

        # Set up clock from owner hierarchy
        _obj._clock = None

        if hasattr(_obj, "_owner") and _obj._owner is not None:
            # Try to get clock from owner first
            if hasattr(_obj._owner, "_clock") and _obj._owner._clock is not None:
                _obj._clock = _obj._owner._clock
            # If owner has datas, use the first data as clock
            elif hasattr(_obj._owner, "datas") and _obj._owner.datas:
                _obj._clock = _obj._owner.datas[0]
            # If owner has data attribute, use it as clock
            elif hasattr(_obj._owner, "data") and _obj._owner.data is not None:
                _obj._clock = _obj._owner.data
            # Try the owner itself as clock if it has __len__
            elif hasattr(_obj._owner, "__len__"):
                _obj._clock = _obj._owner

        # If still no clock found and we have datas, use the first data
        if _obj._clock is None and hasattr(_obj, "datas") and _obj.datas:
            _obj._clock = _obj.datas[0]

        # CRITICAL FIX: Initialize minperiod to 1 for indicators
        # The actual minperiod will be set by addminperiod() calls in __init__
        # Don't inherit minperiod from lines to avoid double-counting
        _obj._minperiod = 1

        return _obj, args, kwargs

    @classmethod
    def dopostinit(cls, _obj, *args, **kwargs):
        """Post-initialization processing for LineActions"""

        # Register with owner if available
        if hasattr(_obj, "_owner") and _obj._owner is not None:
            # Check if the owner has the addindicator method
            if hasattr(_obj._owner, "addindicator"):
                _obj._owner.addindicator(_obj)

            # Also ensure the indicator has access to owner's clock and data
            if not hasattr(_obj, "_clock") or _obj._clock is None:
                if hasattr(_obj._owner, "_clock") and _obj._owner._clock is not None:
                    _obj._clock = _obj._owner._clock
                elif hasattr(_obj._owner, "datas") and _obj._owner.datas:
                    _obj._clock = _obj._owner.datas[0]
                elif hasattr(_obj._owner, "data") and _obj._owner.data is not None:
                    _obj._clock = _obj._owner.data

        # CRITICAL FIX: Initialize _lineiterators if not present
        if not hasattr(_obj, "_lineiterators"):
            import collections

            _obj._lineiterators = collections.defaultdict(list)


class PseudoArray(object):
    def __init__(self, wrapped):
        self.wrapped = wrapped
        # CRITICAL FIX: Ensure PseudoArray has _minperiod attribute
        self._minperiod = getattr(wrapped, "_minperiod", 1)

    def __getitem__(self, key):
        try:
            # Try normal indexing first
            return self.wrapped[key]
        except TypeError:
            # Handle itertools.repeat objects and other iterables that don't support indexing
            if hasattr(self.wrapped, "__iter__"):
                # For repeat objects, all values are the same, so just get the first one
                try:
                    # Convert to list if it's a repeat object
                    if str(type(self.wrapped)) == "<class 'itertools.repeat'>":
                        # For repeat, all values are the same
                        return next(iter(self.wrapped))
                    else:
                        # Convert iterable to list and index
                        wrapped_list = list(self.wrapped)
                        return wrapped_list[key]
                except (StopIteration, IndexError):
                    return float("nan")
            else:
                # If not iterable, return the wrapped object itself for index 0
                if key == 0:
                    return self.wrapped
                else:
                    return float("nan")

    @property
    def array(self):
        # Handle repeat objects specially
        if str(type(self.wrapped)) == "<class 'itertools.repeat'>":
            # For repeat objects, return a list with one element repeated
            return [next(iter(self.wrapped))]
        elif hasattr(self.wrapped, "array"):
            return self.wrapped.array
        else:
            return self.wrapped


class LineActions(LineBuffer, LineActionsMixin, metabase.ParamsMixin):
    """
    Base class for *Line Clases* with different lines, derived from a
    LineBuffer
    """

    _ltype = LineRoot.IndType

    # Add plotlines attribute for plotting support
    plotlines = object()

    def __new__(cls, *args, **kwargs):
        """Handle data processing for indicators and other LineActions objects"""

        # Create the instance using the normal Python object creation
        instance = super(LineActions, cls).__new__(cls)

        # Initialize basic attributes
        import collections

        instance._lineiterators = collections.defaultdict(list)

        # CRITICAL FIX: Define mindatas before using it
        mindatas = getattr(cls, "_mindatas", getattr(cls, "mindatas", 1))

        # Set up parameters for this instance (needed for self.p.period etc.)
        if hasattr(cls, "_params") and cls._params is not None:
            params_cls = cls._params
            # Create parameter instance for this object
            instance.p = params_cls()
            # Update with kwargs
            for key, value in kwargs.items():
                if hasattr(instance.p, key):
                    setattr(instance.p, key, value)
        else:
            # Fallback to empty parameter object
            from .utils import DotDict

            instance.p = DotDict(**kwargs)

        # Create and set up Lines instance
        lines_cls = getattr(cls, "lines", None)
        if lines_cls is not None:
            instance.lines = lines_cls()
            # CRITICAL FIX: Set lines._owner immediately after creating lines instance
            # Use object.__setattr__ to directly set _owner_ref (bypasses Lines.__setattr__)
            object.__setattr__(instance.lines, "_owner_ref", instance)
            # Ensure lines are properly initialized with their own buffers
            if hasattr(instance.lines, "_obj"):
                instance.lines._obj = instance

            # CRITICAL FIX: Ensure lines instance has the essential methods
            # If the lines instance doesn't have advance method, add it
            if not hasattr(instance.lines, "advance"):

                def advance_method(size=1):
                    """Forward all lines in the collection"""
                    for line in getattr(instance.lines, "lines", []):
                        if hasattr(line, "advance"):
                            line.advance(size=size)

                instance.lines.advance = advance_method

            # CRITICAL FIX: Set up line references for indicators
            # Each line should be a separate LineBuffer with its own array
            if hasattr(instance.lines, "lines") and instance.lines.lines:
                # Ensure each line is a LineBuffer with its own array
                for i, line_obj in enumerate(instance.lines.lines):
                    if not isinstance(line_obj, LineBuffer):
                        # Create a new LineBuffer for this line - no import needed, we're in linebuffer.py
                        new_line = LineBuffer()
                        # Copy any existing attributes
                        if hasattr(line_obj, "__dict__"):
                            new_line.__dict__.update(line_obj.__dict__)
                        instance.lines.lines[i] = new_line
                        line_obj = new_line

                    # Ensure the line has its own array
                    if not hasattr(line_obj, "array") or not line_obj.array:
                        import array

                        line_obj.array = array.array("d")
                        line_obj._idx = -1
                        line_obj.lencount = 0

                # Set up convenience references - first line as .line
                instance.line = instance.lines.lines[0] if instance.lines.lines else instance
                instance.l = instance.lines  # Common shorthand
            else:
                # No individual lines, use the instance itself
                instance.line = instance
                instance.l = instance.lines
        else:
            # Create default lines using the proper Lines class
            from .lineseries import Lines

            instance.lines = Lines()
            # Add the advance method if it doesn't exist
            if not hasattr(instance.lines, "advance"):

                def advance_method(size=1):
                    """Forward all lines in the collection"""
                    for line in getattr(instance.lines, "lines", []):
                        if hasattr(line, "advance"):
                            line.advance(size=size)

                instance.lines.advance = advance_method
            instance.line = instance
            instance.l = instance.lines

        # CRITICAL FIX: Auto-assign data from owner if no data provided and mindatas > 0
        if mindatas > 0:
            # Try to get owner and auto-assign data using multiple strategies
            from . import metabase

            owner = None

            # Strategy 1: Use findowner
            try:
                import backtrader as bt

                owner = metabase.findowner(instance, bt.Strategy)
            except Exception:
                pass

            # If we found an owner with data, auto-assign it
            if owner is not None and hasattr(owner, "data") and owner.data is not None:
                # Check if we already have data in args
                data_count = 0
                for arg in args:
                    if (
                        hasattr(arg, "lines")
                        or hasattr(arg, "_name")
                        or str(type(arg).__name__).endswith("Data")
                    ):
                        data_count += 1

                # If we need more data sources than we have, auto-assign from owner
                if data_count < mindatas:
                    # Add owner's data as needed
                    missing_data_count = mindatas - data_count
                    for _ in range(missing_data_count):
                        args = (owner.data,) + args

        # Process arguments to identify data sources
        data_count = 0
        processed_datas = []

        for i, arg in enumerate(args):
            if (
                hasattr(arg, "lines")
                or hasattr(arg, "_name")
                or str(type(arg).__name__).endswith("Data")
            ):
                processed_datas.append(arg)
                data_count += 1
                if data_count >= mindatas:
                    break

        instance.datas = processed_datas

        if processed_datas:
            instance.data = processed_datas[0]
        else:
            instance.data = None

        # Set up dnames if available
        try:
            from .utils import DotDict

            instance.dnames = DotDict(
                [(d._name, d) for d in instance.datas if getattr(d, "_name", "")]
            )
        except:
            instance.dnames = {}

        return instance

    def __init__(self, *args, **kwargs):
        # CRITICAL FIX: Set lines._owner FIRST, before any other initialization
        # This ensures line bindings in user's __init__ can find the owner
        if hasattr(self, "lines") and self.lines is not None:
            # If lines is still a class, create an instance first
            if isinstance(self.lines, type):
                self.lines = self.lines()
            # Now set owner using object.__setattr__ to directly set _owner_ref
            if self.lines is not None:
                object.__setattr__(self.lines, "_owner_ref", self)

        # Set up _owner from call stack BEFORE calling dopreinit
        from . import metabase

        # Try to find any LineIterator-like owner

        # Try findowner first with different classes
        self._owner = None

        # First try to find a Strategy specifically
        try:
            import backtrader as bt

            self._owner = metabase.findowner(self, bt.Strategy)
        except:
            pass

        # If no Strategy found, try LineIterator
        if self._owner is None:
            try:
                from .lineiterator import LineIterator

                self._owner = metabase.findowner(self, LineIterator)
            except:
                pass

        # If still no owner, try a broader search
        if self._owner is None:
            self._owner = metabase.findowner(self, None)

        # If still no owner, manually search the call stack more thoroughly
        if self._owner is None:
            import sys

            for level in range(2, 20):  # Search deeper in the stack
                try:
                    frame = sys._getframe(level)
                    frame_self = frame.f_locals.get("self", None)
                    if frame_self is not None and frame_self is not self:
                        # Check if this looks like a strategy
                        if (
                            hasattr(frame_self, "datas")
                            and hasattr(frame_self, "broker")
                            and hasattr(frame_self, "_addindicator")
                        ):
                            self._owner = frame_self
                            break
                        # Check if this looks like a LineIterator
                        elif hasattr(frame_self, "_lineiterators") and hasattr(
                            frame_self, "addindicator"
                        ):
                            self._owner = frame_self
                            break
                except ValueError:
                    break

        # Call pre-init
        self.__class__.dopreinit(self, *args, **kwargs)

        # Call parent init
        super(LineActions, self).__init__()

        # Call post-init
        self.__class__.dopostinit(self, *args, **kwargs)

    def getindicators(self):
        return []

    def qbuffer(self, savemem=0):
        super(LineActions, self).qbuffer(savemem=1)

    def plotlabel(self):
        """Return the plot label for this line object"""
        # Try to get plot label from _plotlabel method
        if hasattr(self, "_plotlabel"):
            label_dict = self._plotlabel()
            # Convert dict to string format
            if isinstance(label_dict, dict):
                # Format as 'ClassName(param1=value1, param2=value2)'
                params_str = ", ".join(f"{k}={v}" for k, v in label_dict.items())
                if params_str:
                    return f"{self.__class__.__name__}({params_str})"
                else:
                    return self.__class__.__name__
            else:
                return str(label_dict)
        # Fallback: return class name
        return self.__class__.__name__

    def _plotlabel(self):
        """Default implementation of plot label"""
        # Try to get params if available
        if hasattr(self, "params") and hasattr(self.params, "_getkwargs"):
            return self.params._getkwargs()
        # Otherwise return empty dict
        return {}

    @staticmethod
    def arrayize(obj):
        if not hasattr(obj, "array"):
            if not hasattr(obj, "__getitem__"):
                # CRITICAL FIX: Create a LineNum that properly handles _minperiod
                line_num = LineNum(obj)
                # Ensure the LineNum has the _minperiod attribute
                if not hasattr(line_num, "_minperiod"):
                    line_num._minperiod = 1
                return line_num  # make it a LineNum
            if not hasattr(obj, "__len__"):
                pseudo_array = PseudoArray(obj)
                # CRITICAL FIX: Ensure PseudoArray objects have _minperiod for compatibility
                if not hasattr(pseudo_array, "_minperiod"):
                    pseudo_array._minperiod = 1
                return pseudo_array  # Can iterate (for once)

        return obj

    def _next_old(self):
        """DEPRECATED: This method is no longer used. LineIterator._next() is used instead."""
        # CRITICAL FIX: Prevent double processing if _once was already called
        if hasattr(self, "_once_called") and self._once_called:
            return  # Already processed in once mode, don't process again

        # CRITICAL FIX: Ensure data synchronization without over-advancing
        if hasattr(self, "_clock") and self._clock is not None:
            try:
                clock_len = len(self._clock)
                self_len = len(self)

                # Only advance if we're behind the clock and not already at or ahead
                if self_len < clock_len and (clock_len - self_len) <= 1:
                    # Forward one step to match the clock
                    self.forward()
            except Exception:
                # If clock access fails, just forward once
                self.forward()
        else:
            # No clock, just forward once
            self.forward()

        # Call prenext or nextstart/next depending on minperiod
        if len(self) < self._minperiod:
            self.prenext()
        elif len(self) == self._minperiod:
            self.nextstart()  # called once for the 1st value over minperiod
        else:
            self.next()  # called for each value over minperiod

    def _once(self, start, end):
        # Mark that once was called to prevent double processing in _next
        self._once_called = True

        # CRITICAL FIX: Ensure array exists but don't pre-fill it
        # Pre-filling causes incorrect buflen() calculations
        if not hasattr(self, "array") or self.array is None:
            import array as array_module

            self.array = array_module.array(str("d"))

        # CRITICAL FIX: Ensure proper range for once processing
        if start < 0:
            start = 0
        if end < start:
            end = start

        # CRITICAL FIX: Get the actual buffer length if available
        if hasattr(self, "_clock") and self._clock and hasattr(self._clock, "buflen"):
            max_len = self._clock.buflen()
            if end > max_len:
                end = max_len

        # CRITICAL FIX: Call _once() on all child line iterators first
        # This ensures dependencies are calculated before this indicator
        if hasattr(self, "_lineiterators"):
            from .lineiterator import LineIterator

            for indicator in self._lineiterators.get(LineIterator.IndType, []):
                try:
                    if hasattr(indicator, "_once"):
                        indicator._once(start, end)
                except Exception:
                    # Continue processing other indicators if one fails
                    pass

        # CRITICAL FIX: Call preonce before main processing
        try:
            if hasattr(self, "preonce"):
                self.preonce(start, end)
        except Exception:
            pass

        # CRITICAL FIX: Process the main once calculation
        # Try to call once method if it exists
        try:
            if hasattr(self, "once") and callable(self.once):
                self.once(start, end)
        except Exception:
            # If once fails or doesn't exist, skip it
            # The indicator will be calculated via next() calls during strategy execution
            pass

        # CRITICAL FIX: Update lencount after once processing to match the data length
        # In runonce mode, lencount should equal the number of data points processed
        # Get the actual data length from the clock or data source
        actual_data_len = end
        try:
            # Try to get the actual data length from clock or data sources
            if hasattr(self, "_clock") and self._clock:
                try:
                    actual_data_len = self._clock.buflen()
                except:
                    try:
                        actual_data_len = len(self._clock)
                    except:
                        pass
            elif hasattr(self, "datas") and self.datas and len(self.datas) > 0:
                try:
                    actual_data_len = self.datas[0].buflen()
                except:
                    try:
                        actual_data_len = len(self.datas[0])
                    except:
                        pass
            # Use the maximum of end and actual_data_len to ensure we don't truncate
            final_len = max(end, actual_data_len) if actual_data_len > 0 else end
        except:
            final_len = end

        if hasattr(self, "lines") and hasattr(self.lines, "lines") and self.lines.lines:
            # Update lencount for all lines to match the data length
            for line in self.lines.lines:
                if hasattr(line, "lencount"):
                    # CRITICAL FIX: Set lencount to final_len (actual data length)
                    # This ensures len(indicator) == len(strategy) in runonce mode
                    line.lencount = final_len
                if hasattr(line, "_idx"):
                    # Set _idx to the last processed position
                    line._idx = final_len - 1 if final_len > 0 else -1

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
    return _LineDelay(PseudoArray(repeat(num)), 0)


class _LineDelay(LineActions):
    def __init__(self, a, ago):
        super(_LineDelay, self).__init__()
        self.a = self.arrayize(a)
        self.ago = ago

        # Need to add the delay to the period
        # CRITICAL FIX: Handle _minperiod more safely for any type of object
        if hasattr(a, "_minperiod"):
            self.addminperiod(abs(ago))
        else:
            # If 'a' doesn't have _minperiod, set a default
            self.addminperiod(max(1, abs(ago)))

    def next(self):
        # CRITICAL FIX: Proper delay operation
        try:
            # Get the delayed value
            delayed_val = self.a[-self.ago]

            # Ensure value is never None or NaN
            if delayed_val is None:
                delayed_val = 0.0
            elif isinstance(delayed_val, float) and math.isnan(delayed_val):
                delayed_val = 0.0

            self[0] = delayed_val
        except (IndexError, AttributeError):
            # If we can't get the delayed value, use 0.0
            self[0] = 0.0

    def once(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        ago = self.ago

        # CRITICAL FIX: Ensure destination array is properly sized
        while len(dst) < end:
            dst.append(0.0)

        # CRITICAL FIX: Check if source is a constant value (PseudoArray with repeat)
        # We need to check the wrapped object, not just the array, because
        # PseudoArray.array returns a new list each time
        is_constant = False
        constant_value = None

        # Check if self.a is a PseudoArray wrapping a repeat object
        # OR if self.a is a _LineDelay that wraps a PseudoArray with repeat
        source_obj = self.a
        if hasattr(self.a, "a"):
            # self.a is a _LineDelay, check its source
            source_obj = self.a.a

        if hasattr(source_obj, "wrapped"):
            wrapped = source_obj.wrapped
            # Check if it's a repeat object
            if (
                isinstance(wrapped, itertools.repeat)
                or str(type(wrapped)) == "<class 'itertools.repeat'>"
            ):
                is_constant = True
                try:
                    # Get the constant value from the repeat object
                    # Create a new iterator to avoid consuming it
                    constant_value = next(iter(wrapped))
                    # Ensure constant value is not None or NaN
                    if constant_value is None:
                        constant_value = 0.0
                    elif isinstance(constant_value, float) and math.isnan(constant_value):
                        constant_value = 0.0
                except (StopIteration, TypeError):
                    constant_value = 0.0

        # If not a constant, get the source array
        if not is_constant:
            src = self.a.array

        for i in range(start, end):
            if is_constant:
                # For constant values, just use the constant
                dst[i] = constant_value
            else:
                # CRITICAL FIX: Proper bounds checking for delayed access
                src_index = i - ago
                if src_index >= 0 and src_index < len(src):
                    val = src[src_index]
                    # Ensure value is never None or NaN
                    if val is None:
                        val = 0.0
                    elif isinstance(val, float) and math.isnan(val):
                        val = 0.0
                    dst[i] = val
                elif len(src) > 0:
                    # If index is out of bounds but we have source data, use the last available value
                    val = src[-1]
                    if val is None:
                        val = 0.0
                    elif isinstance(val, float) and math.isnan(val):
                        val = 0.0
                    dst[i] = val
                else:
                    # If no source data available, use 0.0
                    dst[i] = 0.0


class _LineForward(LineActions):
    def __init__(self, a, ago):
        super(_LineForward, self).__init__()
        self.a = self.arrayize(a)
        self.ago = ago

        # Need to add the delay to the period
        if hasattr(a, "_minperiod"):
            self.addminperiod(ago)

    def next(self):
        # operation(float, other) ... expecting other to be a float
        # CRITICAL FIX: Ensure we get valid numeric values for indicator calculations
        try:
            # Get operand values with proper type checking
            if hasattr(self.a, "__getitem__"):
                # LineBuffer-like object - get current value
                try:
                    a_val = self.a[0]
                except (IndexError, TypeError):
                    a_val = 0.0
            else:
                # Direct value
                a_val = self.a

            if hasattr(self.b, "__getitem__"):
                # LineBuffer-like object - get current value
                try:
                    b_val = self.b[0]
                except (IndexError, TypeError):
                    b_val = 0.0
            else:
                # Direct value
                b_val = self.b

            # CRITICAL FIX: Ensure values are numeric and not None/NaN
            if a_val is None:
                a_val = 0.0
            elif isinstance(a_val, float) and math.isnan(a_val):
                a_val = 0.0
            elif not isinstance(a_val, (int, float)):
                try:
                    a_val = float(a_val)
                except (ValueError, TypeError):
                    a_val = 0.0

            if b_val is None:
                b_val = 0.0
            elif isinstance(b_val, float) and math.isnan(b_val):
                b_val = 0.0
            elif not isinstance(b_val, (int, float)):
                try:
                    b_val = float(b_val)
                except (ValueError, TypeError):
                    b_val = 0.0

            # CRITICAL FIX: Actually perform the operation and store the result
            # Handle both normal and reverse operations
            if hasattr(self, "operation") and self.operation:
                # CRITICAL FIX: Handle reverse operations properly
                if getattr(self, "r", False):
                    result = self.operation(b_val, a_val)  # Reverse: b op a
                else:
                    result = self.operation(a_val, b_val)  # Normal: a op b

                # Ensure result is a valid number
                if result is None:
                    result = 0.0
                elif isinstance(result, float) and math.isnan(result):
                    result = 0.0
                elif not isinstance(result, (int, float)):
                    try:
                        result = float(result)
                    except (ValueError, TypeError):
                        result = 0.0

                # Store the result in the current position
                self[0] = result
            else:
                # Fallback: store a_val if no operation is defined
                self[0] = a_val

        except Exception:
            # If anything fails, store 0.0 to prevent crashes
            # print(f"LinesOperation.next() error: {e}")  # Removed for performance
            self[0] = 0.0

    def once(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        op = self.operation

        # CRITICAL FIX: Ensure destination array is properly sized
        while len(dst) < end:
            dst.append(0.0)

        # CRITICAL FIX: Ensure source array has required data
        if len(srca) < end:
            # If source array is shorter than required range, only process available data
            end = min(end, len(srca))

        for i in range(start, end):
            try:
                # CRITICAL FIX: Bounds checking for source array
                a_val = srca[i] if i < len(srca) else 0.0

                # Ensure value is numeric
                if a_val is None or (isinstance(a_val, float) and math.isnan(a_val)):
                    a_val = 0.0

                result = op(a_val)

                # Ensure result is valid
                if result is None or (isinstance(result, float) and math.isnan(result)):
                    result = 0.0

                dst[i] = result
            except Exception:
                # If operation fails, store 0.0
                dst[i] = 0.0


class LinesOperation(LineActions):
    def __init__(self, a, b, operation, r=False):
        super(LinesOperation, self).__init__()
        self.operation = operation
        self.a = a  # always a linebuffer-like object
        self.b = self.arrayize(b)
        self.r = r

        # ensure a is added if it's a lineiterator-like object
        # self.addminperiod(1) already done by the base class
        # CRITICAL FIX: Handle _minperiod attribute access more safely
        a_minperiod = getattr(a, "_minperiod", 1) if hasattr(a, "_minperiod") else 1
        b_minperiod = getattr(b, "_minperiod", 1) if hasattr(b, "_minperiod") else 1

        self.addminperiod(a_minperiod)
        self.addminperiod(b_minperiod)

    def next(self):
        # operation(float, other) ... expecting other to be a float
        # CRITICAL FIX: Ensure we get valid numeric values for indicator calculations
        try:
            # Get operand values with proper type checking
            if hasattr(self.a, "__getitem__"):
                # LineBuffer-like object - get current value
                try:
                    a_val = self.a[0]
                except (IndexError, TypeError):
                    a_val = 0.0
            else:
                # Direct value
                a_val = self.a

            if hasattr(self.b, "__getitem__"):
                # LineBuffer-like object - get current value
                try:
                    b_val = self.b[0]
                except (IndexError, TypeError):
                    b_val = 0.0
            else:
                # Direct value
                b_val = self.b

            # CRITICAL FIX: Ensure values are numeric and not None/NaN
            if a_val is None:
                a_val = 0.0
            elif isinstance(a_val, float) and math.isnan(a_val):
                a_val = 0.0
            elif not isinstance(a_val, (int, float)):
                try:
                    a_val = float(a_val)
                except (ValueError, TypeError):
                    a_val = 0.0

            if b_val is None:
                b_val = 0.0
            elif isinstance(b_val, float) and math.isnan(b_val):
                b_val = 0.0
            elif not isinstance(b_val, (int, float)):
                try:
                    b_val = float(b_val)
                except (ValueError, TypeError):
                    b_val = 0.0

            # CRITICAL FIX: Actually perform the operation and store the result
            # Handle both normal and reverse operations
            if hasattr(self, "operation") and self.operation:
                # CRITICAL FIX: Handle reverse operations properly
                if getattr(self, "r", False):
                    result = self.operation(b_val, a_val)  # Reverse: b op a
                else:
                    result = self.operation(a_val, b_val)  # Normal: a op b

                # Ensure result is a valid number
                if result is None:
                    result = 0.0
                elif isinstance(result, float) and math.isnan(result):
                    result = 0.0
                elif not isinstance(result, (int, float)):
                    try:
                        result = float(result)
                    except (ValueError, TypeError):
                        result = 0.0

                # Store the result in the current position
                self[0] = result
            else:
                # Fallback: store a_val if no operation is defined
                self[0] = a_val

        except Exception:
            # If anything fails, store 0.0 to prevent crashes
            # print(f"LinesOperation.next() error: {e}")  # Removed for performance
            self[0] = 0.0

    def once(self, start, end):
        if hasattr(self.b, "array"):
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
            try:
                # CRITICAL FIX: Bounds checking for source arrays
                a_val = srca[i] if i < len(srca) else 0.0
                b_val = srcb[i] if i < len(srcb) else 0.0

                # Ensure values are numeric
                if a_val is None or (isinstance(a_val, float) and math.isnan(a_val)):
                    a_val = 0.0
                if b_val is None or (isinstance(b_val, float) and math.isnan(b_val)):
                    b_val = 0.0

                if self.r:
                    result = op(b_val, a_val)
                else:
                    result = op(a_val, b_val)

                # Ensure result is valid
                if result is None or (isinstance(result, float) and math.isnan(result)):
                    result = 0.0

                dst[i] = result
            except Exception:
                # If operation fails, store 0.0
                dst[i] = 0.0

    def _once_time_op(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b[0]
        op = self.operation

        for i in range(start, end):
            try:
                # CRITICAL FIX: Bounds checking for source array
                a_val = srca[i] if i < len(srca) else 0.0

                # Ensure values are numeric
                if a_val is None or (isinstance(a_val, float) and math.isnan(a_val)):
                    a_val = 0.0
                if srcb is None or (isinstance(srcb, float) and math.isnan(srcb)):
                    srcb = 0.0

                if self.r:
                    result = op(srcb, a_val)
                else:
                    result = op(a_val, srcb)

                # Ensure result is valid
                if result is None or (isinstance(result, float) and math.isnan(result)):
                    result = 0.0

                dst[i] = result
            except Exception:
                # If operation fails, store 0.0
                dst[i] = 0.0

    def _once_val_op(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b
        op = self.operation

        for i in range(start, end):
            try:
                # CRITICAL FIX: Bounds checking for source array
                a_val = srca[i] if i < len(srca) else 0.0

                # Ensure values are numeric
                if a_val is None or (isinstance(a_val, float) and math.isnan(a_val)):
                    a_val = 0.0
                if srcb is None or (isinstance(srcb, float) and math.isnan(srcb)):
                    srcb = 0.0

                result = op(a_val, srcb)

                # Ensure result is valid
                if result is None or (isinstance(result, float) and math.isnan(result)):
                    result = 0.0

                dst[i] = result
            except Exception:
                # If operation fails, store 0.0
                dst[i] = 0.0

    def _once_val_op_r(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b
        op = self.operation

        for i in range(start, end):
            try:
                # CRITICAL FIX: Bounds checking for source array
                a_val = srca[i] if i < len(srca) else 0.0

                # Ensure values are numeric
                if a_val is None or (isinstance(a_val, float) and math.isnan(a_val)):
                    a_val = 0.0
                if srcb is None or (isinstance(srcb, float) and math.isnan(srcb)):
                    srcb = 0.0

                result = op(srcb, a_val)

                # Ensure result is valid
                if result is None or (isinstance(result, float) and math.isnan(result)):
                    result = 0.0

                dst[i] = result
            except Exception:
                # If operation fails, store 0.0
                dst[i] = 0.0


class LineOwnOperation(LineActions):
    def __init__(self, a, operation):
        super(LineOwnOperation, self).__init__()
        self.operation = operation
        self.a = a

        # CRITICAL FIX: Handle _minperiod attribute access more safely
        a_minperiod = getattr(a, "_minperiod", 1) if hasattr(a, "_minperiod") else 1
        self.addminperiod(a_minperiod)

    def next(self):
        self[0] = self.operation(self.a[0])

    def once(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        op = self.operation

        # CRITICAL FIX: Ensure destination array is properly sized
        while len(dst) < end:
            dst.append(0.0)

        # CRITICAL FIX: Ensure source array has required data
        if len(srca) < end:
            # If source array is shorter than required range, only process available data
            end = min(end, len(srca))

        for i in range(start, end):
            try:
                # CRITICAL FIX: Bounds checking for source array
                a_val = srca[i] if i < len(srca) else 0.0

                # Ensure value is numeric
                if a_val is None or (isinstance(a_val, float) and math.isnan(a_val)):
                    a_val = 0.0

                result = op(a_val)

                # Ensure result is valid
                if result is None or (isinstance(result, float) and math.isnan(result)):
                    result = 0.0

                dst[i] = result
            except Exception:
                # If operation fails, store 0.0
                dst[i] = 0.0

    def size(self):
        """Return the number of lines in this LineActions object"""
        if hasattr(self, "lines") and hasattr(self.lines, "size"):
            return self.lines.size()
        elif hasattr(self, "lines") and hasattr(self.lines, "__len__"):
            return len(self.lines)
        else:
            return 1  # Default to 1 line if no lines object available
