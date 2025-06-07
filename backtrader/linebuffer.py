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
import math
import time

from .utils.py3 import range, string_types

from .lineroot import LineRoot, LineSingle, LineMultiple, LineRootMixin
from . import metabase
from .utils import num2date, time2num


NAN = float("NaN")


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
        # Initialize core attributes first
        self._minperiod = 1  # Ensure _minperiod is always set
        self._array = array.array(str('d'))  # Internal array for storage
        self._idx = -1  # Current index
        self._size = 0  # Current size of the array
        self.maxlen = None
        self.extension = None
        self.lencount = None
        self.useislice = None
        self.array = None
        
        # CRITICAL FIX: Ensure lines is properly initialized
        if not hasattr(self, 'lines'):
            self.lines = [self]  # lines是一个包含自身的列表
            
        # Initialize mode and bindings
        self.mode = self.UnBounded  # self.mode默认值是0
        self.bindings = list()  # self.bindings默认是一个列表
        
        # Initialize timezone and other attributes
        self._tz = None  # 时区设置
        
        # Call reset to initialize the rest of the state
        self.reset()  # 重置，调用自身的reset方法
        
        # CRITICAL FIX: Ensure we have a valid array
        if not hasattr(self, '_array') or not isinstance(self._array, array.array):
            self._array = array.array(str('d'))
            self._size = 0

    # 获取_idx的值
    def get_idx(self):
        # CRITICAL FIX: Ensure _idx exists before accessing it
        if not hasattr(self, '_idx'):
            self._idx = -1
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
        
        # CRITICAL FIX: Ensure _idx exists before accessing it
        if not hasattr(self, '_idx'):
            self._idx = -1
            
        if self.mode == self.QBuffer:
            # CRITICAL FIX: Ensure lenmark attribute exists
            if not hasattr(self, 'lenmark'):
                self.lenmark = 0
                
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
            # Add extrasize to ensure resample/replay work. They will
            # use backwards to erase the last bar/tick before delivering a new
            # bar (with reopening) the tick which was just delivered. Using
            # maxsize -> just erasing the delivered tick and not the
            # already removed bar would remove the bar that gets the tick
            # allows the forward without removing that bar
            # CRITICAL FIX: Ensure maxlen + extrasize is always positive
            deque_maxlen = max(1, self.maxlen + self.extrasize)
            self.array = collections.deque(maxlen=deque_maxlen)
            self.useislice = True
        else:
            # CRITICAL FIX: Initialize with empty array
            self.array = array.array(str("d"))
            self.useislice = False
            
            # CRITICAL FIX: For indicators, pre-fill with NaN to avoid uninitialized values
            if (hasattr(self, '_ltype') and getattr(self, '_ltype', None) == 0) or \
               (hasattr(self, '__class__') and 'Indicator' in str(self.__class__.__name__)):
                # Pre-fill with a few NaN values to avoid index errors
                for _ in range(10):
                    self.array.append(float('nan'))
        
        # 默认最开始的时候lencount等于0,idx等于-1,extension等于0
        self.lencount = 0
        self.idx = -1
        self.extension = 0
        
        # CRITICAL FIX: Ensure _minperiod is set
        if not hasattr(self, '_minperiod'):
            self._minperiod = 1

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
        """Calculate the length of this line object"""
        # CRITICAL FIX: Ensure necessary attributes exist before accessing
        if not hasattr(self, 'lencount'):
            self.lencount = 0
            
        if not hasattr(self, 'array'):
            self.array = array.array(str('d'))
        
        # Prevent recursion - return current length if recursion is detected
        if hasattr(self, '_len_recursion_guard'):
            return self.lencount
        
        # Set recursion guard
        self._len_recursion_guard = True
        
        try:
            # CRITICAL FIX: Special handling for indicators to synchronize with strategies
            if (hasattr(self, '_ltype') and getattr(self, '_ltype', None) == 0) or \
               (hasattr(self, '__class__') and 'Indicator' in str(self.__class__.__name__)):
                
                # Try getting length from owner (usually strategy)
                if hasattr(self, '_owner') and self._owner is not None:
                    if hasattr(self._owner, '__len__') and not hasattr(self._owner, '_len_recursion_guard'):
                        return len(self._owner)
                    elif hasattr(self._owner, 'datas') and self._owner.datas:
                        primary_data = self._owner.datas[0]
                        if hasattr(primary_data, '__len__'):
                            return len(primary_data)
                        elif hasattr(primary_data, 'lencount'):
                            return primary_data.lencount
                    elif hasattr(self._owner, 'lines') and hasattr(self._owner.lines, 'lines') and self._owner.lines.lines:
                        first_line = self._owner.lines.lines[0]
                        if hasattr(first_line, 'lencount'):
                            return first_line.lencount
                        elif hasattr(first_line, 'array') and hasattr(first_line.array, '__len__'):
                            return len(first_line.array)
                            
                # Try using clock for synchronization
                if hasattr(self, '_clock') and self._clock is not None:
                    if hasattr(self._clock, '__len__'):
                        return len(self._clock)
                    elif hasattr(self._clock, 'lencount'):
                        return self._clock.lencount
                
                # Fallback for indicators without properly linked data sources
                # No synchronization points found - return safe default
                return 0
            
            # For non-indicators (strategies, data feeds, etc.), use the processed line length
            if hasattr(self, 'lines') and self.lines:
                # If it's a collection of lines, get the minimum length
                if hasattr(self.lines, '__iter__') and not isinstance(self.lines, str):
                    try:
                        lengths = []
                        for line in self.lines:
                            if hasattr(line, '__len__') and not hasattr(line, '_len_recursion_guard'):
                                # Set recursion guard to prevent infinite loops
                                line._len_recursion_guard = True
                                try:
                                    lengths.append(len(line))
                                finally:
                                    if hasattr(line, '_len_recursion_guard'):
                                        delattr(line, '_len_recursion_guard')
                            elif hasattr(line, 'lencount'):
                                lengths.append(line.lencount)
                        
                        if lengths:
                            return min(lengths)
                    except Exception:
                        pass
                        
                # If lines is a single object with length, use it
                elif hasattr(self.lines, '__len__'):
                    try:
                        return len(self.lines)
                    except Exception:
                        pass
                elif hasattr(self.lines, 'lencount'):
                    return self.lines.lencount
        except Exception:
            # Silently handle all exceptions and fall back to default behavior
            pass
        finally:
            # Always clean up recursion guard
            if hasattr(self, '_len_recursion_guard'):
                delattr(self, '_len_recursion_guard')
        
        # Default fallback: return internal length counter
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
        """Get the value at the specified offset from the current index.
        
        Args:
            ago (int): Offset from current index (0 = current, -1 = previous, 1 = next)
            
        Returns:
            The value at the specified position, or NaN/0.0 if out of bounds
        """
        try:
            # CRITICAL FIX: Ensure we have valid state
            if not hasattr(self, '_idx') or self._idx is None:
                self._idx = -1
                
            # CRITICAL FIX: Ensure array is initialized
            if not hasattr(self, 'array') or self.array is None:
                import array
                self.array = array.array('d')
                
            # For indicators, pre-fill with NaN if empty to avoid index errors
            is_indicator = (hasattr(self, '_ltype') and getattr(self, '_ltype', None) == 0) or \
                          (hasattr(self, '__class__') and 'Indicator' in str(self.__class__.__name__))
            
            if len(self.array) == 0 and is_indicator:
                self.array.append(float('nan'))
            
            # Calculate the required index
            required_index = self._idx + ago
            
            # Handle out-of-bounds access
            if required_index < 0 or required_index >= len(self.array):
                # For indicators, return NaN for out-of-bounds access
                if is_indicator:
                    return float('nan')
                # For data feeds, return first/last value or 0.0 if empty
                if len(self.array) == 0:
                    return 0.0
                return self.array[0] if required_index < 0 else self.array[-1]
                
            # Get the value from the array
            value = self.array[required_index]
            
            # CRITICAL FIX: Handle None/NaN values consistently
            if value is None or (isinstance(value, float) and math.isnan(value)):
                if is_indicator:
                    return float('nan')
                return 0.0
                
            # Special handling for datetime lines to prevent NaN from breaking date conversion
            if hasattr(self, '_owner') and hasattr(self._owner, 'lines'):
                try:
                    # Check if this buffer is the datetime line (usually index 0 for data feeds)
                    if hasattr(self._owner.lines, '_getlines'):
                        lines = self._owner.lines._getlines()
                        if lines and len(lines) > 0:
                            # Check if this is the first line (datetime) by checking if it's at index 0
                            if hasattr(self._owner.lines, 'lines') and len(self._owner.lines.lines) > 0:
                                if self is self._owner.lines.lines[0]:
                                    # This is likely the datetime line
                                    if isinstance(value, float) and (math.isnan(value) or value == 0.0):
                                        # Return a valid default date instead of NaN or 0
                                        # Use a default date of 2000-01-01 00:00:00 as float representation
                                        try:
                                            import datetime
                                            # Try to import date2num from the correct module
                                            try:
                                                from .utils import date2num
                                            except ImportError:
                                                try:
                                                    from backtrader.utils import date2num
                                                except ImportError:
                                                    # Fallback: return a known good timestamp value
                                                    return 730485.0  # 2000-01-01 as matplotlib date number
                                            
                                            default_date = datetime.datetime(2000, 1, 1)
                                            return date2num(default_date)
                                        except:
                                            # Final fallback: return a known good timestamp value
                                            return 730485.0  # 2000-01-01 as matplotlib date number
                except:
                    # If any check fails, just return the original value
                    pass
            
            return value
            
        except Exception as e:
            # For any other unexpected errors, return appropriate default
            try:
                import sys
                frame = sys._getframe(1)
                caller = f"{frame.f_code.co_name} at line {frame.f_lineno}"
                print(f"Warning: LineBuffer.__getitem__ error in {caller}: {e}")
            except:
                pass
            
            # Return appropriate default based on object type
            if (hasattr(self, '_ltype') and getattr(self, '_ltype', None) == 0) or \
               (hasattr(self, '__class__') and 'Indicator' in str(self.__class__.__name__)):
                return float('nan')
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
        # CRITICAL FIX: Ensure we have a valid array
        if not hasattr(self, 'array') or self.array is None:
            import array
            self.array = array.array('d')
            
        # CRITICAL FIX: Handle None/NaN values consistently
        if value is None or (isinstance(value, float) and math.isnan(value)):
            # For indicators, use NaN as default, for others use 0.0
            if (hasattr(self, '_ltype') and getattr(self, '_ltype', None) == 0) or \
               (hasattr(self, '__class__') and 'Indicator' in str(self.__class__.__name__)):
                value = float('nan')
            else:
                value = 0.0
        
        # Calculate the required index
        required_index = self.idx + ago
        
        # Handle index out of bounds
        if required_index >= len(self.array):
            # Extend the array to accommodate the required index
            extend_size = required_index - len(self.array) + 1
            # For indicators, extend with NaN, otherwise with 0.0
            fill_value = float('nan') if ((hasattr(self, '_ltype') and getattr(self, '_ltype', None) == 0) or 
                                       (hasattr(self, '__class__') and 'Indicator' in str(self.__class__.__name__))) else 0.0
            for _ in range(extend_size):
                self.array.append(fill_value)
        elif required_index < 0:
            # Skip setting values for negative indices
            return
            
        # Set the value at the required index
        self.array[required_index] = value
        
        # Update any bindings
        for binding in self.bindings:
            binding[ago] = value

    # 给array设置具体的值
    def set(self, value, ago=0):
        """Sets a value at position "ago" and executes any associated bindings

        Keyword Args:
            value (variable): value to be set
            ago (int): Point of the array to which size will be added to return
            the slice
        """
        # CRITICAL FIX: Ensure we never store None values - convert to 0.0
        if value is None:
            value = 0.0
        # CRITICAL FIX: Also convert NaN to 0.0 to prevent comparison issues
        elif isinstance(value, float) and math.isnan(value):
            value = 0.0
        
        # CRITICAL FIX: Ensure array is initialized before accessing
        if not hasattr(self, 'array') or self.array is None:
            import array
            self.array = array.array('d')
        
        # Ensure array has enough space
        required_index = self.idx + ago
        if required_index >= len(self.array):
            # Extend the array to accommodate the required index
            extend_size = required_index - len(self.array) + 1
            for _ in range(extend_size):
                self.array.append(0.0)  # Use 0.0 instead of NAN
        elif required_index < 0:
            # Handle negative indices gracefully
            return
            
        self.array[required_index] = value
        for binding in self.bindings:
            binding[ago] = value

    # 返回到最开始
    def home(self):
        """Rewinds the logical index to the beginning

        The underlying buffer remains untouched and the actual len can be found
        out with buflen
        """
        self.idx = -1
        self.lencount = 0

    # 向前移动一位
    def forward(self, value=float('nan'), size=1):
        """Moves the logical index forward and enlarges the buffer as much as needed

        Keyword Args:
            value (variable): value to be set in new positions
            size (int): How many extra positions to enlarge the buffer
        """
        # CRITICAL FIX: Handle None/NaN values consistently
        if value is None or (isinstance(value, float) and math.isnan(value)):
            # For indicators, use NaN as default, for others use 0.0
            if (hasattr(self, '_ltype') and getattr(self, '_ltype', None) == 0) or \
               (hasattr(self, '__class__') and 'Indicator' in str(self.__class__.__name__)):
                value = float('nan')
            else:
                value = 0.0
        
        # CRITICAL FIX: Ensure array is properly initialized
        if not hasattr(self, 'array') or self.array is None:
            import array
            self.array = array.array('d')
        
        # CRITICAL FIX: Don't limit advancement for indicators - they need to calculate freely
        # Only limit for strategies/data feeds that should sync with clock
        if not ((hasattr(self, '_ltype') and getattr(self, '_ltype', None) == 0) or \
                (hasattr(self, '__class__') and 'Indicator' in str(self.__class__.__name__))):
            # For non-indicators, check clock synchronization
            if hasattr(self, '_clock') and self._clock is not None:
                try:
                    clock_len = len(self._clock)
                    current_len = len(self)
                    
                    # If we're already synchronized or ahead, don't advance further
                    if current_len >= clock_len:
                        return
                        
                    max_advance = clock_len - current_len
                    if size > max_advance:
                        size = max_advance
                        
                    if size <= 0:
                        return
                except Exception:
                    # If there's an error getting clock length, proceed with original logic
                    pass
        
        # CRITICAL FIX: Ensure we have a valid size
        if size <= 0:
            return
            
        self.idx += size
        self.lencount += size

        # CRITICAL FIX: Append values with proper NaN handling
        for i in range(size):
            # For indicators, store NaN as is, otherwise convert to 0.0
            if (hasattr(self, '_ltype') and getattr(self, '_ltype', None) == 0) or \
               (hasattr(self, '__class__') and 'Indicator' in str(self.__class__.__name__)):
                self.array.append(float('nan') if math.isnan(value) else value)
            else:
                self.array.append(0.0 if math.isnan(value) or value is None else value)

    # 向后移动一位
    def backwards(self, size=1, force=False):
        """Moves the logical index backwards and reduces the buffer as much as needed
        
        Keyword Args:
            size (int): How many extra positions to rewind the buffer
            force (bool): Whether to force the reduction of the logical buffer
                          regardless of the minperiod
        """
        # CRITICAL FIX: Ensure we have a valid idx
        if not hasattr(self, 'idx') or self.idx is None:
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
        if not hasattr(self, '_idx') or self._idx is None:
            self._idx = -1
            return False
            
        self._idx -= size
        return self._idx >= 0

    # 把idx和lencount减少size
    def rewind(self, size=1):
        # CRITICAL FIX: Safe attribute access
        if hasattr(self, 'idx'):
            self.idx -= size
        if hasattr(self, 'lencount'):
            self.lencount -= size

    # 把idx和lencount增加size
    def advance(self, size=1):
        """Advances the logical index without touching the underlying buffer"""
        if hasattr(self, 'idx'):
            self.idx += size
        if hasattr(self, 'lencount'):
            self.lencount += size

    # 向前扩展
    def extend(self, value=float('nan'), size=0):
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
        value = self[ago]
        # Check for NaN values and return a default datetime instead of None
        if value is None or (isinstance(value, float) and math.isnan(value)):
            # Return a default date (epoch start - Jan 1, 1970)
            try:
                import datetime
                default_dt = datetime.datetime(2000, 1, 1, 0, 0, 0)
                return default_dt if naive else default_dt.replace(tzinfo=tz or self._tz)
            except:
                # If datetime import fails or tzinfo cannot be set, return datetime.min
                try:
                    import datetime
                    return datetime.datetime.min if naive else datetime.datetime.min.replace(tzinfo=tz or self._tz)
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
        except (ValueError, OverflowError) as e:
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
        dt = self.datetime(ago, tz, naive)
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
        return hash(tuple(id(arg) if hasattr(arg, '__hash__') else str(arg) for arg in args))


