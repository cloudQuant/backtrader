#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from .utils.py3 import range

from .lineiterator import LineIterator, IndicatorBase
from .lineseries import LineSeriesMaker, Lines
from .metabase import AutoInfoClass


# Simple indicator registry to replace MetaIndicator functionality
class IndicatorRegistry:
    """Registry to manage indicator classes and provide caching functionality"""
    _indcol = dict()
    _icache = dict()
    _icacheuse = False

    @classmethod
    def register(cls, name, indicator_cls):
        """Register an indicator class"""
        if not name.startswith("_") and name != "Indicator":
            cls._indcol[name] = indicator_cls

    @classmethod  
    def cleancache(cls):
        """Clear the indicator cache"""
        cls._icache = dict()

    @classmethod
    def usecache(cls, onoff):
        """Enable or disable caching"""
        cls._icacheuse = onoff

    @classmethod
    def get_cached_or_create(cls, indicator_cls, *args, **kwargs):
        """Get cached indicator instance or create new one"""
        if not cls._icacheuse:
            return indicator_cls(*args, **kwargs)

        # implement a cache to avoid duplicating lines actions
        ckey = (indicator_cls, tuple(args), tuple(kwargs.items()))  # tuples hashable
        try:
            return cls._icache[ckey]
        except TypeError:  # something is not hashable
            return indicator_cls(*args, **kwargs)
        except KeyError:
            pass  # hashable but not in the cache

        _obj = indicator_cls(*args, **kwargs)
        return cls._icache.setdefault(ckey, _obj)


# 指标类 - refactored to remove metaclass usage
class Indicator(IndicatorBase):
    # line的类型被设置为指标
    _ltype = LineIterator.IndType
    # 输出到csv文件被设置成False
    csv = False
    # Track if this is an aliased indicator
    aliased = False

    def __init_subclass__(cls, **kwargs):
        """Handle subclass registration without metaclass"""
        super().__init_subclass__(**kwargs)
        
        # Register subclasses automatically  
        if not cls.aliased and cls.__name__ != "Indicator" and not cls.__name__.startswith("_"):
            IndicatorRegistry.register(cls.__name__, cls)
            
            # Handle aliases - register them to the indicators module
            if hasattr(cls, 'alias') and cls.alias:
                import sys
                indicators_module = sys.modules.get('backtrader.indicators')
                if indicators_module:
                    # Set the main class name
                    setattr(indicators_module, cls.__name__, cls)
                    # Set all aliases - handle both tuple and list formats
                    aliases = cls.alias
                    if isinstance(aliases, (list, tuple)):
                        for alias in aliases:
                            if isinstance(alias, str):
                                setattr(indicators_module, alias, cls)

        # Check if next and once have both been overridden
        next_over = cls.next != IndicatorBase.next
        once_over = cls.once != IndicatorBase.once
        
        if next_over and not once_over:
            # No -> need pointer movement to once simulation via next
            cls.once = cls.once_via_next
            cls.preonce = cls.preonce_via_prenext
            cls.oncestart = cls.oncestart_via_nextstart

    # Cache related methods - moved from metaclass
    @classmethod
    def cleancache(cls):
        """Clear the indicator cache"""
        IndicatorRegistry.cleancache()

    @classmethod
    def usecache(cls, onoff):
        """Enable or disable caching""" 
        IndicatorRegistry.usecache(onoff)

    # 当数据小于当前时间的时候，数据向前移动size
    def advance(self, size=1):
        # Need intercepting this call to support datas with
        # different lengths (timeframes)
        if len(self) < len(self._clock):
            self.lines.advance(size=size)

    # 如果prenext重写了，但是preonce没有被重写，通常的实施方法
    def preonce_via_prenext(self, start, end):
        # generic implementation if prenext is overridden but preonce is not
        # 从start到end进行循环
        for i in range(start, end):
            # 数据每次增加
            for data in self.datas:
                data.advance()
            # 指标每次增加
            for indicator in self._lineiterators[LineIterator.IndType]:
                indicator.advance()
            # 自身增加
            self.advance()
            # 每次调用下prenext
            self.prenext()

    # 如果nextstart重写了，但是oncestart没有重写，需要做的操作，和上一个比较类似
    def oncestart_via_nextstart(self, start, end):
        # nextstart has been overriden, but oncestart has not and the code is
        # here. call the overriden nextstart
        for i in range(start, end):
            for data in self.datas:
                data.advance()

            for indicator in self._lineiterators[LineIterator.IndType]:
                indicator.advance()

            self.advance()
            self.nextstart()

    # next重写了，但是once没有重写，需要的操作
    def once_via_next(self, start, end):
        # Not overridden, next must be there ...
        for i in range(start, end):
            for data in self.datas:
                data.advance()

            for indicator in self._lineiterators[LineIterator.IndType]:
                indicator.advance()

            self.advance()
            self.next()


# 指标画出多条line的类，下面这两个类，在整个项目中并没有使用到
class MtLinePlotterIndicator(Indicator.__class__):
    def donew(cls, *args, **kwargs):
        # line的名字
        lname = kwargs.pop("name")
        # 类的名字
        name = cls.__name__
        # 获取cls的liens,如果没有，就返回Lines
        lines = getattr(cls, "lines", Lines)
        # 对lines进行相应的操作
        cls.lines = lines._derive(name, (lname,), 0, [])
        # plotlines响应的操作
        plotlines = AutoInfoClass
        newplotlines = dict()
        newplotlines.setdefault(lname, dict())
        cls.plotlines = plotlines._derive(name, newplotlines, [], recurse=True)

        # Create the object and set the params in place
        # 创建具体的类并设置参数
        _obj, args, kwargs = super(MtLinePlotterIndicator, cls).donew(*args, **kwargs)
        # 设置_obj的owner属性值
        _obj.owner = _obj.data.owner._clock
        # 增加另一条linebuffer
        _obj.data.lines[0].addbinding(_obj.lines[0])
        # Return the object and arguments to the chain
        return _obj, args, kwargs


# LinePlotterIndicator类，同样没有用到
class LinePlotterIndicator(Indicator, metaclass=MtLinePlotterIndicator):
    pass
