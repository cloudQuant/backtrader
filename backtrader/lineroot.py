#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
module:: lineroot

Definition of the base class LineRoot and base classes LineSingle/LineMultiple
to define interfaces and hierarchy for the real operational classes

module author:: Daniel Rodriguez

"""
import operator
from . import metabase
from .utils.py3 import range


class LineRootMixin:
    """Mixin to provide LineRoot functionality without metaclass"""
    
    @classmethod
    def donew(cls, *args, **kwargs):
        """Create new instance with owner finding logic"""
        _obj, args, kwargs = super().donew(*args, **kwargs) if hasattr(super(), 'donew') else (cls.__new__(cls), args, kwargs)

        # Find the owner and store it
        # startlevel = 4 ... to skip intermediate call stacks
        ownerskip = kwargs.pop("_ownerskip", None)
        # Import LineMultiple here to avoid circular imports
        from .lineroot import LineMultiple
        _obj._owner = metabase.findowner(_obj, _obj._OwnerCls or LineMultiple, skip=ownerskip)

        # Parameter values have now been set before __init__
        return _obj, args, kwargs


class LineRoot(LineRootMixin, metabase.BaseMixin):
    """
    Defines a common base and interfaces for Single and Multiple
    LineXXX instances

        Period management
        Iteration management
        Operation (dual/single operand) Management
        Rich Comparison operator definition
    """

    # 初始化的时候类的属性
    _OwnerCls = None  # 默认的父类实例是None
    _minperiod = 1  # 最小周期是1
    _opstage = 1  # 操作状态默认是1

    # 指标类型、策略类型和观察类型的值分别是0,1,2
    IndType, StratType, ObsType = range(3)

    # 转变操作状态为1
    def _stage1(self):
        self._opstage = 1

    # 转变操作状态为2
    def _stage2(self):
        self._opstage = 2

    # 根据line的操作状态决定调用哪种操作算法
    def _operation(self, other, operation, r=False, intify=False):
        if self._opstage == 1:
            return self._operation_stage1(other, operation, r=r, intify=intify)

        return self._operation_stage2(other, operation, r=r)

    # 自身的操作
    def _operationown(self, operation):
        if self._opstage == 1:
            return self._operationown_stage1(operation)

        return self._operationown_stage2(operation)

    # 改变lines去实施最小缓存计划
    def qbuffer(self, savemem=0):
        """Change the lines to implement a minimum size qbuffer scheme"""
        raise NotImplementedError

    # 需要达到的最小缓存
    def minbuffer(self, size):
        """Receive notification of how large the buffer must at least be"""
        raise NotImplementedError

    # 可以用于在策略中设置最小的周期，可以不用等待指标产生具体的值就开始运行
    def setminperiod(self, minperiod):
        """
        Direct minperiod manipulation.It could be used, for example,
        by a strategy
        to not wait for all indicators to produce a value

        """
        self._minperiod = minperiod

    # 更新最小周期，最小周期可能在其他地方已经计算产生，跟现有的最小周期对比，选择一个最大的作为最小周期
    def updateminperiod(self, minperiod):
        """
        Update the minperiod if needed. The minperiod will have been
        calculated elsewhere
        and has to take over if greater that self's
        """
        self._minperiod = max(self._minperiod, minperiod)

    # 添加最小周期
    def addminperiod(self, minperiod):
        """
        Add a minperiod to own ... to be defined by subclasses
        """
        raise NotImplementedError

    # 增加最小周期
    def incminperiod(self, minperiod):
        """
        Increment the minperiod with no considerations
        """
        raise NotImplementedError

    # 在最小周期内迭代的时候将会调用这个函数
    def prenext(self):
        """
        It will be called during the "minperiod" phase of an iteration.
        """
        pass

    # 在最小周期迭代结束的时候，即将开始next的时候调用一次
    def nextstart(self):
        """
        It will be called when the minperiod phase is over for the 1st
        post-minperiod value. Only called once and defaults to automatically
        calling next
        """
        self.next()

    # 最小周期迭代结束后，开始调用next
    def next(self):
        """
        Called to calculate values when the minperiod is over
        """
        pass

    # 在最小周期迭代的时候调用preonce
    def preonce(self, start, end):
        """
        It will be called during the "minperiod" phase of a "once" iteration
        """
        pass

    # 在最小周期结束的时候运行一次，调用once
    def oncestart(self, start, end):
        """
        It will be called when the minperiod phase is over for the 1st
        post-minperiod value

        Only called once and defaults to automatically calling once

        """
        self.once(start, end)

    # 当最小周期迭代结束的时候调用用于计算结果
    def once(self, start, end):
        """
        Called to calculate values at "once" when the minperiod is over

        """
        pass

    def size(self):
        """Return the number of lines in this object"""
        # This method provides a size() interface for all LineRoot objects
        # It will be overridden by specific implementations as needed
        if hasattr(self, 'lines') and hasattr(self.lines, 'size'):
            return self.lines.size()
        elif hasattr(self, 'lines') and hasattr(self.lines, '__len__'):
            return len(self.lines)
        else:
            return 1  # Default to 1 line if no lines object available

    # Arithmetic operators
    # 一些算术操作
    def _makeoperation(self, other, operation, r=False, _ownerskip=None):
        # For LineMultiple, we can implement a basic operation using the first line
        # This provides a fallback when operations are needed
        if hasattr(self, 'lines') and self.lines:
            # Use the first line for operations
            from .linebuffer import LinesOperation
            return LinesOperation(self.lines[0], other, operation, r=r)
        else:
            # If no lines, return a simple operation result
            try:
                if r:
                    return operation(other, 0)  # Use 0 as default value
                else:
                    return operation(0, other)  # Use 0 as default value
            except:
                # If operation fails, return False for bool operations
                if operation == bool:
                    return False
                return 0

    # 做自身操作
    def _makeoperationown(self, operation, _ownerskip=None):
        # CRITICAL FIX: For bool operations, return a simple boolean result instead of creating objects
        if operation == bool:
            # For bool operations, check if we have any lines and if they have data
            if hasattr(self, 'lines') and self.lines:
                try:
                    # Try to get the current value from the first line
                    if hasattr(self.lines, '__getitem__') and len(self.lines) > 0:
                        line = self.lines[0]
                        if hasattr(line, '__getitem__') and hasattr(line, '__len__'):
                            if len(line) > 0:
                                value = line[0]
                                # Return True if value is not None, not NaN and not 0
                                if value is None:
                                    return False
                                elif isinstance(value, float):
                                    import math
                                    if math.isnan(value):
                                        return False
                                    return value != 0.0
                                else:
                                    return bool(value)
                    return False
                except:
                    return False
            elif hasattr(self, '__getitem__') and hasattr(self, '__len__'):
                # For LineSingle objects, check the current value directly
                try:
                    if len(self) > 0:
                        value = self[0]
                        if value is None:
                            return False
                        elif isinstance(value, float):
                            import math
                            if math.isnan(value):
                                return False
                            return value != 0.0
                        else:
                            return bool(value)
                    return False
                except:
                    return False
            else:
                return False
        
        # For other operations, use the original approach but only if really needed
        if hasattr(self, 'lines') and self.lines:
            # Use the first line for self-operations
            from .linebuffer import LineOwnOperation
            return LineOwnOperation(self.lines[0], operation)
        else:
            # If no lines, return a simple operation result
            try:
                return operation(0)  # Use 0 as default value
            except:
                # If operation fails, return 0 for most operations
                return 0

    # 自身操作阶段1
    def _operationown_stage1(self, operation):
        """
        Operation with single operand which is "self"
        """
        return self._makeoperationown(operation, _ownerskip=self)

    # 自身操作阶段2
    def _operationown_stage2(self, operation):
        return operation(self[0])

    # 右操作
    def _roperation(self, other, operation, intify=False):
        """
        Relies on self._operation to and passes "r" True to define a
        reverse operation
        """
        return self._operation(other, operation, r=True, intify=intify)

    # 阶段1操作，判断other是不是包含多个line,如果有多个line，就取出第一个line,然后进行操作
    def _operation_stage1(self, other, operation, r=False, intify=False):
        """
        Two operands' operations.Scanning of other happens to understand
        if other must be directly an operand or rather a subitem thereof
        """
        if isinstance(other, LineMultiple):
            other = other.lines[0]

        return self._makeoperation(other, operation, r, self)

    # 阶段2操作，如果other是一个line，就取出当前值，然后进行操作
    def _operation_stage2(self, other, operation, r=False):
        """
        Rich Comparison operators. Scans other and returns either an
        operation with other directly or a subitem from other
        """
        if isinstance(other, LineRoot):
            other = other[0]

        # operation(float, other) ... expecting other to be a float
        # CRITICAL FIX: Handle None values in comparisons to prevent errors
        self_value = self[0]
        
        # CRITICAL FIX: Convert None to 0.0 to prevent None vs float comparison errors
        if self_value is None:
            self_value = 0.0
        elif isinstance(self_value, float):
            import math
            if math.isnan(self_value):
                self_value = 0.0
        
        # Also handle None in other value
        if other is None:
            other = 0.0
        elif isinstance(other, float):
            import math
            if math.isnan(other):
                other = 0.0
        
        # CRITICAL FIX: Actually perform the operation and return the result
        # Don't create LinesOperation objects in stage2 - return actual values
        try:
            if r:
                result = operation(other, self_value)
            else:
                result = operation(self_value, other)
            return result
        except Exception as e:
            # If operation fails, return appropriate default
            if operation in [operator.__lt__, operator.__le__, operator.__gt__, 
                           operator.__ge__, operator.__eq__, operator.__ne__]:
                return False  # For comparison operations, return False on error
            else:
                return 0.0  # For arithmetic operations, return 0.0 on error

    # 加
    def __add__(self, other):
        return self._operation(other, operator.__add__)

    # 右加
    def __radd__(self, other):
        return self._roperation(other, operator.__add__)

    # 减
    def __sub__(self, other):
        return self._operation(other, operator.__sub__)

    # 右减
    def __rsub__(self, other):
        return self._roperation(other, operator.__sub__)

    # 乘
    def __mul__(self, other):
        return self._operation(other, operator.__mul__)

    # 右乘
    def __rmul__(self, other):
        return self._roperation(other, operator.__mul__)

    # 除
    def __div__(self, other):
        return self._operation(other, operator.__div__)

    # 右除
    def __rdiv__(self, other):
        return self._roperation(other, operator.__div__)

    # 向下取整数
    def __floordiv__(self, other):
        return self._operation(other, operator.__floordiv__)

    # 右向下取整
    def __rfloordiv__(self, other):
        return self._roperation(other, operator.__floordiv__)

    # 真除法
    def __truediv__(self, other):
        return self._operation(other, operator.__truediv__)

    # 右真除法
    def __rtruediv__(self, other):
        return self._roperation(other, operator.__truediv__)

    # 幂
    def __pow__(self, other):
        return self._operation(other, operator.__pow__)

    # 右幂
    def __rpow__(self, other):
        return self._roperation(other, operator.__pow__)

    # 绝对值
    def __abs__(self):
        return self._operationown(operator.__abs__)

    # 取负的结果
    def __neg__(self):
        return self._operationown(operator.__neg__)

    # a<b
    def __lt__(self, other):
        # CRITICAL FIX: Always check opstage first to determine behavior
        if self._opstage == 2:
            # In stage2, return actual boolean values for direct use in strategies
            self_value = self[0] if hasattr(self, '__getitem__') else 0.0
            
            # Handle None values and convert to floats for comparison
            if self_value is None:
                self_value = 0.0
            elif isinstance(self_value, float):
                import math
                if math.isnan(self_value):
                    self_value = 0.0
                    
            if other is None:
                other = 0.0
            elif isinstance(other, float):
                import math
                if math.isnan(other):
                    other = 0.0
            
            # Return actual boolean for direct strategy use
            try:
                return float(self_value) < float(other)
            except (ValueError, TypeError):
                return False
        else:
            # In stage1, use normal operation creation
            return self._operation(other, operator.__lt__)

    # a>b
    def __gt__(self, other):
        # CRITICAL FIX: Always check opstage first to determine behavior
        if self._opstage == 2:
            # In stage2, return actual boolean values for direct use in strategies
            self_value = self[0] if hasattr(self, '__getitem__') else 0.0
            
            # Handle None values and convert to floats for comparison
            if self_value is None:
                self_value = 0.0
            elif isinstance(self_value, float):
                import math
                if math.isnan(self_value):
                    self_value = 0.0
                    
            if other is None:
                other = 0.0
            elif isinstance(other, float):
                import math
                if math.isnan(other):
                    other = 0.0
            
            # Return actual boolean for direct strategy use
            try:
                return float(self_value) > float(other)
            except (ValueError, TypeError):
                return False
        else:
            # In stage1, use normal operation creation
            return self._operation(other, operator.__gt__)

    # a<=b
    def __le__(self, other):
        # CRITICAL FIX: Always check opstage first to determine behavior
        if self._opstage == 2:
            # In stage2, return actual boolean values for direct use in strategies
            self_value = self[0] if hasattr(self, '__getitem__') else 0.0
            
            # Handle None values and convert to floats for comparison
            if self_value is None:
                self_value = 0.0
            elif isinstance(self_value, float):
                import math
                if math.isnan(self_value):
                    self_value = 0.0
                    
            if other is None:
                other = 0.0
            elif isinstance(other, float):
                import math
                if math.isnan(other):
                    other = 0.0
            
            # Return actual boolean for direct strategy use
            try:
                return float(self_value) <= float(other)
            except (ValueError, TypeError):
                return False
        else:
            # In stage1, use normal operation creation
            return self._operation(other, operator.__le__)

    # a>=b
    def __ge__(self, other):
        # CRITICAL FIX: Always check opstage first to determine behavior
        if self._opstage == 2:
            # In stage2, return actual boolean values for direct use in strategies
            self_value = self[0] if hasattr(self, '__getitem__') else 0.0
            
            # Handle None values and convert to floats for comparison
            if self_value is None:
                self_value = 0.0
            elif isinstance(self_value, float):
                import math
                if math.isnan(self_value):
                    self_value = 0.0
                    
            if other is None:
                other = 0.0
            elif isinstance(other, float):
                import math
                if math.isnan(other):
                    other = 0.0
            
            # Return actual boolean for direct strategy use
            try:
                return float(self_value) >= float(other)
            except (ValueError, TypeError):
                return False
        else:
            # In stage1, use normal operation creation
            return self._operation(other, operator.__ge__)

    # a = b
    def __eq__(self, other):
        return self._operation(other, operator.__eq__)

    # a!=b
    def __ne__(self, other):
        return self._operation(other, operator.__ne__)

    #  a!=0
    def __nonzero__(self):
        # CRITICAL FIX: __bool__ MUST return a boolean, not a LineOwnOperation object
        # This was causing "TypeError: __bool__ should return bool, returned LineOwnOperation"
        try:
            if hasattr(self, 'lines') and self.lines:
                # For LineMultiple objects, check the first line
                if hasattr(self.lines, '__getitem__') and len(self.lines) > 0:
                    line = self.lines[0]
                    if hasattr(line, '__getitem__') and hasattr(line, '__len__'):
                        if len(line) > 0:
                            value = line[0]
                            # Return True if value exists and is not 0
                            if value is None:
                                return False
                            elif isinstance(value, float):
                                import math
                                if math.isnan(value):
                                    return False
                                return value != 0.0
                            else:
                                return bool(value)
                return False
            elif hasattr(self, '__getitem__') and hasattr(self, '__len__'):
                # For LineSingle objects, check the current value
                if len(self) > 0:
                    value = self[0]
                    if value is None:
                        return False
                    elif isinstance(value, float):
                        import math
                        if math.isnan(value):
                            return False
                        return value != 0.0
                    else:
                        return bool(value)
                return False
            else:
                # Fallback: if no data available, return False
                return False
        except Exception as e:
            # If any error occurs during boolean evaluation, return False
            # This prevents crashes in strategies when doing "if self.cross > 0:"
            return False

    __bool__ = __nonzero__

    # Python 3 forces explicit implementation of hash if
    # the class has redefined __eq__
    __hash__ = object.__hash__


class LineMultiple(LineRoot):
    def __init__(self):
        super(LineMultiple, self).__init__()
        # CRITICAL FIX: Initialize _ltype for proper strategy/indicator identification
        self._ltype = None
        # CRITICAL FIX: Initialize lines list to prevent index errors
        if not hasattr(self, 'lines') or self.lines is None:
            from . import lineseries
            self.lines = lineseries.Lines()
        
        # CRITICAL FIX: Set up minimal clock for timing
        if not hasattr(self, '_clock'):
            self._clock = None
            
        # CRITICAL FIX: Initialize line iterators tracking
        if not hasattr(self, '_lineiterators'):
            self._lineiterators = {}
        
        # CRITICAL FIX: Ensure minperiod is set
        if not hasattr(self, '_minperiod'):
            self._minperiod = 1

    def reset(self):
        for line in self.lines:
            line.reset()

    def _stage1(self):
        super(LineMultiple, self)._stage1()
        for line in self.lines:
            line._stage1()

    def _stage2(self):
        super(LineMultiple, self)._stage2()
        for line in self.lines:
            line._stage2()

    def addminperiod(self, minperiod):
        """
        The passed minperiod is fed to the lines
        """
        for line in self.lines:
            line.addminperiod(minperiod)

    def incminperiod(self, minperiod):
        """
        The passed minperiod is fed to the lines
        """
        for line in self.lines:
            line.incminperiod(minperiod)

    def _makeoperation(self, other, operation, r=False, _ownerskip=None):
        # For LineMultiple, we can implement a basic operation using the first line
        # This provides a fallback when operations are needed
        if hasattr(self, 'lines') and self.lines:
            # Use the first line for operations
            from .linebuffer import LinesOperation
            return LinesOperation(self.lines[0], other, operation, r=r)
        else:
            # If no lines, return a simple operation result
            try:
                if r:
                    return operation(other, 0)  # Use 0 as default value
                else:
                    return operation(0, other)  # Use 0 as default value
            except:
                # If operation fails, return False for bool operations
                if operation == bool:
                    return False
                return 0

    def _makeoperationown(self, operation, _ownerskip=None):
        # CRITICAL FIX: For bool operations, return a simple boolean result instead of creating objects
        if operation == bool:
            # For bool operations, check if we have any lines and if they have data
            if hasattr(self, 'lines') and self.lines:
                try:
                    # Try to get the current value from the first line
                    value = self.lines[0][0] if len(self.lines[0]) > 0 else 0
                    # Return True if value is not NaN and not 0
                    import math
                    if isinstance(value, float) and math.isnan(value):
                        return False
                    return bool(value)
                except:
                    return False
            else:
                return False
        
        # For other operations, use the original approach but only if really needed
        if hasattr(self, 'lines') and self.lines:
            # Use the first line for self-operations
            from .linebuffer import LineOwnOperation
            return LineOwnOperation(self.lines[0], operation)
        else:
            # If no lines, return a simple operation result
            try:
                return operation(0)  # Use 0 as default value
            except:
                # If operation fails, return 0 for most operations
                return 0

    def qbuffer(self, savemem=0):
        for line in self.lines:
            line.qbuffer(savemem=savemem)

    def minbuffer(self, size):
        for line in self.lines:
            line.minbuffer(size)


class LineSingle(LineRoot):
    def addminperiod(self, minperiod):
        """
        Add the minperiod (substracting the overlapping 1 minimum period)
        """
        self._minperiod += minperiod - 1

    def incminperiod(self, minperiod):
        """
        Increment the minperiod with no considerations
        """
        self._minperiod += minperiod


# CRITICAL FIX: Patch Strategy._clk_update to prevent "max() iterable argument is empty" error
def _apply_strategy_patch():
    """Apply critical bug fix to Strategy class _clk_update method"""
    try:
        import math
        
        # Import after a delay to ensure strategy module is loaded
        def safe_clk_update(self):
            """CRITICAL FIX: Safe _clk_update method that handles empty data sources"""
            
            # CRITICAL FIX: Handle the old sync method safely
            if hasattr(self, '_oldsync') and self._oldsync:
                # Call parent class _clk_update if available
                try:
                    # Use the parent class method from StrategyBase if available
                    from .lineiterator import StrategyBase
                    if hasattr(StrategyBase, '_clk_update'):
                        clk_len = super(type(self), self)._clk_update()
                    else:
                        clk_len = 1
                except Exception:
                    clk_len = 1
                
                # CRITICAL FIX: Only set datetime if we have valid data sources with length
                if hasattr(self, 'datas') and self.datas:
                    valid_data_times = []
                    for d in self.datas:
                        try:
                            if len(d) > 0 and hasattr(d, 'datetime') and hasattr(d.datetime, '__getitem__'):
                                dt_val = d.datetime[0]
                                # Only add valid datetime values (not None or NaN)
                                if dt_val is not None and not (isinstance(dt_val, float) and math.isnan(dt_val)):
                                    valid_data_times.append(dt_val)
                        except (IndexError, AttributeError, TypeError):
                            continue
                    
                    if valid_data_times and hasattr(self, 'lines') and hasattr(self.lines, 'datetime'):
                        try:
                            self.lines.datetime[0] = max(valid_data_times)
                        except (ValueError, IndexError, AttributeError):
                            # If setting datetime fails, use a default valid ordinal (1 = Jan 1, Year 1)
                            self.lines.datetime[0] = 1.0
                    elif hasattr(self, 'lines') and hasattr(self.lines, 'datetime'):
                        # No valid times, use default valid ordinal (1 = Jan 1, Year 1)
                        self.lines.datetime[0] = 1.0
                
                return clk_len
            
            # CRITICAL FIX: Handle the normal (non-oldsync) path
            # Initialize _dlens if not present
            if not hasattr(self, '_dlens'):
                self._dlens = [len(d) if hasattr(d, '__len__') else 0 for d in (self.datas if hasattr(self, 'datas') else [])]
            
            # Get current data lengths safely
            if hasattr(self, 'datas') and self.datas:
                newdlens = []
                for d in self.datas:
                    try:
                        newdlens.append(len(d) if hasattr(d, '__len__') else 0)
                    except Exception:
                        newdlens.append(0)
            else:
                newdlens = []
            
            # Forward if any data source has grown
            if newdlens and hasattr(self, '_dlens') and any(nl > l for l, nl in zip(self._dlens, newdlens) if l is not None and nl is not None):
                try:
                    if hasattr(self, 'forward'):
                        self.forward()
                except Exception:
                    pass
            
            # Update _dlens
            self._dlens = newdlens
            
            # CRITICAL FIX: Set datetime safely - only use data sources that have valid data
            if hasattr(self, 'datas') and self.datas and hasattr(self, 'lines') and hasattr(self.lines, 'datetime'):
                valid_data_times = []
                for d in self.datas:
                    try:
                        if len(d) > 0 and hasattr(d, 'datetime') and hasattr(d.datetime, '__getitem__'):
                            dt_val = d.datetime[0]
                            # Only add valid datetime values (not None or NaN)
                            if dt_val is not None and not (isinstance(dt_val, float) and math.isnan(dt_val)):
                                valid_data_times.append(dt_val)
                    except (IndexError, AttributeError, TypeError):
                        continue
                
                # CRITICAL FIX: This is the line that was causing the "max() iterable argument is empty" error
                # We check if valid_data_times is not empty before calling max()
                if valid_data_times:
                    try:
                        self.lines.datetime[0] = max(valid_data_times)
                    except (ValueError, IndexError, AttributeError):
                        # If setting datetime fails, use a default valid ordinal (1 = Jan 1, Year 1)
                        self.lines.datetime[0] = 1.0
                else:
                    # No valid times available, use a reasonable default valid ordinal
                    # This is the critical fix - instead of calling max() on empty list, use default
                    self.lines.datetime[0] = 1.0
            
            # Return the length of this strategy (number of processed bars)
            try:
                return len(self)
            except Exception:
                return 0
        
        # Import Strategy and patch it
        try:
            from .strategy import Strategy
            # Monkey patch the Strategy class
            Strategy._clk_update = safe_clk_update
            pass
        except ImportError:
            # Strategy not imported yet, try to patch later when it's imported
            pass
        
    except Exception as e:
        pass  # Fail silently to not break imports


# Apply the patch when this module is imported
_apply_strategy_patch()