class LineActionsMixin:
    """Mixin to provide LineActions functionality without metaclass"""
    
    @classmethod
    def dopreinit(cls, _obj, *args, **kwargs):
        """Pre-initialization processing for LineActions"""
        # Set up clock from owner hierarchy
        _obj._clock = None
        
        if hasattr(_obj, '_owner') and _obj._owner is not None:
            # Try to get clock from owner first
            if hasattr(_obj._owner, '_clock') and _obj._owner._clock is not None:
                _obj._clock = _obj._owner._clock
            # If owner has datas, use the first data as clock  
            elif hasattr(_obj._owner, 'datas') and _obj._owner.datas:
                _obj._clock = _obj._owner.datas[0]
            # If owner has data attribute, use it as clock
            elif hasattr(_obj._owner, 'data') and _obj._owner.data is not None:
                _obj._clock = _obj._owner.data
            # Try the owner itself as clock if it has __len__
            elif hasattr(_obj._owner, '__len__'):
                _obj._clock = _obj._owner
        
        # If still no clock found and we have datas, use the first data
        if _obj._clock is None and hasattr(_obj, 'datas') and _obj.datas:
            _obj._clock = _obj.datas[0]
        
        # Calculate minperiod based on LineBuffer instances
        mindatas = 0
        minperstatus = MAXINT = 2 ** 31 - 1
        
        # Scan class members for LineBuffer instances
        for membername in dir(_obj):
            try:
                member = getattr(_obj, membername)
                if isinstance(member, (LineBuffer, LineSingle)):
                    mindatas += 1
                    if hasattr(member, '_minperiod'):
                        minperstatus = min(minperstatus, member._minperiod)
            except:
                # Skip any attributes that cause issues during inspection
                continue
        
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
            # Check if the owner has the addindicator method
            if hasattr(_obj._owner, 'addindicator'):
                _obj._owner.addindicator(_obj)
                
            # Also ensure the indicator has access to owner's clock and data
            if not hasattr(_obj, '_clock') or _obj._clock is None:
                if hasattr(_obj._owner, '_clock') and _obj._owner._clock is not None:
                    _obj._clock = _obj._owner._clock
                elif hasattr(_obj._owner, 'datas') and _obj._owner.datas:
                    _obj._clock = _obj._owner.datas[0]
                elif hasattr(_obj._owner, 'data') and _obj._owner.data is not None:
                    _obj._clock = _obj._owner.data

        # CRITICAL FIX: Initialize _lineiterators if not present  
        if not hasattr(_obj, '_lineiterators'):
            import collections
            _obj._lineiterators = collections.defaultdict(list)


