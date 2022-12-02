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

from collections import OrderedDict
import itertools
import sys

import backtrader as bt
from .utils.py3 import zip, string_types, with_metaclass

# 寻找基类，这个python函数主要使用了四个python小技巧：
# 第一个是class.__bases__这个会包含class的基类(父类)
# 第二个是issubclass用于判断base是否是topclass的子类
# 第三个是在函数中直接调用这个函数，使用了递归，python中的递归是有限的，在这个包里面，寻找子类与父类之间的继承关系，不大可能超过递归限制
# 第四个是list的操作，extend和append，没啥需要讲解的，python基础
# 这个函数看起来似乎也没有使用cython优化的需要。但是基于对python性能的理解，这个函数代码并没有发挥到最佳的效率，其中retval创建列表的时候
# 调用list()函数其实并没有最大化python的效率，其实应该直接使用retval = [],这样效率更高一些，但是整体上提升的效率也是微乎其微，这个函数看起来
# 不算是高频率使用的函数。关于改写list()的原因可以参考这篇文章：https://blog.csdn.net/weixin_44799217/article/details/119877699
# 查找这个函数的时候，发现backtrader几乎没有使用到。忽略就好。
def findbases(kls, topclass):
    # retval = list() # backtrader自带
    retval = []
    for base in kls.__bases__:
        if issubclass(base, topclass):
            retval.extend(findbases(base, topclass))
            retval.append(base)

    return retval


# 这个函数看起来还是不太容易理解的。虽然已经阅读过几遍了，但是看起来还是有点头大。这个函数比前一个函数用到的地方比较多，重点分析这个函数的意义。
# itertools.count(start=0,step=1)用于生成从0开始的步长为1的无界限序列，需要使用break停止循环，在这个使用中，默认是从2开始的，每次步长为1
# sys._getframe([depth])：从调用堆栈返回帧对象。如果可选参数depth是一个整数，返回在最顶级堆栈下多少层的调用的帧对象，如果这个depth高于调用的层数
#       - 会抛出一个ValueError.默认参数depth是0,会返回最顶层堆栈的帧对象。从这个函数的使用来看，获取到的frame(帧对象)是最底层调用的帧对象
#       - Return a frame object from the call stack. 
#       - If optional integer depth is given, return the frame object that many calls below the top of the stack. 
#       - If that is deeper than the call stack, ValueError is raised. The default for depth is zero, 
#       - returning the frame at the top of the call stack.
# sys._getframe().f_locals返回的是帧对象的本地的变量，字典形式，使用get("self",None)是查看本地变量中有没有frame，如果有的话，返回相应的值，如果没有，返回值是None
# 总结一下这个函数的用法：findowner用于发现owned的父类，这个类是cls的实例，但是同时这个类不能是skip，如果不能满足这些条件，就返回一个None.
def findowner(owned, cls, startlevel=2, skip=None):
    # skip this frame and the caller's -> start at 2
    for framelevel in itertools.count(startlevel):
        try:
            frame = sys._getframe(framelevel)
        except ValueError:
            # Frame depth exceeded ... no owner ... break away
            break

        # 'self' in regular code
        self_ = frame.f_locals.get('self', None)
        # 如果skip和self_不一样，如果self_不是owned并且self_是cls的实例,就返回self_
        if skip is not self_:
            if self_ is not owned and isinstance(self_, cls):
                return self_

        # '_obj' in metaclasses
        # 如果"_obj"在帧对象本地变量中
        obj_ = frame.f_locals.get('_obj', None)
        # 如果obj_不是skip，并且obj_不是owned，并且obj_是class的实例，返回obj_
        if skip is not obj_:
            if obj_ is not owned and isinstance(obj_, cls):
                return obj_
    # 前两种情况都不是的话，返回None
    return None


