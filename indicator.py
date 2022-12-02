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


from .utils.py3 import range, with_metaclass

from .lineiterator import LineIterator, IndicatorBase
from .lineseries import LineSeriesMaker, Lines
from .metabase import AutoInfoClass

# 指标元类
class MetaIndicator(IndicatorBase.__class__):
    # 指标名称(_refname)
    _refname = '_indcol'
    # 指标列
    _indcol = dict()
    # 指标缓存
    _icache = dict()
    # 指标缓存使用
    _icacheuse = False
    # 类方法，清除缓存
    @classmethod
    def cleancache(cls):
        cls._icache = dict()
    # 类方法，设置是否使用缓存
    @classmethod
    def usecache(cls, onoff):
        cls._icacheuse = onoff

    # Object cache deactivated on 2016-08-17. If the object is being used
    # inside another object, the minperiod information carried over
    # influences the first usage when being modified during the 2nd usage
    # 调用的时候
    def __call__(cls, *args, **kwargs):
        # 如果不是使用缓存的话，调用元类的__call__方法，生成cls
        if not cls._icacheuse:
            return super(MetaIndicator, cls).__call__(*args, **kwargs)

        # implement a cache to avoid duplicating lines actions
        # 如果使用缓存的话，创建一个缓存，避免重复的line行为，下面ckey是一个可以哈希的元组，可以作为字典的key
        ckey = (cls, tuple(args), tuple(kwargs.items()))  # tuples hashable
        # 如果缓存中已经存在了ckey的key和值，直接返回相应的值，如果不是可以哈希的，调用元类的__call__方法，生成cls
        try:
            return cls._icache[ckey]
        except TypeError:  # something not hashable
            return super(MetaIndicator, cls).__call__(*args, **kwargs)
        except KeyError:
            pass  # hashable but not in the cache
        # 如果缓存中没有ckey，那么调用元类的__call__方法，生成一个实例，并把这个实例设为ckey的值
        _obj = super(MetaIndicator, cls).__call__(*args, **kwargs)
        return cls._icache.setdefault(ckey, _obj)

    # 初始化
    def __init__(cls, name, bases, dct):
        '''
        Class has already been created ... register subclasses
        '''
        # Initialize the class
        super(MetaIndicator, cls).__init__(name, bases, dct)
        # 如果不是alised ，同时name也不等于指标，同时name并不是以_开头的，
        if not cls.aliased and name != 'Indicator' and not name.startswith('_'):
            # 获取refattr属性，并添加name和cls到这个属性值中
            refattr = getattr(cls, cls._refname)
            refattr[name] = cls

        # Check if next and once have both been overridden
        # 检查next和once是否被重写了
        next_over = cls.next != IndicatorBase.next
        once_over = cls.once != IndicatorBase.once
        # 如果只有next被重写了，但是once没有被重写
        if next_over and not once_over:
            # No -> need pointer movement to once simulation via next
            # 需要通过next来模拟once的指针运动
            cls.once = cls.once_via_next
            cls.preonce = cls.preonce_via_prenext
            cls.oncestart = cls.oncestart_via_nextstart


# 指标类
class Indicator(with_metaclass(MetaIndicator, IndicatorBase)):
    # line的类型被设置为指标
    _ltype = LineIterator.IndType
    # 输出到csv文件被设置成False
    csv = False
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
        lname = kwargs.pop('name')
        # 类的名字
        name = cls.__name__
        # 获取cls的liens,如果没有，就返回Lines
        lines = getattr(cls, 'lines', Lines)
        # 对lines进行相应的操作
        cls.lines = lines._derive(name, (lname,), 0, [])
        # plotlines响应的操作
        plotlines = AutoInfoClass
        newplotlines = dict()
        newplotlines.setdefault(lname, dict())
        cls.plotlines = plotlines._derive(name, newplotlines, [], recurse=True)

        # Create the object and set the params in place
        # 创建具体的类并设置参数
        _obj, args, kwargs =  super(MtLinePlotterIndicator, cls).donew(*args, **kwargs)
        # 设置_obj的owner属性值
        _obj.owner = _obj.data.owner._clock
        # 增加另一条linebuffer
        _obj.data.lines[0].addbinding(_obj.lines[0])
        # Return the object and arguments to the chain
        return _obj, args, kwargs

# LinePlotterIndicator类，同样没有用到
class LinePlotterIndicator(with_metaclass(MtLinePlotterIndicator, Indicator)):
    pass