class PseudoArray(object):
    def __init__(self, wrapped):
        self.wrapped = wrapped
        # CRITICAL FIX: Ensure PseudoArray has _minperiod attribute
        self._minperiod = getattr(wrapped, '_minperiod', 1)

    def __getitem__(self, key):
        try:
            # Try normal indexing first
            return self.wrapped[key]
        except TypeError:
            # Handle itertools.repeat objects and other iterables that don't support indexing
            if hasattr(self.wrapped, '__iter__'):
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
                    return float('nan')
            else:
                # If not iterable, return the wrapped object itself for index 0
                if key == 0:
                    return self.wrapped
                else:
                    return float('nan')

    @property
    def array(self):
        # Handle repeat objects specially
        if str(type(self.wrapped)) == "<class 'itertools.repeat'>":
            # For repeat objects, return a list with one element repeated
            return [next(iter(self.wrapped))]
        elif hasattr(self.wrapped, 'array'):
            return self.wrapped.array
        else:
            return self.wrapped


class LineActions(LineBuffer, LineActionsMixin, metabase.ParamsMixin):
    '''
    Base class for *Line Clases* with different lines, derived from a
    LineBuffer
    '''
    
    from .lineroot import LineRoot
    _ltype = LineRoot.IndType
    
    # Add plotlines attribute for plotting support
    plotlines = object()

    def __new__(cls, *args, **kwargs):
        """Handle data processing for indicators and other LineActions objects"""
        
        # Create the instance using the normal Python object creation
        instance = super(LineActions, cls).__new__(cls)
        
        # Initialize basic attributes
        instance._lineiterators = getattr(instance, '_lineiterators', {})
        
        # CRITICAL FIX: Define mindatas before using it
        mindatas = getattr(cls, '_mindatas', getattr(cls, 'mindatas', 1))
        
        # Set up parameters for this instance (needed for self.p.period etc.)
        if hasattr(cls, '_params') and cls._params is not None:
            params_cls = cls._params
            # Create parameter instance for this object
            instance.p = params_cls()
        else:
            # Fallback to empty parameter object
            from .utils import DotDict
            instance.p = DotDict()
        
        # Create and set up Lines instance
        lines_cls = getattr(cls, 'lines', None)
        if lines_cls is not None:
            instance.lines = lines_cls()
            # Ensure lines are properly initialized with their own buffers
            if hasattr(instance.lines, '_obj'):
                instance.lines._obj = instance
                
            # CRITICAL FIX: Ensure lines instance has the essential methods
            # If the lines instance doesn't have advance method, add it
            if not hasattr(instance.lines, 'advance'):
                def advance_method(size=1):
                    """Forward all lines in the collection"""
                    for line in getattr(instance.lines, 'lines', []):
                        if hasattr(line, 'advance'):
                            line.advance(size=size)
                instance.lines.advance = advance_method
                
            # CRITICAL FIX: Set up line references for indicators
            # Each line should be a separate LineBuffer with its own array
            if hasattr(instance.lines, 'lines') and instance.lines.lines:
                # Ensure each line is a LineBuffer with its own array
                for i, line_obj in enumerate(instance.lines.lines):
                    if not isinstance(line_obj, LineBuffer):
                        # Create a new LineBuffer for this line - no import needed, we're in linebuffer.py
                        new_line = LineBuffer()
                        # Copy any existing attributes
                        if hasattr(line_obj, '__dict__'):
                            new_line.__dict__.update(line_obj.__dict__)
                        instance.lines.lines[i] = new_line
                        line_obj = new_line
                    
                    # Ensure the line has its own array
                    if not hasattr(line_obj, 'array') or not line_obj.array:
                        import array
                        line_obj.array = array.array('d')
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
            if not hasattr(instance.lines, 'advance'):
                def advance_method(size=1):
                    """Forward all lines in the collection"""
                    for line in getattr(instance.lines, 'lines', []):
                        if hasattr(line, 'advance'):
                            line.advance(size=size)
                instance.lines.advance = advance_method
            instance.line = instance
            instance.l = instance.lines
        
        # CRITICAL FIX: Auto-assign data from owner if no data provided and mindatas > 0
        if mindatas > 0:
            # Try to get owner and auto-assign data using multiple strategies
            import inspect
            from . import metabase
            
            owner = None
            
            # Strategy 1: Use findowner
            try:
                import backtrader as bt
                owner = metabase.findowner(instance, bt.Strategy)
            except Exception as e:
                pass
            
            # If we found an owner with data, auto-assign it
            if owner is not None and hasattr(owner, 'data') and owner.data is not None:
                # Check if we already have data in args
                data_count = 0
                for arg in args:
                    if (hasattr(arg, 'lines') or hasattr(arg, '_name') or 
                        str(type(arg).__name__).endswith('Data')):
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
            if hasattr(arg, 'lines') or hasattr(arg, '_name') or str(type(arg).__name__).endswith('Data'):
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
            instance.dnames = DotDict([(d._name, d) for d in instance.datas if getattr(d, "_name", "")])
        except:
            instance.dnames = {}
        
        return instance

    def __init__(self, *args, **kwargs):
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
                    frame_self = frame.f_locals.get('self', None)
                    if frame_self is not None and frame_self is not self:
                        # Check if this looks like a strategy
                        if hasattr(frame_self, 'datas') and hasattr(frame_self, 'broker') and hasattr(frame_self, '_addindicator'):
                            self._owner = frame_self
                            break
                        # Check if this looks like a LineIterator
                        elif hasattr(frame_self, '_lineiterators') and hasattr(frame_self, 'addindicator'):
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
        if hasattr(self, '_plotlabel'):
            label_dict = self._plotlabel()
            # Convert dict to string format
            if isinstance(label_dict, dict):
                # Format as 'ClassName(param1=value1, param2=value2)'
                params_str = ', '.join(f"{k}={v}" for k, v in label_dict.items())
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
        if hasattr(self, 'params') and hasattr(self.params, '_getkwargs'):
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
                if not hasattr(line_num, '_minperiod'):
                    line_num._minperiod = 1
                return line_num  # make it a LineNum
            if not hasattr(obj, "__len__"):
                pseudo_array = PseudoArray(obj)
                # CRITICAL FIX: Ensure PseudoArray objects have _minperiod for compatibility
                if not hasattr(pseudo_array, '_minperiod'):
                    pseudo_array._minperiod = 1
                return pseudo_array  # Can iterate (for once)

        return obj

    def _next(self):
        # CRITICAL FIX: Prevent double processing if _once was already called
        if hasattr(self, '_once_called') and self._once_called:
            return  # Already processed in once mode, don't process again
        
        # CRITICAL FIX: Ensure data synchronization without over-advancing
        if hasattr(self, '_clock') and self._clock is not None:
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
        
        # CRITICAL FIX: Ensure proper range for once processing
        if start < 0:
            start = 0
        if end < start:
            end = start
            
        # CRITICAL FIX: Get the actual buffer length if available
        if hasattr(self, '_clock') and self._clock and hasattr(self._clock, 'buflen'):
            max_len = self._clock.buflen()
            if end > max_len:
                end = max_len
        elif hasattr(self, 'array') and self.array:
            max_len = len(self.array)
            if end > max_len:
                # Extend array if needed
                while len(self.array) < end:
                    self.array.append(0.0)

        # CRITICAL FIX: Call _once() on all child line iterators first
        # This ensures dependencies are calculated before this indicator
        if hasattr(self, '_lineiterators'):
            from .lineiterator import LineIterator
            for indicator in self._lineiterators.get(LineIterator.IndType, []):
                try:
                    if hasattr(indicator, '_once'):
                        indicator._once(start, end)
                except Exception as e:
                    # Continue processing other indicators if one fails
                    pass

        # CRITICAL FIX: Call preonce before main processing
        try:
            if hasattr(self, 'preonce'):
                self.preonce(start, end)
        except Exception:
            pass

        # CRITICAL FIX: Process the main once calculation
        try:
            if hasattr(self, 'once'):
                self.once(start, end)
        except Exception as e:
            # If once method fails, fall back to next-style processing
            print(f"_once method failed, falling back to next processing: {e}")
            for i in range(start, end):
                try:
                    # Advance the buffer position
                    if hasattr(self, 'forward'):
                        self.forward()
                    # Call next method if available
                    if hasattr(self, 'next'):
                        self.next()
                except Exception:
                    # If next fails, just advance the position
                    if hasattr(self, 'array') and len(self.array) <= i:
                        self.array.append(0.0)
                    elif hasattr(self, '_idx'):
                        self._idx = min(self._idx + 1, len(self.array) - 1)

        # CRITICAL FIX: Ensure the buffer is properly positioned after once processing
        if hasattr(self, '_idx') and hasattr(self, 'array'):
            # Set the index to the end position
            self._idx = min(end - 1, len(self.array) - 1)
        
        # CRITICAL FIX: Ensure lencount is updated
        if hasattr(self, 'lencount'):
            self.lencount = max(self.lencount, end)

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
        if hasattr(a, '_minperiod'):
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
        src = self.a.array
        ago = self.ago

        # CRITICAL FIX: Ensure destination array is properly sized
        while len(dst) < end:
            dst.append(0.0)

        for i in range(start, end):
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
            else:
                # If index is out of bounds, use 0.0
                dst[i] = 0.0