# 这是一个看起来更加复杂的使用元编程的技巧,MetaParams是其子类，很多地方都在使用，为了能够搞懂MetaParams，需要对这个类有足够的了解.
# csdn上有一篇文章讲解backtrader元类的，可以借鉴一下：https://blog.csdn.net/h00cker/article/details/121523010
# MetaBase作为一个创建元类的类，开始的时候首先调用的是__call__()的函数，在这个函数下，依次对cls进行doprenew,donew,dopreinit,doinit,dopostinit
# 这几个方法的处理，然后返回创建好的类。为了更好的理解MetaBase,需要结合MetaParams一块，先移步到这个类上。
# 从MetaParams上来看，这个子类主要是重写了__new__和donew这两个，在调用的时候，看起来是先调用__new__，然后调用donew,依次看这两个
class MetaBase(type):
    def doprenew(cls, *args, **kwargs):
        return cls, args, kwargs

    def donew(cls, *args, **kwargs):
        # print("metabase donew")
        _obj = cls.__new__(cls, *args, **kwargs)
        return _obj, args, kwargs

    def dopreinit(cls, _obj, *args, **kwargs):
        return _obj, args, kwargs

    def doinit(cls, _obj, *args, **kwargs):
        _obj.__init__(*args, **kwargs)
        return _obj, args, kwargs

    def dopostinit(cls, _obj, *args, **kwargs):
        return _obj, args, kwargs

    def __call__(cls, *args, **kwargs):
        # print("__call__")
        # print(cls,args,kwargs)
        # 具体的参数值如下：
        # <class 'backtrader.order.BuyOrder'> () {'owner': <__main__.DirectStrategy object at 0x7f8079016760>, 
        # 'data': <backtrader.feeds.pandafeed.PandasDirectData object at 0x7f807953eee0>, 'size': 1, 'price': None, 
        # 'pricelimit': None, 'exectype': None, 'valid': None, 'tradeid': 0, 'trailamount': None, 'trailpercent': None, 
        # 'parent': None, 'transmit': True, 'histnotify': False}
        cls, args, kwargs = cls.doprenew(*args, **kwargs)
        _obj, args, kwargs = cls.donew(*args, **kwargs)
        _obj, args, kwargs = cls.dopreinit(_obj, *args, **kwargs)
        _obj, args, kwargs = cls.doinit(_obj, *args, **kwargs)
        _obj, args, kwargs = cls.dopostinit(_obj, *args, **kwargs)
        return _obj

