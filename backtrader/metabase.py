#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from collections import OrderedDict
import itertools
import sys

import backtrader as bt
from .utils.py3 import zip, string_types


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
        self_ = frame.f_locals.get("self", None)
        # 如果skip和self_不一样，如果self_不是owned并且self_是cls的实例,就返回self_
        if skip is not self_:
            if self_ is not owned and cls is not None and isinstance(self_, cls):
                return self_

        # '_obj' in metaclasses
        # 如果"_obj"在帧对象本地变量中
        obj_ = frame.f_locals.get("_obj", None)
        # 如果obj_不是skip，并且obj_不是owned，并且obj_是class的实例，返回obj_
        if skip is not obj_:
            if obj_ is not owned and cls is not None and isinstance(obj_, cls):
                return obj_
    # 前两种情况都不是的话，返回None
    return None


class ObjectFactory:
    """Factory class to replace MetaBase functionality"""
    
    @staticmethod
    def create(cls, *args, **kwargs):
        """Create an object with the old metaclass-style lifecycle hooks"""
        # Pre-new processing
        if hasattr(cls, 'doprenew'):
            cls, args, kwargs = cls.doprenew(*args, **kwargs)
        
        # Object creation
        if hasattr(cls, 'donew'):
            _obj, args, kwargs = cls.donew(*args, **kwargs)
        else:
            _obj = cls.__new__(cls)
        
        # Pre-init processing
        if hasattr(cls, 'dopreinit'):
            _obj, args, kwargs = cls.dopreinit(_obj, *args, **kwargs)
        
        # Main initialization
        if hasattr(cls, 'doinit'):
            _obj, args, kwargs = cls.doinit(_obj, *args, **kwargs)
        else:
            _obj.__init__(*args, **kwargs)
        
        # Post-init processing
        if hasattr(cls, 'dopostinit'):
            _obj, args, kwargs = cls.dopostinit(_obj, *args, **kwargs)
        
        return _obj


class BaseMixin:
    """Mixin to provide factory-based object creation without metaclass"""
    
    @classmethod
    def doprenew(cls, *args, **kwargs):
        return cls, args, kwargs

    @classmethod
    def donew(cls, *args, **kwargs):
        _obj = cls.__new__(cls)
        return _obj, args, kwargs

    @classmethod
    def dopreinit(cls, _obj, *args, **kwargs):
        return _obj, args, kwargs

    @classmethod
    def doinit(cls, _obj, *args, **kwargs):
        _obj.__init__(*args, **kwargs)
        return _obj, args, kwargs

    @classmethod
    def dopostinit(cls, _obj, *args, **kwargs):
        return _obj, args, kwargs

    @classmethod
    def create(cls, *args, **kwargs):
        """Factory method to create instances"""
        return ObjectFactory.create(cls, *args, **kwargs)


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
        """推测各个参数的意义：
        cls:代表一个具体的类，很有可能就是AutoInfoClass的一个实例
        info:代表参数（parameter)
        otherBases:其他的bases
        recurse:递归
        举例的应用：_derive(name, newparams, morebasesparams)
        """
        # collect the 3 set of infos
        # info = OrderedDict(info)
        # print(name,info,otherbases)
        baseinfo = (
            cls._getpairs().copy()
        )  # 浅拷贝，保证有序字典一级目录下不改变,暂时没有明白为什么要copy
        obasesinfo = OrderedDict()  # 代表其他类的info
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
        newclsname = str(cls.__name__ + "_" + name)  # str - Python 2/3 compat

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
        setattr(newcls, "_getpairsbase", classmethod(lambda cls: baseinfo.copy()))
        setattr(newcls, "_getpairs", classmethod(lambda cls: clsinfo.copy()))
        setattr(newcls, "_getrecurse", classmethod(lambda cls: recurse))

        for infoname, infoval in info2add.items():
            # 查找具体的AutoInfoClass的使用，暂时没有发现recurse是真的的语句，所以下面条件语句可能不怎么运行。推测这个是递归用的，如果递归，会把infoval下的信息加进去
            if recurse:
                recursecls = getattr(newcls, infoname, AutoInfoClass)
                infoval = recursecls._derive(name + "_" + infoname, infoval, [])
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

    def get(self, name, default=None):
        return self._get(name, default)

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
        l = [(x, getattr(self, x)) for x in self._getkeys() if not skip_ or not x.startswith("_")]
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