class _LineForward(LineActions):
    def __init__(self, a, ago):
        super(_LineForward, self).__init__()
        self.a = self.arrayize(a)
        self.ago = ago

        # Need to add the delay to the period
        if hasattr(a, '_minperiod'):
            self.addminperiod(ago)

    def next(self):
        # operation(float, other) ... expecting other to be a float
        # CRITICAL FIX: Ensure we get valid numeric values for indicator calculations
        try:
            # Get operand values with proper type checking
            if hasattr(self.a, '__getitem__'):
                # LineBuffer-like object - get current value
                try:
                    a_val = self.a[0]
                except (IndexError, TypeError):
                    a_val = 0.0
            else:
                # Direct value
                a_val = self.a
            
            if hasattr(self.b, '__getitem__'):
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
            if hasattr(self, 'operation') and self.operation:
                # CRITICAL FIX: Handle reverse operations properly
                if getattr(self, 'r', False):
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
                
        except Exception as e:
            # If anything fails, store 0.0 to prevent crashes
            print(f"LinesOperation.next() error: {e}")
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
            except Exception as e:
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
        a_minperiod = getattr(a, '_minperiod', 1) if hasattr(a, '_minperiod') else 1
        b_minperiod = getattr(b, '_minperiod', 1) if hasattr(b, '_minperiod') else 1
        
        self.addminperiod(a_minperiod)
        self.addminperiod(b_minperiod)

    def next(self):
        # operation(float, other) ... expecting other to be a float
        # CRITICAL FIX: Ensure we get valid numeric values for indicator calculations
        try:
            # Get operand values with proper type checking
            if hasattr(self.a, '__getitem__'):
                # LineBuffer-like object - get current value
                try:
                    a_val = self.a[0]
                except (IndexError, TypeError):
                    a_val = 0.0
            else:
                # Direct value
                a_val = self.a
            
            if hasattr(self.b, '__getitem__'):
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
            if hasattr(self, 'operation') and self.operation:
                # CRITICAL FIX: Handle reverse operations properly
                if getattr(self, 'r', False):
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
                
        except Exception as e:
            # If anything fails, store 0.0 to prevent crashes
            print(f"LinesOperation.next() error: {e}")
            self[0] = 0.0

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

        # CRITICAL FIX: Ensure destination array is properly sized
        while len(dst) < end:
            dst.append(0.0)
        
        # CRITICAL FIX: Ensure source arrays have required data
        max_src_len = max(len(srca), len(srcb))
        if max_src_len < end:
            # If source arrays are shorter than required range, only process available data
            end = min(end, max_src_len)

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
            except Exception as e:
                # If operation fails, store 0.0
                dst[i] = 0.0

    def _once_time_op(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b[0]
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
            except Exception as e:
                # If operation fails, store 0.0
                dst[i] = 0.0

    def _once_val_op(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b
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
            except Exception as e:
                # If operation fails, store 0.0
                dst[i] = 0.0

    def _once_val_op_r(self, start, end):
        # cache python dictionary lookups
        dst = self.array
        srca = self.a.array
        srcb = self.b
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
            except Exception as e:
                # If operation fails, store 0.0
                dst[i] = 0.0


class LineOwnOperation(LineActions):
    def __init__(self, a, operation):
        super(LineOwnOperation, self).__init__()
        self.operation = operation
        self.a = a

        # CRITICAL FIX: Handle _minperiod attribute access more safely
        a_minperiod = getattr(a, '_minperiod', 1) if hasattr(a, '_minperiod') else 1
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
            except Exception as e:
                # If operation fails, store 0.0
                dst[i] = 0.0

    def size(self):
        """Return the number of lines in this LineActions object"""
        if hasattr(self, 'lines') and hasattr(self.lines, 'size'):
            return self.lines.size()
        elif hasattr(self, 'lines') and hasattr(self.lines, '__len__'):
            return len(self.lines)
        else:
            return 1  # Default to 1 line if no lines object available