class AutoInfoClass(object):

    #  
    # 下面的三个函数应该等价于类似的结构.这个结论是推测的
    # @classmethod
    # def _getpairsbase(cls)
    #     return OrderedDict()
    # @classmethod
    # def _getpairs(cls)
    #     return OrderedDict()
    # @classmethod
    # def _getrecurse(cls)
    #     return False
    # 

    _getpairsbase = classmethod(lambda cls: OrderedDict())
    _getpairs = classmethod(lambda cls: OrderedDict())
    _getrecurse = classmethod(lambda cls: False)

    @classmethod
    def _derive(cls, name, info, otherbases, recurse=False):
        '''推测各个参数的意义：
        cls:代表一个具体的类，很有可能就是AutoInfoClass的一个实例
        info:代表参数（parameter)
        otherBases:其他的bases
        recurse:递归
        举例的应用：_derive(name, newparams, morebasesparams)
        '''
        # collect the 3 set of infos
        # info = OrderedDict(info)
        # print(name,info,otherbases)
        baseinfo = cls._getpairs().copy()   # 浅拷贝，保证有序字典一级目录下不改变,暂时没有明白为什么要copy
        obasesinfo = OrderedDict()          # 代表其他类的info
        for obase in otherbases:
            # 如果传入的otherbases是已经获取过类的参数，这些参数值应该是字典或者元组，就更新到obaseinfo中；否则就是类的实例，但是如果是类的实例的话，使用_getpairs()获取的
            # 是具体的cls.baseinfo
            if isinstance(obase, (tuple, dict)):
                obasesinfo.update(obase)
            else:
                obasesinfo.update(obase._getpairs())

        # update the info of this class (base) with that from the other bases
        baseinfo.update(obasesinfo)

        # The info of the new class is a copy of the full base info
        # plus and update from parameter
        clsinfo = baseinfo.copy()
        clsinfo.update(info)
        # 上面的clsinfo本质上就是把cls的信息、info和otherbases的相关信息汇总到一起

        # The new items to update/set are those from the otherbase plus the new
        # info2add保存的是info和otherbases的相关信息汇总到一起，没包含cls的信息
        info2add = obasesinfo.copy()
        info2add.update(info)
        
        # 接下来创建一个cls的子类，并把这个类赋值给clsmodule的newclsname
        clsmodule = sys.modules[cls.__module__]
        newclsname = str(cls.__name__ + '_' + name)  # str - Python 2/3 compat

        # This loop makes sure that if the name has already been defined, a new
        # unique name is found. A collision example is in the plotlines names
        # definitions of bt.indicators.MACD and bt.talib.MACD. Both end up
        # definining a MACD_pl_macd and this makes it impossible for the pickle
        # module to send results over a multiprocessing channel
        namecounter = 1
        while hasattr(clsmodule, newclsname):
            newclsname += str(namecounter)
            namecounter += 1

        newcls = type(newclsname, (cls,), {})
        setattr(clsmodule, newclsname, newcls)
        # 给cls的设置几个方法，分别返回baseinfo和clsinfo和recurse的值
        setattr(newcls, '_getpairsbase',
                classmethod(lambda cls: baseinfo.copy()))
        setattr(newcls, '_getpairs', classmethod(lambda cls: clsinfo.copy()))
        setattr(newcls, '_getrecurse', classmethod(lambda cls: recurse))

        for infoname, infoval in info2add.items():
            # 查找具体的AutoInfoClass的使用，暂时没有发现recurse是真的的语句，所以下面条件语句可能不怎么运行。推测这个是递归用的，如果递归，会把infoval下的信息加进去
            if recurse:
                recursecls = getattr(newcls, infoname, AutoInfoClass)
                infoval = recursecls._derive(name + '_' + infoname,
                                             infoval,
                                             [])
            # 给newcls设置info和otherbases之类的信息
            setattr(newcls, infoname, infoval)

        return newcls

    def isdefault(self, pname):
        # 是默认的
        return self._get(pname) == self._getkwargsdefault()[pname]

    def notdefault(self, pname):
        # 不是默认的
        return self._get(pname) != self._getkwargsdefault()[pname]

    def _get(self, name, default=None):
        # 获取cls的name的属性值
        return getattr(self, name, default)

    @classmethod
    def _getkwargsdefault(cls):
        # 获取cls的信息
        return cls._getpairs()

    @classmethod
    def _getkeys(cls):
        # 获取cls的有序字典的key
        return cls._getpairs().keys()

    @classmethod
    def _getdefaults(cls):
        # 获取cls的有序字典的value
        return list(cls._getpairs().values())

    @classmethod
    def _getitems(cls):
        # 获取cls的有序字典的key和value对，是迭代对象
        return cls._getpairs().items()

    @classmethod
    def _gettuple(cls):
        # 获取cls的有序字典的key和value对，并保存为元组
        return tuple(cls._getpairs().items())

    def _getkwargs(self, skip_=False):
        # 获取cls的key,value并保存为有序字典
        l = [
            (x, getattr(self, x))
            for x in self._getkeys() if not skip_ or not x.startswith('_')]
        return OrderedDict(l)

    def _getvalues(self):
        # 获取cls的value并保存为列表
        return [getattr(self, x) for x in self._getkeys()]

    def __new__(cls, *args, **kwargs):
        # 创建一个新的obj
        obj = super(AutoInfoClass, cls).__new__(cls, *args, **kwargs)

        if cls._getrecurse():
            for infoname in obj._getkeys():
                recursecls = getattr(cls, infoname)
                setattr(obj, infoname, recursecls())

        return obj