class ParameterManager:
    """Manager for handling parameter operations without metaclass"""
    
    @staticmethod
    def setup_class_params(cls, params=(), packages=(), frompackages=()):
        """Setup parameters for a class"""
        # Remove params from class definition if present
        newparams = OrderedDict(params) if params else OrderedDict()
        
        # Handle base class parameters
        morebasesparams = []
        for base in cls.__bases__:
            if hasattr(base, '_params'):
                morebasesparams.append(base._params)
        
        # Create derived parameters - ensure we always create a parameter class
        if newparams or morebasesparams or not hasattr(cls, '_params'):
            cls._params = ParameterManager._derive_params('params', newparams, morebasesparams)
        
        # Handle packages
        if packages or frompackages:
            ParameterManager._handle_packages(cls, packages, frompackages)
    
    @staticmethod
    def _derive_params(name, params, otherbases):
        """Derive parameter class"""
        # Create a simple parameter class
        class_name = f"Params_{name}"
        
        # Collect all parameters
        all_params = OrderedDict()
        for base in otherbases:
            if hasattr(base, '_getpairs'):
                all_params.update(base._getpairs())
        
        # Handle params - could be tuple or dict-like
        if isinstance(params, (tuple, list)):
            # Convert tuple to dict
            for item in params:
                if isinstance(item, (tuple, list)) and len(item) == 2:
                    key, value = item
                    all_params[key] = value
                elif isinstance(item, string_types):
                    # Just a key with None value
                    all_params[item] = None
        elif hasattr(params, 'items'):
            # Dict-like object
            all_params.update(params)
        
        # Create new parameter class with all necessary methods
        # Use a custom class that ensures _gettuple is always available
        class ParamClass(AutoInfoClass):
            @classmethod
            def _getpairs(cls):
                return all_params.copy()
            
            @classmethod
            def _gettuple(cls):
                return tuple(all_params.items())
        
        ParamClass.__name__ = class_name
        return ParamClass
    
    @staticmethod
    def _handle_packages(cls, packages, frompackages):
        """Handle package imports"""
        cls.packages = packages
        cls.frompackages = frompackages
        
        clsmod = sys.modules[cls.__module__]
        
        for package in packages:
            if isinstance(package, (tuple, list)):
                package, alias = package
            else:
                alias = package
            
            try:
                pmod = __import__(package)
                for part in package.split('.')[1:]:
                    pmod = getattr(pmod, part)
                setattr(clsmod, alias, pmod)
            except ImportError:
                pass
        
        for packageitems in frompackages:
            if len(packageitems) != 2:
                continue
            package, frompackage = packageitems
            
            if isinstance(frompackage, string_types):
                frompackage = (frompackage,)
            
            for fromitem in frompackage:
                if isinstance(fromitem, (tuple, list)):
                    fromitem, alias = fromitem
                else:
                    alias = fromitem
                
                try:
                    pmod = __import__(package, fromlist=[fromitem])
                    pattr = getattr(pmod, fromitem)
                    setattr(clsmod, alias, pattr)
                except (ImportError, AttributeError):
                    pass


