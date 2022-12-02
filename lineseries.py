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

.. module:: lineroot

Defines LineSeries and Descriptors inside of it for classes that hold multiple
lines at once.

.. moduleauthor:: Daniel Rodriguez

'''
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys

from .utils.py3 import map, range, string_types, with_metaclass

from .linebuffer import LineBuffer, LineActions, LinesOperation, LineDelay, NAN
from .lineroot import LineRoot, LineSingle, LineMultiple
from .metabase import AutoInfoClass
from . import metabase


class LineAlias(object):
    ''' Descriptor class that store a line reference and returns that line
    from the owner

    Keyword Args:
        line (int): reference to the line that will be returned from
        owner's *lines* buffer

    As a convenience the __set__ method of the descriptor is used not set
    the *line* reference because this is a constant along the live of the
    descriptor instance, but rather to set the value of the *line* at the
    instant '0' (the current one)
    '''
    # Descriptor就是一类实现了__get__(), __set__(), __delete__()方法的对象
    # 这个类的是通过初始化一个"line",这个line是一个整数，在请求的时候会返回obj.lines[line]
    # __set__用于设置line在0处的值

    def __init__(self, line):
        # 初始化，self.line是一个整数
        self.line = line

    def __get__(self, obj, cls=None):
        # 返回obj.lines[整数]，返回的应该是一个line的类型
        # print(obj,obj.__class__,obj.lines,self.line )
        return obj.lines[self.line]

    def __set__(self, obj, value):
        '''
        A line cannot be "set" once it has been created. But the values
        inside the line can be "set". This is achieved by adding a binding
        to the line inside "value"
        '''
        # 如果值是多条line的数据结构，就取第一条line
        if isinstance(value, LineMultiple):
            value = value.lines[0]

        # If the now for sure, LineBuffer 'value' is not a LineActions the
        # binding below could kick-in too early in the chain writing the value
        # into a not yet "forwarded" line, effectively writing the value 1
        # index too early and breaking the functionality (all in next mode)
        # Hence the need to transform it into a LineDelay object of null delay
        # 如果value是一个line，但是这个line还不是LineActions的子类的话，就把value转换成LineDelay结构
        if not isinstance(value, LineActions):
            value = value(0)
        # 给value这个line增加一个line，obj.lines[self.line]，到value.blindings,然后给line增加最小周期
        value.addbinding(obj.lines[self.line])


class Lines(object):
    '''
    Defines an "array" of lines which also has most of the interface of
    a LineBuffer class (forward, rewind, advance...).

    This interface operations are passed to the lines held by self

    The class can autosubclass itself (_derive) to hold new lines keeping them
    in the defined order.
    '''
    # Lines用于定义lines的array，并且拥有LineBuffer的大多数接口方法
    # 这些接口方法被传递到self保存的lines上
    # 这个类可以通过_derive自动子类话，用于按照预先定义的次序保存新的lines
    
    # 类方法，返回空元组
    _getlinesbase = classmethod(lambda cls: ())
    # 类方法，返回空元组
    _getlines = classmethod(lambda cls: ())
    # 类方法，返回0
    _getlinesextra = classmethod(lambda cls: 0)
    # 类方法，返回0
    _getlinesextrabase = classmethod(lambda cls: 0)

    @classmethod
    def _derive(cls, name, lines, extralines, otherbases, linesoverride=False,
                lalias=None):
        '''
        Creates a subclass of this class with the lines of this class as
        initial input for the subclass. It will include num "extralines" and
        lines present in "otherbases"

        "name" will be used as the suffix of the final class name

        "linesoverride": if True the lines of all bases will be discarded and
        the baseclass will be the topmost class "Lines". This is intended to
        create a new hierarchy
        '''
        # 创建这个class的子类，这个子类将会包含这个class的lines,extralines, otherbases的lines
        # name将会用于最终类的名字的后缀
        # linesoverride：如果这个参数是真的，所有bases的lines将会被丢弃，并且baseclass将会成为最高等级的Lines类
        #                这个用于创建一个新的等级
        
        # 其他类的lines，默认是空元组
        obaseslines = ()
        # 其他类的额外的lines，默认是0
        obasesextralines = 0

        # 对其他的bases进行循环
        for otherbase in otherbases:
            # 如果otherbase是元组，直接添加到obaseslines中去
            if isinstance(otherbase, tuple):
                obaseslines += otherbase
            # 如果不是元组，就通过_getlines获取具体的lines,添加到obaseslines，然后通过_getlinesextra获取额外的lines,添加到obasesextralines
            else:
                obaseslines += otherbase._getlines()
                obasesextralines += otherbase._getlinesextra()
            
        # 如果linesoverride是False的话，baselines就包含这个类的lines，如果是True,baselines就是空的元组
        if not linesoverride:
            baselines = cls._getlines() + obaseslines
            baseextralines = cls._getlinesextra() + obasesextralines
        else:  # overriding lines, skip anything from baseclasses
            baselines = ()
            baseextralines = 0

        # class的lines,元组
        clslines = baselines + lines
        # class的额外的lines，整数
        clsextralines = baseextralines + extralines
        # 要添加的lines,包含穿进来的其他类的lines和lines
        lines2add = obaseslines + lines

        # str for Python 2/3 compatibility
        # 如果不对lines进行重置，那么基类就是cls本身，否则就是Lines
        basecls = cls if not linesoverride else Lines
        
        
        # 动态创建类，名字是cls的名字加上name作为后缀，继承自basecls
        newcls = type(str(cls.__name__ + '_' + name), (basecls,), {})
        # clsmodule
        clsmodule = sys.modules[cls.__module__]
        # 设置newcls的__module__
        newcls.__module__ = cls.__module__
        
        # 设置clsmodule的newcls的名字的属性为newcls
        setattr(clsmodule, str(cls.__name__ + '_' + name), newcls)
        # 给newcls设置类方法属性_getlinesbase，返回baselines
        setattr(newcls, '_getlinesbase', classmethod(lambda cls: baselines))
        # 给newcls设置类方法属性_getlines，返回clslines
        setattr(newcls, '_getlines', classmethod(lambda cls: clslines))
        # 给newcls设置类方法属性_getlines，返回baseextralines
        setattr(newcls, '_getlinesextrabase',
                classmethod(lambda cls: baseextralines))
        # 给newcls设置类方法属性_getlinesextra，返回clsextralines
        setattr(newcls, '_getlinesextra',
                classmethod(lambda cls: clsextralines))
        # line开始，如果line不重写的话，开始的数字就是cls的line的数量，否则就是0
        # 
        l2start = len(cls._getlines()) if not linesoverride else 0
        # 返回一个enumerate对象，从l2start开始返回迭代的index和值，既然l2add只用到了下面的循环，直接写到后面的循环就好
        # l2add = enumerate(lines2add, start=l2start)  # backtrader自带
        # 如果lalias是None，l2alias是空的字典，否则返回lalias._getkwargsdefault()
        # l2alias = {} if lalias is None else lalias._getkwargsdefault() # backtrader自带，在这里面没用，移动到下面
        # for line, linealias in l2add: # backtrader自带
        for line,linealias in enumerate(lines2add, start=l2start):
            # line是一个整数，linealias如果不是字符串，那么和可能是元组或者列表，第一个就是它的名字
            if not isinstance(linealias, string_types):
                # a tuple or list was passed, 1st is name
                linealias = linealias[0]
            # 创建一个LineAlias的类
            desc = LineAlias(line)  # keep a reference below，LineAlias这个类只有用在了这里面和下面里面
            # 在newcls中绑定linealias属性值为desc，个人感觉是方便数字和line名字的转换
            setattr(newcls, linealias, desc)

        # Create extra aliases for the given name, checking if the names is in
        # l2alias (which is from the argument lalias and comes from the
        # directive 'linealias', hence the confusion here (the LineAlias come
        # from the directive 'lines')
        # 如果l2alias不是空的话，有需要设置，会运行下面的代码进行设置。这个逻辑写的并不是很高效，应该先判断下l2alias是否是空的，如果是空的话，就忽略，不运行
        # 如果lalias不是None的 情况下，l2alias才不是空
        if lalias is not None:   # 个人增加的
            l2alias = lalias._getkwargsdefault() # 个人增加的，替换前面的生成语句
            for line, linealias in enumerate(newcls._getlines()):
                if not isinstance(linealias, string_types):
                    # a tuple or list was passed, 1st is name
                    linealias = linealias[0]

                # 给newcls设置alias属性，属性值为desc
                desc = LineAlias(line)  # keep a reference below
                if linealias in l2alias:
                    extranames = l2alias[linealias]
                    if isinstance(linealias, string_types):
                        extranames = [extranames]

                    for ename in extranames:
                        setattr(newcls, ename, desc)

        return newcls


    @classmethod
    def _getlinealias(cls, i):
        '''
        Return the alias for a line given the index
        '''
        # 类方法，根据具体的index i 返回line的名字
        lines = cls._getlines()
        if i >= len(lines):
            return ''
        linealias = lines[i]   # backtrader自带
        return linealias       # backtrader自带
        # return lines[i]

    @classmethod
    def getlinealiases(cls):
        # 类方法，返回cls的所有的line
        return cls._getlines()

    def itersize(self):
        # 生成lines中0到self.size的切片的迭代器
        return iter(self.lines[0:self.size()])

    def __init__(self, initlines=None):
        '''
        Create the lines recording during "_derive" or else use the
        provided "initlines"
        '''
        # 初始化lines,设定lines是一个列表
        self.lines = list()
        for line, linealias in enumerate(self._getlines()):
            kwargs = dict()
            self.lines.append(LineBuffer(**kwargs))

        # Add the required extralines
        # 添加额外的line，如果不初始化line的话，直接使用LineBuffer,如果初始化line的话，就使用initlines[i]进行初始化
        # 然后添加到self.lines
        for i in range(self._getlinesextra()):
            if not initlines:
                self.lines.append(LineBuffer())
            else:
                self.lines.append(initlines[i])

    def __len__(self):
        '''
        Proxy line operation
        '''
        # 返回一条line的长度
        return len(self.lines[0])

    def size(self):
        # 返回正常的line的数量
        return len(self.lines) - self._getlinesextra()

    def fullsize(self):
        # 返回全部的line的数量
        return len(self.lines)

    def extrasize(self):
        # 返回额外line的数量
        return self._getlinesextra()

    def __getitem__(self, line):
        '''
        Proxy line operation
        '''
        # 根据整数line作为yindex获取具体的line对象
        return self.lines[line]

    def get(self, ago=0, size=1, line=0):
        '''
        Proxy line operation
        '''
        # 根据整数line作为index获取某条line，然后获取包含ago在内的之前的size个数量的数据
        return self.lines[line].get(ago, size=size)

    def __setitem__(self, line, value):
        '''
        Proxy line operation
        '''
        # 给self设置属性，self._getlinealias(line)返回的是line的名字，value是设置的值
        setattr(self, self._getlinealias(line), value)

    def forward(self, value=NAN, size=1):
        '''
        Proxy line operation
        '''
        # 把每个line都向前size
        for line in self.lines:
            line.forward(value, size=size)

    def backwards(self, size=1, force=False):
        '''
        Proxy line operation
        '''
        # 把每个line都向后size
        for line in self.lines:
            line.backwards(size, force=force)

    def rewind(self, size=1):
        '''
        Proxy line operation
        '''
        # 把line的idx和lencount减少size
        for line in self.lines:
            line.rewind(size)

    def extend(self, value=NAN, size=0):
        '''
        Proxy line operation
        '''
        # 把line.array向前扩展size个值
        for line in self.lines:
            line.extend(value, size)

    def reset(self):
        '''
        Proxy line operation
        '''
        # 重置line
        for line in self.lines:
            line.reset()

    def home(self):
        '''
        Proxy line operation
        '''
        # 返回到最开始
        for line in self.lines:
            line.home()

    def advance(self, size=1):
        '''
        Proxy line operation
        '''
        # 把line的idx和lencount增加size
        for line in self.lines:
            line.advance(size)

    def buflen(self, line=0):
        '''
        Proxy line operation
        '''
        # 返回line缓存的数据的长度
        return self.lines[line].buflen()


class MetaLineSeries(LineMultiple.__class__):
    '''
    Dirty job manager for a LineSeries

      - During __new__ (class creation), it reads "lines", "plotinfo",
        "plotlines" class variable definitions and turns them into
        Classes of type Lines or AutoClassInfo (plotinfo/plotlines)

      - During "new" (instance creation) the lines/plotinfo/plotlines
        classes are substituted in the instance with instances of the
        aforementioned classes and aliases are added for the "lines" held
        in the "lines" instance

        Additionally and for remaining kwargs, these are matched against
        args in plotinfo and if existent are set there and removed from kwargs

        Remember that this Metaclass has a MetaParams (from metabase)
        as root class and therefore "params" defined for the class have been
        removed from kwargs at an earlier state
    '''

    def __new__(meta, name, bases, dct):
        '''
        Intercept class creation, identifiy lines/plotinfo/plotlines class
        attributes and create corresponding classes for them which take over
        the class attributes
        '''

        # Get the aliases - don't leave it there for subclasses
        aliases = dct.setdefault('alias', ())
        aliased = dct.setdefault('aliased', '')

        # Remove the line definition (if any) from the class creation
        linesoverride = dct.pop('linesoverride', False)
        newlines = dct.pop('lines', ())
        extralines = dct.pop('extralines', 0)

        # remove the new plotinfo/plotlines definition if any
        newlalias = dict(dct.pop('linealias', {}))

        # remove the new plotinfo/plotlines definition if any
        newplotinfo = dict(dct.pop('plotinfo', {}))
        newplotlines = dict(dct.pop('plotlines', {}))

        # Create the class - pulling in any existing "lines"
        cls = super(MetaLineSeries, meta).__new__(meta, name, bases, dct)

        # Check the line aliases before creating the lines
        lalias = getattr(cls, 'linealias', AutoInfoClass)
        oblalias = [x.linealias for x in bases[1:] if hasattr(x, 'linealias')]
        cls.linealias = la = lalias._derive('la_' + name, newlalias, oblalias)

        # Get the actual lines or a default
        lines = getattr(cls, 'lines', Lines)

        # Create a subclass of the lines class with our name and newlines
        # and put it in the class
        morebaseslines = [x.lines for x in bases[1:] if hasattr(x, 'lines')]
        cls.lines = lines._derive(name, newlines, extralines, morebaseslines,
                                  linesoverride, lalias=la)

        # Get a copy from base class plotinfo/plotlines (created with the
        # class or set a default)
        plotinfo = getattr(cls, 'plotinfo', AutoInfoClass)
        plotlines = getattr(cls, 'plotlines', AutoInfoClass)

        # Create a plotinfo/plotlines subclass and set it in the class
        morebasesplotinfo = \
            [x.plotinfo for x in bases[1:] if hasattr(x, 'plotinfo')]
        cls.plotinfo = plotinfo._derive('pi_' + name, newplotinfo,
                                        morebasesplotinfo)

        # Before doing plotline newlines have been added and no plotlineinfo
        # is there add a default
        for line in newlines:
            newplotlines.setdefault(line, dict())

        morebasesplotlines = \
            [x.plotlines for x in bases[1:] if hasattr(x, 'plotlines')]
        cls.plotlines = plotlines._derive(
            'pl_' + name, newplotlines, morebasesplotlines, recurse=True)

        # create declared class aliases (a subclass with no modifications)
        for alias in aliases:
            newdct = {'__doc__': cls.__doc__,
                      '__module__': cls.__module__,
                      'aliased': cls.__name__}

            if not isinstance(alias, string_types):
                # a tuple or list was passed, 1st is name, 2nd plotname
                aliasplotname = alias[1]
                alias = alias[0]
                newdct['plotinfo'] = dict(plotname=aliasplotname)

            newcls = type(str(alias), (cls,), newdct)
            clsmodule = sys.modules[cls.__module__]
            setattr(clsmodule, alias, newcls)

        # return the class
        return cls

    def donew(cls, *args, **kwargs):
        '''
        Intercept instance creation, take over lines/plotinfo/plotlines
        class attributes by creating corresponding instance variables and add
        aliases for "lines" and the "lines" held within it
        '''
        # _obj.plotinfo shadows the plotinfo (class) definition in the class
        plotinfo = cls.plotinfo()

        for pname, pdef in cls.plotinfo._getitems():
            setattr(plotinfo, pname, kwargs.pop(pname, pdef))

        # Create the object and set the params in place
        _obj, args, kwargs = super(MetaLineSeries, cls).donew(*args, **kwargs)

        # set the plotinfo member in the class
        _obj.plotinfo = plotinfo

        # _obj.lines shadows the lines (class) definition in the class
        _obj.lines = cls.lines()

        # _obj.plotinfo shadows the plotinfo (class) definition in the class
        _obj.plotlines = cls.plotlines()

        # add aliases for lines and for the lines class itself
        _obj.l = _obj.lines
        if _obj.lines.fullsize():
            _obj.line = _obj.lines[0]

        for l, line in enumerate(_obj.lines):
            # print(l,line,_obj._getlinealias(l))
            setattr(_obj, 'line_%s' % l, _obj._getlinealias(l))
            setattr(_obj, 'line_%d' % l, line)
            setattr(_obj, 'line%d' % l, line)

        # Parameter values have now been set before __init__
        return _obj, args, kwargs
class MetaLineSeries(LineMultiple.__class__):
    '''
    Dirty job manager for a LineSeries

      - During __new__ (class creation), it reads "lines", "plotinfo",
        "plotlines" class variable definitions and turns them into
        Classes of type Lines or AutoClassInfo (plotinfo/plotlines)

      - During "new" (instance creation) the lines/plotinfo/plotlines
        classes are substituted in the instance with instances of the
        aforementioned classes and aliases are added for the "lines" held
        in the "lines" instance

        Additionally and for remaining kwargs, these are matched against
        args in plotinfo and if existent are set there and removed from kwargs

        Remember that this Metaclass has a MetaParams (from metabase)
        as root class and therefore "params" defined for the class have been
        removed from kwargs at an earlier state
    '''
    # 这个类是给LineSeries做一些预处理工作，主要是获取plotinfo、lines、plotlines等相关的属性
    # 然后创建一个_obj并给它增加相应的属性并赋值
    

    def __new__(meta, name, bases, dct):
        '''
        Intercept class creation, identifiy lines/plotinfo/plotlines class
        attributes and create corresponding classes for them which take over
        the class attributes
        '''

        # Get the aliases - don't leave it there for subclasses
        # 给dct增加一个alias,aliased的key，并设定默认值是(),"",其中aliases的值是一个空的列表，aliased的值是空的字符串。字典的具体用法
        aliases = dct.setdefault('alias', ())
        aliased = dct.setdefault('aliased', '')

        # Remove the line definition (if any) from the class creation
        # 从字典中删除linesoverride的key，并用linesoverride接收这个值，如果不存在这个key，就返回一个False
        linesoverride = dct.pop('linesoverride', False)
        # 删除dct中的lines，并把具体的值保存到newlines中，如果没有lines的值，返回空元组
        newlines = dct.pop('lines', ())
        # 删除dct中的extralines，并把具体的值保存到extralines中，如果没有extralines的值，返回0
        extralines = dct.pop('extralines', 0)

        # remove the new plotinfo/plotlines definition if any
        # 删除dct中的linealias，并把具体的值保存到newlalias中，如果没有linealias的值，返回空的字典
        newlalias = dict(dct.pop('linealias', {}))

        # remove the new plotinfo/plotlines definition if any
        # 删除dct中的plotinfo，并把具体的值保存到newplotinfo中，如果没有plotinfo的值，返回空的字典
        newplotinfo = dict(dct.pop('plotinfo', {}))
        # 删除dct中的plotlines，并把具体的值保存到newplotlines中，如果没有plotlines的值，返回空的字典
        newplotlines = dict(dct.pop('plotlines', {}))

        # Create the class - pulling in any existing "lines"
        # 创建一个cls
        cls = super(MetaLineSeries, meta).__new__(meta, name, bases, dct)

        # Check the line aliases before creating the lines
        # 获取cls的linealias属性值，如果不存在，就返回AutoInfoClass类
        lalias = getattr(cls, 'linealias', AutoInfoClass)
        # 获取其他base的linealias
        oblalias = [x.linealias for x in bases[1:] if hasattr(x, 'linealias')]
        # AutoInfoClass类的_derive方法创建一个对象，给cls的linealias赋值
        cls.linealias = la = lalias._derive('la_' + name, newlalias, oblalias)
        # Get the actual lines or a default
        # 从cls获取lines属性值，如果没有返回Lines类
        lines = getattr(cls, 'lines', Lines)

        # Create a subclass of the lines class with our name and newlines
        # and put it in the class
        morebaseslines = [x.lines for x in bases[1:] if hasattr(x, 'lines')]
        # 使用lines的_derive方法创建一个对象，给cls的lines属性赋值
        cls.lines = lines._derive(name, newlines, extralines, morebaseslines,
                                  linesoverride, lalias=la)

        # Get a copy from base class plotinfo/plotlines (created with the
        # class or set a default)
        plotinfo = getattr(cls, 'plotinfo', AutoInfoClass)
        plotlines = getattr(cls, 'plotlines', AutoInfoClass)

        # Create a plotinfo/plotlines subclass and set it in the class
        morebasesplotinfo = \
            [x.plotinfo for x in bases[1:] if hasattr(x, 'plotinfo')]
        # 使用autoinfoclass的_derive创建一个对象，赋值给cls的plotinfo属性
        cls.plotinfo = plotinfo._derive('pi_' + name, newplotinfo,
                                        morebasesplotinfo)

        # Before doing plotline newlines have been added and no plotlineinfo
        # is there add a default
        for line in newlines:
            newplotlines.setdefault(line, dict())

        morebasesplotlines = \
            [x.plotlines for x in bases[1:] if hasattr(x, 'plotlines')]
        # 使用autoinfoclass的_derive创建一个对象，赋值给cls的plotlines属性
        cls.plotlines = plotlines._derive(
            'pl_' + name, newplotlines, morebasesplotlines, recurse=True)

        # create declared class aliases (a subclass with no modifications)
        # 给alias属性赋值
        for alias in aliases:
            newdct = {'__doc__': cls.__doc__,
                      '__module__': cls.__module__,
                      'aliased': cls.__name__}

            if not isinstance(alias, string_types):
                # a tuple or list was passed, 1st is name, 2nd plotname
                aliasplotname = alias[1]
                alias = alias[0]
                newdct['plotinfo'] = dict(plotname=aliasplotname)

            newcls = type(str(alias), (cls,), newdct)
            clsmodule = sys.modules[cls.__module__]
            setattr(clsmodule, alias, newcls)

        # return the class
        return cls

    def donew(cls, *args, **kwargs):
        '''
        Intercept instance creation, take over lines/plotinfo/plotlines
        class attributes by creating corresponding instance variables and add
        aliases for "lines" and the "lines" held within it
        '''
        # 创建一个_obj,保存lines,plotinfo,plotlines相关的属性，并给lines增加别名
        
        # _obj.plotinfo shadows the plotinfo (class) definition in the class
        # plotinfo的cls
        plotinfo = cls.plotinfo()
        # 给plotinfo增加具体的属性和相应的值
        for pname, pdef in cls.plotinfo._getitems():
            setattr(plotinfo, pname, kwargs.pop(pname, pdef))

        # Create the object and set the params in place
        # 创建一个_obj,并设置plotinfo等于plotinfo
        _obj, args, kwargs = super(MetaLineSeries, cls).donew(*args, **kwargs)

        # set the plotinfo member in the class
        _obj.plotinfo = plotinfo

        # _obj.lines shadows the lines (class) definition in the class
        # 给_obj的lines属性赋值
        _obj.lines = cls.lines()

        # _obj.plotinfo shadows the plotinfo (class) definition in the class
        # 给_obj的plotlines属性赋值
        _obj.plotlines = cls.plotlines()

        # add aliases for lines and for the lines class itself
        # 增加一个l属性，和lines等同
        _obj.l = _obj.lines
        # _obj的line属性，返回lines中的第一条，如果lines的数量是大于0的话
        if _obj.lines.fullsize():
            _obj.line = _obj.lines[0]
        # 迭代_obj中的lines，设置line的别名
        # self.line_1,self.line1,self.line_xxx是等同的
        for l, line in enumerate(_obj.lines):
            setattr(_obj, 'line_%s' % l, _obj._getlinealias(l))
            setattr(_obj, 'line_%d' % l, line)
            setattr(_obj, 'line%d' % l, line)

        # Parameter values have now been set before __init__
        return _obj, args, kwargs


class LineSeries(with_metaclass(MetaLineSeries, LineMultiple)):
    # 创建一个LineSeries类
    
    # 给lineseries类增加一个默认的属性plotinfo
    plotinfo = dict(
        plot=True,
        plotmaster=None,
        legendloc=None,
    )

    # csv属性
    csv = True

    @property
    def array(self):
        # 如果调用array，将会返回添加进去的第一条line的数据
        return self.lines[0].array

    def __getattr__(self, name):
        # to refer to line by name directly if the attribute was not found
        # in this object if we set an attribute in this object it will be
        # found before we end up here
        
        # 返回self.lines的name属性值
        return getattr(self.lines, name)

    def __len__(self):
        # 返回lines的数量
        return len(self.lines)

    def __getitem__(self, key):
        # 根据index获取第一条line的值
        return self.lines[0][key]

    def __setitem__(self, key, value):
        # 给self.lines设置属性及属性值
        setattr(self.lines, self.lines._getlinealias(key), value)

    def __init__(self, *args, **kwargs):
        # if any args, kwargs make it up to here, something is broken
        # defining a __init__ guarantees the existence of im_func to findbases
        # in lineiterator later, because object.__init__ has no im_func
        # (object has slots)
        
        # 初始化
        super(LineSeries, self).__init__()
        pass

    def plotlabel(self):
        
        # 画图的标签
        label = self.plotinfo.plotname or self.__class__.__name__
        # 获取参数的值
        sublabels = self._plotlabel()
        # 如果有具体的参数的话
        if sublabels:
            # 遍历对象sublabels，如果其中元素sublabel有plotinfo属性的话，就获取其中的plotname属性值，否则就是sublabel本身的名字
            for i, sublabel in enumerate(sublabels):
                # if isinstance(sublabel, LineSeries): ## DOESN'T WORK ??? 我替作者回答下，这是因为lineseries的plotinfo属性中暂时没有plotname变量
                if hasattr(sublabel, 'plotinfo'):
                    try:
                        s = sublabel.plotinfo.plotname
                    except:
                        s = ''

                    sublabels[i] = s or sublabel.__name__
            # 把sublabels按照字符串连接起来
            label += ' (%s)' % ', '.join(map(str, sublabels))
        return label

    def _plotlabel(self):
        # 获取参数的值
        return self.params._getvalues()

    def _getline(self, line, minusall=False):
        # 获取line
        # 如果line是字符串，就从self.lines获取属性值，如果不是字符串而是数字的话
        if isinstance(line, string_types):
            lineobj = getattr(self.lines, line)
        else:
            # 如果line的值是-1的话，如果minusall是False的话，修改line的值为0,返回第一条line，如果minusall是True的话，返回None
            if line == -1:  # restore original api behavior - default -> 0
                if minusall:  # minus means ... all lines
                    return None
                line = 0
            lineobj = self.lines[line]
        # 返回一条line
        return lineobj

    def __call__(self, ago=None, line=-1):
        '''Returns either a delayed verison of itself in the form of a
        LineDelay object or a timeframe adapting version with regards to a ago

        Param: ago (default: None)

          If ago is None or an instance of LineRoot (a lines object) the
          returned valued is a LineCoupler instance

          If ago is anything else, it is assumed to be an int and a LineDelay
          object will be returned

        Param: line (default: -1)
          If a LinesCoupler will be returned ``-1`` means to return a
          LinesCoupler which adapts all lines of the current LineMultiple
          object. Else the appropriate line (referenced by name or index) will
          be LineCoupled

          If a LineDelay object will be returned, ``-1`` is the same as ``0``
          (to retain compatibility with the previous default value of 0). This
          behavior will change to return all existing lines in a LineDelayed
          form

          The referenced line (index or name) will be LineDelayed
        '''
        from .lineiterator import LinesCoupler  # avoid circular import
        # 如果ago是None或者是LineRoot的子类的话
        if ago is None or isinstance(ago, LineRoot):
            args = [self, ago]
            lineobj = self._getline(line, minusall=True)
            if lineobj is not None:
                args[0] = lineobj
            # 将会返回一个LinesCoupler
            return LinesCoupler(*args, _ownerskip=self)

        # else -> assume type(ago) == int -> return LineDelay object
        # 如果ago不是None，并且不是LineRoot的子类，默认ago是int值，返回一个LineDelay对象
        return LineDelay(self._getline(line), ago, _ownerskip=self)

    # The operations below have to be overriden to make sure subclasses can
    # reach them using "super" which will not call __getattr__ and
    # LineSeriesStub (see below) already uses super
    
    # line的常规操作
    def forward(self, value=NAN, size=1):
        self.lines.forward(value, size)

    def backwards(self, size=1, force=False):
        self.lines.backwards(size, force=force)

    def rewind(self, size=1):
        self.lines.rewind(size)

    def extend(self, value=NAN, size=0):
        self.lines.extend(value, size)

    def reset(self):
        self.lines.reset()

    def home(self):
        self.lines.home()

    def advance(self, size=1):
        self.lines.advance(size)


class LineSeriesStub(LineSeries):
    '''Simulates a LineMultiple object based on LineSeries from a single line

    The index management operations are overriden to take into account if the
    line is a slave, ie:

      - The line reference is a line from many in a LineMultiple object
      - Both the LineMultiple object and the Line are managed by the same
        object

    Were slave not to be taken into account, the individual line would for
    example be advanced twice:

      - Once under when the LineMultiple object is advanced (because it
        advances all lines it is holding
      - Again as part of the regular management of the object holding it
    '''
    # 根据一条line模拟一个多条line的对象

    extralines = 1

    def __init__(self, line, slave=False):
        # 初始化,把单个line对象转变为lines对象
        self.lines = self.__class__.lines(initlines=[line])
        # give a change to find the line owner (for plotting at least)
        self.owner = self._owner = line._owner
        self._minperiod = line._minperiod
        self.slave = slave

    # Only execute the operations below if the object is not a slave
    def forward(self, value=NAN, size=1):
        if not self.slave:
            super(LineSeriesStub, self).forward(value, size)

    def backwards(self, size=1, force=False):
        if not self.slave:
            super(LineSeriesStub, self).backwards(size, force=force)

    def rewind(self, size=1):
        if not self.slave:
            super(LineSeriesStub, self).rewind(size)

    def extend(self, value=NAN, size=0):
        if not self.slave:
            super(LineSeriesStub, self).extend(value, size)

    def reset(self):
        if not self.slave:
            super(LineSeriesStub, self).reset()

    def home(self):
        if not self.slave:
            super(LineSeriesStub, self).home()

    def advance(self, size=1):
        if not self.slave:
            super(LineSeriesStub, self).advance(size)

    def qbuffer(self):
        if not self.slave:
            super(LineSeriesStub, self).qbuffer()

    def minbuffer(self, size):
        if not self.slave:
            super(LineSeriesStub, self).minbuffer(size)


def LineSeriesMaker(arg, slave=False):
    # 创建lineseries
    if isinstance(arg, LineSeries):
        return arg

    return LineSeriesStub(arg, slave=slave)