class MetaParams(MetaBase):
    # print("begin--------------------------------")
    def __new__(meta, name, bases, dct):
        # name,bases的值大概是这样：name: AroonUpDown bases: (<class 'backtrader.indicators.aroon.AroonUp'>, <class 'backtrader.indicators.aroon.AroonDown'>)
        # print(1,"metaprams","__new__","meta:",meta, "name:",name, "bases:",bases, "dct:",dct)
        # print(1,"metaprams","__new__")
        # Remove params from class definition to avoid inheritance
        # (and hence "repetition")
        # 测试一下dct字典中有没有保存这三个key,经过测试，表明params、packages、frompackages这几个key是可能存在的，
        # if "params" in dct:
        #     print("dct has params","meta:",meta, "name:",name, "bases:",bases, "dct:",dct)
        # if 'packages' in dct:
        #     print("dct has 'packages'","meta:",meta, "name:",name, "bases:",bases, "dct:",dct)
        # if 'frompackages' in dct:
        #     print("dct has 'frompackages'","meta:",meta, "name:",name, "bases:",bases, "dct:",dct)
        # if len(bases)>1:
        #     print("bases",bases)
        #     print(1,"metaprams","__new__","meta:",meta, "name:",name, "bases:",bases, "dct:",dct)
        # 如果dct字典中有params这个key，就删除，并保存到newparams中
        newparams = dct.pop('params', ())
        # 如果存在packages这个key，就删除，然后保存到newpackages中，值类似于这样：'packages': (('pandas', 'pd'), ('statsmodels.api', 'sm'))
        packs = 'packages'
        newpackages = tuple(dct.pop(packs, ()))  # remove before creation
        # 如果存在frompackages这个key,就删除，然后保存到fnewpackages中，类似于这样的值： (('numpy', ('asarray', 'log10', 'polyfit', 'sqrt', 'std', 'subtract')),)
        fpacks = 'frompackages'
        fnewpackages = tuple(dct.pop(fpacks, ()))  # remove before creation
        
        # Create the new class - this pulls predefined "params"
        # 创建一个新的类,这个new并没有调用MetaBase类的donew
        cls = super(MetaParams, meta).__new__(meta, name, bases, dct)
        
        # Pulls the param class out of it - default is the empty class
        # 获取cls的params属性，由于前面已经从dct中删除了，基本上params的值就等于AutoInfoClass
        params = getattr(cls, 'params', AutoInfoClass)

        # Pulls the packages class out of it - default is the empty class
        # 这两句返回的是空的元组,这两句写的有失水准，getattr本身获取的应该就是空的元组，又用了一个tuple函数去初始化，浪费了计算资源。尝试改为不用tuple的
        packages = tuple(getattr(cls, packs, ())) # backtrader自带
        fpackages = tuple(getattr(cls, fpacks, ())) # backtrader自带
        # packages = getattr(cls, packs, ())
        # fpackages = getattr(cls, fpacks, ())

        # get extra (to the right) base classes which have a param attribute
        # 从bases类中获取相应的params的值
        morebasesparams = [x.params for x in bases[1:] if hasattr(x, 'params')]

        # Get extra packages, add them to the packages and put all in the class
        # 从bases类中获取packages,然后添加到packages中，这里面似乎不需要循环所有的每个元组了，考虑修改代码如下：
        for y in [x.packages for x in bases[1:] if hasattr(x, packs)]:
            packages += tuple(y) # backtrader自带
        for y in [x.frompackages for x in bases[1:] if hasattr(x, fpacks)]:
            fpackages += tuple(y) # backtrader自带
        # for x in [x for x in bases[1:] if hasattr(x, packs)]:
        #     packages += x.packages
        # for x in [x for x in bases[1:] if hasattr(x, fpacks)]:
        #     fpackages += x.frompackages 
        # 设置packages和frompackages的属性值
        cls.packages = packages + newpackages
        cls.frompackages = fpackages + fnewpackages
        # AutoInfoClass._derive设置类的参数
        # Subclass and store the newly derived params class
        cls.params = params._derive(name, newparams, morebasesparams)
        # if len(cls.packages)>0:
        #     print(cls.packages)

        return cls

    def donew(cls, *args, **kwargs):
        # print(2,"metaprams","donew",cls)
        # cls.__module__返回cls定义所在的文件
        # sys.modules返回本地的module
        # clsmod用于返回具体的类，比如，如果cls是bt.Cerebro(),clsmod的结果是：
        # <module 'backtrader.cerebro' from '/home/yun/anaconda3/lib/python3.8/site-packages/backtrader/cerebro.py'>
        clsmod = sys.modules[cls.__module__]
        # import specified packages
        # 循环packages的路径,尝试了cerebro和strategy，发现这两个cls.packages都是空元组，如果空元组，很多操作就没有了，如果有具体的packages,就进入下面的循环
        # 使用下面的几行代码测试了一下，发现cls.packages和cls.frompackages这两个都是空元组，没有什么用处，所以这下面的一些代码可能是多余的,至少在一个普通策略中是多余的
        # if len(cls.packages)>0 or len(cls.frompackages)>0:
        #     print(cls.__name__)
        #     print(cls.packages)
        #     print(cls.frompackages)
        for p in cls.packages:
            # 如果p是元组或者列表,就拆分这个列表或者元组,否则就让palias等于p，比如(('pandas', 'pd'), ('statsmodels.api', 'sm'))，或者这样的值：('collections', 'math')
            if isinstance(p, (tuple, list)):
                p, palias = p
            else:
                palias = p
            # 动态加载包，p是具体需要加载的包
            pmod = __import__(p)
            # 看下这个包调用的层数,比如backtrader就是调用了一层，backtrader.date2num就是调用了两层，用len(plevels)判断
            plevels = p.split('.')
            # 英文注释部分是一个举例
            if p == palias and len(plevels) > 1:  # 'os.path' not aliased
                setattr(clsmod, pmod.__name__, pmod)  # set 'os' in module

            else:  # aliased and/or dots
                for plevel in plevels[1:]:  # recurse down the mod
                    pmod = getattr(pmod, plevel)

                setattr(clsmod, palias, pmod)

        # import from specified packages - the 2nd part is a string or iterable
        for p, frompackage in cls.frompackages:
            if isinstance(frompackage, string_types):
                frompackage = (frompackage,)  # make it a tuple

            for fp in frompackage:
                if isinstance(fp, (tuple, list)):
                    fp, falias = fp
                else:
                    fp, falias = fp, fp  # assumed is string

                # complain "not string" without fp (unicode vs bytes)
                pmod = __import__(p, fromlist=[str(fp)])
                pattr = getattr(pmod, fp)
                setattr(clsmod, falias, pattr)
                for basecls in cls.__bases__:
                    setattr(sys.modules[basecls.__module__], falias, pattr)
        # 下面是用于给cls设定具体的参数，后续比较方便使用cls.p或者cls.params调用具体的参数
        # Create params and set the values from the kwargs
        params = cls.params()
        # print("params",cls.params,cls.params())
        # params的值类似于这样： <backtrader.metabase.AutoInfoClass_OrderBase_Order_SellOrder object at 0x7f2fc14dc7f0>
        for pname, pdef in cls.params._getitems():
            setattr(params, pname, kwargs.pop(pname, pdef))

        # Create the object and set the params in place
        # 创建类，然后赋予params、p属性值
        _obj, args, kwargs = super(MetaParams, cls).donew(*args, **kwargs)
        _obj.params = params
        _obj.p = params  # shorter alias

        # Parameter values have now been set before __init__
        return _obj, args, kwargs


class ParamsBase(with_metaclass(MetaParams, object)):
    pass  # stub to allow easy subclassing without metaclasses

# 设置了一个新的类，这个类可以通过index或者name直接获取相应的值
class ItemCollection(object):
    '''
    Holds a collection of items that can be reached by

      - Index
      - Name (if set in the append operation)
    '''
    def __init__(self):
        self._items = list()
        self._names = list()
    # 长度
    def __len__(self):
        return len(self._items)
    # 添加数据
    def append(self, item, name=None):
        setattr(self, name, item)
        self._items.append(item)
        if name:
            self._names.append(name)
    # 根据index返回值
    def __getitem__(self, key):
        return self._items[key]
    # 获取全部的名字
    def getnames(self):
        return self._names
    # 获取相应的name和value这样一对一对的值
    def getitems(self):
        return zip(self._names, self._items)
    # 根据名字获取value
    def getbyname(self, name):
        idx = self._names.index(name)
        return self._items[idx]