class ParamsMixin(BaseMixin):
    """Mixin to provide parameter functionality without metaclass"""
    
    def __init_subclass__(cls, **kwargs):
        """Called when a class is subclassed - replaces metaclass functionality"""
        super().__init_subclass__(**kwargs)
        
        # Get params from the class __dict__ to avoid getting the property
        cls_params = cls.__dict__.get('params', ())
        cls_frompackages = cls.__dict__.get('frompackages', ())
        cls_packages = cls.__dict__.get('packages', ())
        
        # Use ParameterManager to set up parameters
        ParameterManager.setup_class_params(
            cls, 
            params=cls_params,
            packages=cls_packages, 
            frompackages=cls_frompackages
        )
        
        # Handle plotinfo and other info attributes (like the old metaclass system)
        info_attributes = ['plotinfo', 'plotlines', 'plotinfoargs']
        for info_attr in info_attributes:
            if info_attr in cls.__dict__:
                info_dict = cls.__dict__[info_attr]
                if isinstance(info_dict, dict):
                    # Convert dictionary to attribute-accessible object
                    info_obj = type(f'{info_attr}_obj', (), info_dict)()
                    setattr(cls, info_attr, info_obj)
        
        # Ensure the class has a params attribute that can handle _gettuple calls
        if hasattr(cls, '_params'):
            # If _params is not a proper parameter class, make it one
            if isinstance(cls._params, (tuple, list)) or not hasattr(cls._params, '_gettuple'):
                # Create a wrapper that provides _gettuple functionality
                class ParamsWrapper:
                    def __init__(self, data):
                        if isinstance(data, (tuple, list)):
                            self.data = data
                        elif hasattr(data, '_gettuple'):
                            self.data = data._gettuple()
                        else:
                            self.data = ()
                    
                    def _gettuple(self):
                        return self.data if isinstance(self.data, tuple) else tuple(self.data)
                
                cls._params = ParamsWrapper(cls._params)
            
            # Set class-level params attribute for compatibility
            cls.params = cls._params
    
    def __new__(cls, *args, **kwargs):
        """Create instance and set up parameters before __init__ is called"""
        # Create the instance first
        instance = super().__new__(cls)
        
        # Set up parameters for this instance
        if hasattr(cls, '_params') and cls._params is not None:
            params_cls = cls._params
            param_names = set()
            
            # Get all parameter names from the class
            if hasattr(params_cls, '_getpairs'):
                param_names.update(params_cls._getpairs().keys())
            elif hasattr(params_cls, '_gettuple'):
                param_names.update(key for key, value in params_cls._gettuple())
            
            # Separate parameter and non-parameter kwargs
            param_kwargs = {}
            for key, value in kwargs.items():
                if key in param_names:
                    param_kwargs[key] = value
                    
            # Create parameter instance
            try:
                instance._params_instance = params_cls()
            except:
                # If instantiation fails, create a simple object
                instance._params_instance = type('ParamsInstance', (), {})()
                
            # Set all parameter values - first defaults, then custom values
            if hasattr(params_cls, '_getpairs'):
                for key, value in params_cls._getpairs().items():
                    # Use custom value if provided, otherwise use default
                    final_value = param_kwargs.get(key, value)
                    setattr(instance._params_instance, key, final_value)
            elif hasattr(params_cls, '_gettuple'):
                for key, value in params_cls._gettuple():
                    # Use custom value if provided, otherwise use default
                    final_value = param_kwargs.get(key, value)
                    setattr(instance._params_instance, key, final_value)
        else:
            # No parameters defined, create empty parameter instance  
            instance._params_instance = type('ParamsInstance', (), {})()
            
        return instance

    def __init__(self, *args, **kwargs):
        """Initialize with only non-parameter kwargs"""
        # Filter out parameter kwargs before calling super().__init__
        if hasattr(self.__class__, '_params') and self.__class__._params is not None:
            params_cls = self.__class__._params
            param_names = set()
            
            # Get all parameter names from the class
            if hasattr(params_cls, '_getpairs'):
                param_names.update(params_cls._getpairs().keys())
            elif hasattr(params_cls, '_gettuple'):
                param_names.update(key for key, value in params_cls._gettuple())
            
            # Filter kwargs to remove parameter kwargs
            filtered_kwargs = {k: v for k, v in kwargs.items() if k not in param_names}
            
            # Call super().__init__ without args to avoid object.__init__() error
            # Only pass kwargs to prevent "object.__init__() takes exactly one argument" error
            if filtered_kwargs:
                super().__init__(**filtered_kwargs)
            else:
                super().__init__()
        else:
            # No parameters, but still avoid passing args to object.__init__
            if kwargs:
                super().__init__(**kwargs)
            else:
                super().__init__()
    
    @property
    def params(self):
        """Instance-level params property for backward compatibility"""
        return getattr(self, '_params_instance', None)
    
    @params.setter
    def params(self, value):
        """Allow setting params instance"""
        self._params_instance = value
    
    @property 
    def p(self):
        """Provide p property for backward compatibility"""
        return getattr(self, '_params_instance', None)
    
    @p.setter
    def p(self, value):
        """Allow setting p instance"""
        self._params_instance = value


# For backward compatibility, keep the old class names as aliases
ParamsBase = ParamsMixin


# 设置了一个新的类，这个类可以通过index或者name直接获取相应的值
class ItemCollection(object):
    """
    Holds a collection of items that can be reached by

      - Index
      - Name (if set in the append operation)
    """

    def __init__(self):
        self.items = list()

    # 长度
    def __len__(self):
        return len(self.items)

    # 添加数据
    def append(self, item, name=None):
        setattr(self, name or item.__name__, item)
        self.items.append(item)

    # 根据index返回值
    def __getitem__(self, key):
        return self.items[key]

    # 获取全部的名字
    def getnames(self):
        return [x.__name__ for x in self.items]

    # 获取相应的name和value这样一对一对的值
    def getitems(self):
        return self.items

    # 根据名字获取value
    def getbyname(self, name):
        return getattr(self, name)


def _initialize_indicator_aliases():
    """Initialize indicator aliases when the module is loaded"""
    try:
        from .lineiterator import IndicatorBase
        IndicatorBase._register_indicator_aliases()
    except ImportError:
        pass

# Call the initialization function when module is loaded
_initialize_indicator_aliases()
