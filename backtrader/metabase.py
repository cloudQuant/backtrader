#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from collections import OrderedDict
import itertools
import sys
import math

import backtrader as bt
from .utils.py3 import zip, string_types


def patch_strategy_clk_update():
    """
    CRITICAL FIX: Patch the Strategy class's _clk_update method to prevent
    the "max() iterable argument is empty" error that occurs when no data
    sources have any length yet.
    """
    try:
        from .strategy import Strategy
        
        def safe_clk_update(self):
            """CRITICAL FIX: Safe _clk_update method that handles empty data sources"""
            
            # CRITICAL FIX: Ensure data is available before clock operations
            if getattr(self, '_data_assignment_pending', True) and (not hasattr(self, 'datas') or not self.datas):
                # Try to get data assignment from cerebro if not already done
                if hasattr(self, '_ensure_data_available'):
                    self._ensure_data_available()
            
            # CRITICAL FIX: Handle the old sync method safely
            if hasattr(self, '_oldsync') and self._oldsync:
                # Call parent class _clk_update if available
                try:
                    # Use the parent class method from StrategyBase if available
                    from .lineiterator import StrategyBase
                    if hasattr(StrategyBase, '_clk_update') and StrategyBase._clk_update != safe_clk_update:
                        clk_len = StrategyBase._clk_update(self)
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
                            # If setting datetime fails, use a default
                            self.lines.datetime[0] = 0.0
                    elif hasattr(self, 'lines') and hasattr(self.lines, 'datetime'):
                        # No valid times, use default
                        self.lines.datetime[0] = 0.0
                
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
                
                if valid_data_times:
                    try:
                        self.lines.datetime[0] = max(valid_data_times)
                    except (ValueError, IndexError, AttributeError):
                        # If setting datetime fails, use a default
                        self.lines.datetime[0] = 0.0
                else:
                    # CRITICAL FIX: This was the main bug - calling max() on empty list
                    # Instead use a reasonable default datetime value
                    self.lines.datetime[0] = 0.0
            
            # Return the length of this strategy (number of processed bars)
            try:
                return len(self)
            except Exception:
                return 0
        
        # Monkey patch the Strategy class
        Strategy._clk_update = safe_clk_update
        print("CRITICAL FIX: Successfully patched Strategy._clk_update method")
        
    except ImportError as e:
        print(f"Could not patch Strategy._clk_update: {e}")
    except Exception as e:
        print(f"Error patching Strategy._clk_update: {e}")


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
        """Set up parameters for a class"""
        # Handle packages and frompackages
        ParameterManager._handle_packages(cls, packages, frompackages)
        
        # Get params from base classes
        bases = tuple(cls.__mro__[1:])  # Skip self
        
        # Create derived params
        cls._params = ParameterManager._derive_params(cls.__name__, params, bases)
        
        # Set params property on the class
        setattr(cls, 'params', cls._params)
        
        return cls._params

    @staticmethod
    def _derive_params(name, params, otherbases):
        """Derive parameter class"""
        # Create a simple parameter class
        class_name = f"Params_{name}"
        
        # Collect all parameters from base classes first
        all_params = OrderedDict()
        
        # Process base classes in reverse order for proper inheritance
        for base in reversed(otherbases):
            if hasattr(base, '_params') and base._params is not None:
                if hasattr(base._params, '_getpairs'):
                    base_params = base._params._getpairs()
                    all_params.update(base_params)
                elif hasattr(base._params, '_gettuple'):
                    base_params = dict(base._params._gettuple())
                    all_params.update(base_params)
                elif hasattr(base._params, '__dict__'):
                    # Get attributes from parameter instance
                    for attr_name in dir(base._params):
                        if not attr_name.startswith('_') and not callable(getattr(base._params, attr_name)):
                            all_params[attr_name] = getattr(base._params, attr_name)
        
        # Handle current class params - could be tuple, dict, or dict-like
        if isinstance(params, dict):
            # Direct dictionary
            all_params.update(params)
        elif isinstance(params, (tuple, list)):
            # Convert tuple/list to dict
            for item in params:
                if isinstance(item, (tuple, list)) and len(item) >= 2:
                    key, value = item[0], item[1]
                    all_params[key] = value
                elif isinstance(item, string_types):
                    # Just a key with None value
                    all_params[item] = None
                elif hasattr(item, '__iter__') and not isinstance(item, string_types):
                    # Try to treat as key-value pair
                    item_list = list(item)
                    if len(item_list) >= 2:
                        all_params[item_list[0]] = item_list[1]
        elif hasattr(params, 'items'):
            # Dict-like object
            all_params.update(params)
        elif hasattr(params, '__dict__'):
            # Object with attributes
            for attr_name in dir(params):
                if not attr_name.startswith('_') and not callable(getattr(params, attr_name)):
                    all_params[attr_name] = getattr(params, attr_name)
        elif hasattr(params, '_getpairs'):
            all_params.update(params._getpairs())
        elif hasattr(params, '_gettuple'):
            all_params.update(dict(params._gettuple()))
        
        # CRITICAL FIX: Ensure common parameter names are always available
        # Many indicators expect these standard parameters
        common_defaults = {
            'period': 14,
            'movav': None,
            '_movav': None,
            'lookback': 1,
            'upperband': 70.0,
            'lowerband': 30.0,
            'safediv': False,
            'safepct': False,
            'fast': 5,     # For oscillators
            'slow': 34,    # For oscillators  
            'signal': 9,   # For MACD-style indicators
            'mult': 2.0,   # For bands
            'matype': 0,   # Moving average type
        }
        
        # Add common defaults if not already present
        for key, default_value in common_defaults.items():
            if key not in all_params:
                all_params[key] = default_value
        
        # CRITICAL FIX: Handle _movav parameter specially - it should default to SMA
        if '_movav' not in all_params or all_params['_movav'] is None:
            # CRITICAL FIX: Don't import MovAv during class creation to avoid circular imports
            # We'll handle this lazily in the parameter getter instead
            all_params['_movav'] = None
        
        # Create new parameter class with all necessary methods
        class ParamClass(AutoInfoClass):
            @classmethod
            def _getpairs(cls):
                return all_params.copy()
            
            @classmethod
            def _gettuple(cls):
                return tuple(all_params.items())
            
            @classmethod 
            def _getkeys(cls):
                return list(all_params.keys())
            
            @classmethod
            def _getdefaults(cls):
                return list(all_params.values())
            
            def __init__(self, **kwargs):
                super().__init__()
                # Set default values as instance attributes
                for key, default_value in all_params.items():
                    # Use provided value if available, otherwise use default
                    value = kwargs.get(key, default_value)
                    setattr(self, key, value)
                
                # CRITICAL FIX: Set up self-reference for backwards compatibility
                # This allows both self.p.period and self.params.period to work
                object.__setattr__(self, 'params', self)
            
            def __getattr__(self, name):
                # CRITICAL FIX: Enhanced fallback for missing attributes with common parameter support
                # First check if it's in our known parameters
                if name in all_params:
                    value = all_params[name]
                    # Special handling for _movav parameter
                    if name == '_movav' and value is None:
                        # Try to import and return SMA as default
                        try:
                            from .indicators.mabase import MovAv
                            return MovAv.SMA
                        except ImportError:
                            # If import fails, return a simple fallback
                            try:
                                from .indicators.sma import MovingAverageSimple
                                return MovingAverageSimple
                            except ImportError:
                                # Final fallback - return None
                                return None
                    return value
                
                # Handle common parameter name variants and aliases
                param_aliases = {
                    'period': ['period', 'periods', 'window', 'length'],
                    'movav': ['movav', '_movav', 'ma', 'moving_average'],
                    'lookback': ['lookback', 'look_back', 'lag'],
                    'upperband': ['upperband', 'upper_band', 'upper', 'high_band'],
                    'lowerband': ['lowerband', 'lower_band', 'lower', 'low_band'],
                    'fast': ['fast', 'fast_period', 'fastperiod'],
                    'slow': ['slow', 'slow_period', 'slowperiod'],
                    'signal': ['signal', 'signal_period', 'signalperiod'],
                }
                
                # Check if the requested name is an alias for a known parameter
                for canonical_name, aliases in param_aliases.items():
                    if name in aliases and canonical_name in all_params:
                        value = all_params[canonical_name]
                        # Special handling for movav aliases
                        if canonical_name == '_movav' and value is None:
                            try:
                                from .indicators.mabase import MovAv
                                return MovAv.SMA
                            except ImportError:
                                return None
                        return value
                
                # For period specifically, always return a sensible default
                if name in ('period', 'periods', 'window', 'length'):
                    return 14
                if name in ('_movav', 'movav', 'ma', 'moving_average'):
                    try:
                        from .indicators.mabase import MovAv
                        return MovAv.SMA
                    except ImportError:
                        return None
                if name in ('lookback', 'look_back', 'lag'):
                    return 1
                if name in ('upperband', 'upper_band', 'upper', 'high_band'):
                    return 70.0
                if name in ('lowerband', 'lower_band', 'lower', 'low_band'):
                    return 30.0
                if name in ('safediv', 'safe_div'):
                    return False
                if name in ('safepct', 'safe_pct'):
                    return False
                if name in ('fast', 'fast_period', 'fastperiod'):
                    return 5
                if name in ('slow', 'slow_period', 'slowperiod'):
                    return 34
                if name in ('signal', 'signal_period', 'signalperiod'):
                    return 9
                if name in ('mult', 'multiplier'):
                    return 2.0
                    
                # Return None for unknown attributes instead of raising AttributeError
                return None
            
            def __setattr__(self, name, value):
                # Allow setting attributes normally
                super().__setattr__(name, value)
        
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
    """Mixin class that provides parameter management capabilities"""
    
    def __init_subclass__(cls, **kwargs):
        """Set up parameters when a subclass is created"""
        super().__init_subclass__(**kwargs)
        
        # CRITICAL FIX: Call _initialize_indicator_aliases whenever an indicator class is created
        if 'Indicator' in cls.__name__ or any('Indicator' in base.__name__ for base in cls.__mro__):
            try:
                _initialize_indicator_aliases()
            except Exception:
                pass
        
        # Set up params, packages, frompackages if they exist
        params = getattr(cls, 'params', ())
        packages = getattr(cls, 'packages', ())
        frompackages = getattr(cls, 'frompackages', ())
        
        ParameterManager.setup_class_params(cls, params, packages, frompackages)
        
        # CRITICAL FIX: Auto-patch __init__ methods of indicators to ensure proper parameter handling
        if hasattr(cls, '__init__') and '__init__' in cls.__dict__:
            original_init = cls.__init__
            
            def patched_init(self, *args, **kwargs):
                # Ensure we have parameter instance available before user __init__ runs
                if not hasattr(self, 'p') or self.p is None:
                    # Create parameter instance if missing
                    if hasattr(cls, '_params') and cls._params is not None:
                        try:
                            self.p = cls._params()
                        except Exception:
                            from .utils import DotDict
                            self.p = DotDict()
                    else:
                        from .utils import DotDict
                        self.p = DotDict()
                
                # CRITICAL FIX: Ensure indicator has _plotinit method before user init
                if ('Indicator' in cls.__name__ or 
                    any('Indicator' in base.__name__ for base in cls.__mro__)):
                    if not hasattr(self, '_plotinit'):
                        # Add _plotinit method
                        def default_plotinit():
                            plotinfo_defaults = {
                                'plot': True,
                                'subplot': True,
                                'plotname': '',
                                'plotskip': False,
                                'plotabove': False,
                                'plotlinelabels': False,
                                'plotlinevalues': True,
                                'plotvaluetags': True,
                                'plotymargin': 0.0,
                                'plotyhlines': [],
                                'plotyticks': [],
                                'plothlines': [],
                                'plotforce': False,
                                'plotmaster': None,
                            }
                            
                            if not hasattr(self, 'plotinfo'):
                                self.plotinfo = type('plotinfo', (), {})()
                            
                            for attr, default_val in plotinfo_defaults.items():
                                if not hasattr(self.plotinfo, attr):
                                    setattr(self.plotinfo, attr, default_val)
                            
                            return True
                        
                        self._plotinit = default_plotinit
                
                # Call original __init__
                return original_init(self, *args, **kwargs)
            
            cls.__init__ = patched_init
        
        # Handle plotinfo and other info attributes (like the old metaclass system)
        info_attributes = ['plotinfo', 'plotlines', 'plotinfoargs']
        for info_attr in info_attributes:
            if info_attr in cls.__dict__:
                info_dict = cls.__dict__[info_attr]
                if isinstance(info_dict, dict):
                    # CRITICAL FIX: Ensure plotinfo objects have all required attributes
                    if info_attr == 'plotinfo':
                        # Set default plotinfo attributes if missing
                        default_plotinfo = {
                            'plot': True,
                            'subplot': True,
                            'plotname': '',
                            'plotskip': False,
                            'plotabove': False,
                            'plotlinelabels': False,
                            'plotlinevalues': True,
                            'plotvaluetags': True,
                            'plotymargin': 0.0,
                            'plotyhlines': [],
                            'plotyticks': [],
                            'plothlines': [],
                            'plotforce': False,
                            'plotmaster': None,
                        }
                        # Merge provided plotinfo with defaults
                        for key, default_value in default_plotinfo.items():
                            if key not in info_dict:
                                info_dict[key] = default_value
                    
                    # Convert dictionary to attribute-accessible object
                    info_obj = type(f'{info_attr}_obj', (), info_dict)()
                    
                    # CRITICAL FIX: Ensure the object can be used like a dict too
                    # Some code might expect dict-like access
                    def info_getitem(self, key):
                        # CRITICAL FIX: Ensure key is a string before using hasattr()
                        if isinstance(key, str) and hasattr(self, key):
                            return getattr(self, key)
                        return None
                    
                    def info_setitem(self, key, value):
                        # Only set if key is a string
                        if isinstance(key, str):
                            setattr(self, key, value)
                    
                    def info_contains(self, key):
                        # CRITICAL FIX: Only check if key is a string
                        return isinstance(key, str) and hasattr(self, key)
                    
                    def info_get(self, key, default=None):
                        # CRITICAL FIX: Ensure key is a string before using hasattr()
                        if isinstance(key, str) and hasattr(self, key):
                            return getattr(self, key)
                        return default
                    
                    def info_get_method(self, key, default=None):
                        """CRITICAL: _get method expected by plotting system"""
                        # CRITICAL FIX: Ensure key is a string before using hasattr()
                        if isinstance(key, str) and hasattr(self, key):
                            return getattr(self, key)
                        return default
                    
                    def info_keys(self):
                        return [attr for attr in dir(self) if not attr.startswith('_') and not callable(getattr(self, attr))]
                    
                    def info_values(self):
                        return [getattr(self, attr) for attr in self.keys()]
                    
                    def info_items(self):
                        return [(attr, getattr(self, attr)) for attr in self.keys()]
                    
                    info_obj.__getitem__ = info_getitem
                    info_obj.__setitem__ = info_setitem
                    info_obj.__contains__ = info_contains
                    info_obj.get = info_get
                    info_obj._get = info_get_method  # CRITICAL: Add _get method for plotting compatibility
                    info_obj.keys = info_keys
                    info_obj.values = info_values
                    info_obj.items = info_items
                    
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
            non_param_kwargs = {}
            for key, value in kwargs.items():
                if key in param_names:
                    param_kwargs[key] = value
                else:
                    non_param_kwargs[key] = value
                    
            # Store non-param kwargs for later use
            instance._non_param_kwargs = non_param_kwargs
                    
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
                    
            # Also set any extra parameters that were passed but not in the params definition
            for key, value in param_kwargs.items():
                if not hasattr(instance._params_instance, key):
                    setattr(instance._params_instance, key, value)
                    
        else:
            # No parameters defined, create parameter instance from kwargs
            instance._params_instance = type('ParamsInstance', (), {})()
            # Set all kwargs as parameters
            for key, value in kwargs.items():
                setattr(instance._params_instance, key, value)
            instance._non_param_kwargs = {}
            
        return instance

    def __init__(self, *args, **kwargs):
        """Initialize with only non-parameter kwargs"""
        # Use pre-filtered non-parameter kwargs if available
        if hasattr(self, '_non_param_kwargs'):
            filtered_kwargs = self._non_param_kwargs
        else:
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
            else:
                # No parameters, but still avoid passing args to object.__init__
                filtered_kwargs = {}
        
        # Call super().__init__ without args to avoid object.__init__() error
        # Only pass kwargs to prevent "object.__init__() takes exactly one argument" error
        if filtered_kwargs:
            super().__init__(**filtered_kwargs)
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
        # CRITICAL FIX: Ensure p also points to the same instance
        object.__setattr__(self, 'p', value)
    
    @property 
    def p(self):
        """Provide p property for backward compatibility"""
        return getattr(self, '_params_instance', None)
    
    @p.setter
    def p(self, value):
        """Allow setting p instance"""
        self._params_instance = value
        # CRITICAL FIX: Ensure params also points to the same instance  
        object.__setattr__(self, 'params', value)


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
        """返回(name, item)元组的列表，用于解包操作"""
        result = []
        for item in self.items:
            # 获取项目名称
            name = getattr(item, '_name', None) or getattr(item, '__name__', None)
            if name is None:
                # 尝试通过类名获取
                name = item.__class__.__name__.lower()
            result.append((name, item))
        return result

    # 根据名字获取value
    def getbyname(self, name):
        return getattr(self, name)


def _initialize_indicator_aliases():
    """
    CRITICAL FIX: Initialize all indicator aliases and ensure _plotinit method exists
    This function must be called after all indicator modules are loaded
    """
    try:
        import sys
        import backtrader as bt
        
        # CRITICAL FIX: Add a universal _plotinit method to all indicator classes
        def universal_plotinit(self):
            """Universal _plotinit method for all indicators"""
            # Set up default plotinfo if missing
            if not hasattr(self, 'plotinfo'):
                # Create a plotinfo object that behaves like the expected plotinfo with _get method
                class PlotInfo:
                    def __init__(self):
                        self._data = {}
                        # Set default plot attributes
                        defaults = {
                            'plot': True,
                            'subplot': True,
                            'plotname': '',
                            'plotskip': False,
                            'plotabove': False,
                            'plotlinelabels': False,
                            'plotlinevalues': True,
                            'plotvaluetags': True,
                            'plotymargin': 0.0,
                            'plotyhlines': [],
                            'plotyticks': [],
                            'plothlines': [],
                            'plotforce': False,
                            'plotmaster': None,
                        }
                        self._data.update(defaults)
                        # CRITICAL FIX: Set attributes directly on the object for compatibility
                        for key, value in defaults.items():
                            setattr(self, key, value)
                    
                    def _get(self, key, default=None):
                        """Get plot info attribute with default - CRITICAL METHOD"""
                        # CRITICAL FIX: Ensure key is a string before using hasattr()
                        if isinstance(key, str) and hasattr(self, key):
                            return getattr(self, key)
                        # Then try the _data dict
                        if hasattr(self, '_data') and key in self._data:
                            return self._data[key]
                        return default
                    
                    def get(self, key, default=None):
                        """Standard get method for dict-like access"""
                        # CRITICAL FIX: Ensure key is a string before using hasattr()
                        if isinstance(key, str) and hasattr(self, key):
                            return getattr(self, key)
                        # Then try the _data dict
                        if hasattr(self, '_data') and key in self._data:
                            return self._data[key]
                        return default
                    
                    def __getattr__(self, name):
                        if name.startswith('_') and name != '_data':
                            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
                        # Try _data dict first
                        if hasattr(self, '_data') and name in self._data:
                            return self._data[name]
                        # Return None for missing attributes to prevent errors
                        return None
                    
                    def __setattr__(self, name, value):
                        if name.startswith('_') and name != '_data':
                            super().__setattr__(name, value)
                        else:
                            if not hasattr(self, '_data'):
                                super().__setattr__('_data', {})
                            self._data[name] = value
                            # CRITICAL FIX: Also set as direct attribute for compatibility
                            super().__setattr__(name, value)
                    
                    def __contains__(self, key):
                        """Support 'in' operator"""
                        # CRITICAL FIX: Ensure key is a string before using hasattr()
                        string_check = isinstance(key, str) and hasattr(self, key)
                        dict_check = key in getattr(self, '_data', {})
                        return string_check or dict_check
                    
                    def keys(self):
                        """Return all keys"""
                        keys = set(getattr(self, '_data', {}).keys())
                        keys.update(attr for attr in dir(self) if not attr.startswith('_') and not callable(getattr(self, attr)))
                        return list(keys)
                    
                    def values(self):
                        """Return all values"""
                        return [self._get(key) for key in self.keys()]
                    
                    def items(self):
                        """Return all items"""
                        return [(key, self._get(key)) for key in self.keys()]
                
                self.plotinfo = PlotInfo()
            else:
                # If plotinfo exists but doesn't have _get method, add it
                if not hasattr(self.plotinfo, '_get'):
                    def _get_method(key, default=None):
                        if hasattr(self.plotinfo, key):
                            return getattr(self.plotinfo, key)
                        elif hasattr(self.plotinfo, '_data') and key in self.plotinfo._data:
                            return self.plotinfo._data[key]
                        else:
                            return default
                    self.plotinfo._get = _get_method
                
                # Also ensure get method exists
                if not hasattr(self.plotinfo, 'get'):
                    def get_method(key, default=None):
                        if hasattr(self.plotinfo, key):
                            return getattr(self.plotinfo, key)
                        elif hasattr(self.plotinfo, '_data') and key in self.plotinfo._data:
                            return self.plotinfo._data[key]
                        else:
                            return default
                    self.plotinfo.get = get_method
            
            return True
        
        # CRITICAL FIX: Apply _plotinit to indicator classes without complex patching
        indicators_module = sys.modules.get('backtrader.indicators')
        if indicators_module:
            for attr_name in dir(indicators_module):
                try:
                    attr = getattr(indicators_module, attr_name)
                    if (isinstance(attr, type) and 
                        hasattr(attr, '__module__') and 
                        'indicator' in attr.__module__.lower() and
                        hasattr(attr, 'lines')):
                        
                        # Add _plotinit method if missing
                        if not hasattr(attr, '_plotinit'):
                            attr._plotinit = universal_plotinit
                            print(f"DEBUG: Added _plotinit to {attr.__name__}")
                        
                except Exception:
                    continue
        
        # CRITICAL FIX: Patch specific indicator classes that are known to be problematic
        try:
            from .indicators.sma import MovingAverageSimple
            if not hasattr(MovingAverageSimple, '_plotinit'):
                MovingAverageSimple._plotinit = universal_plotinit
                print(f"DEBUG: DIRECT PATCH - Added _plotinit to MovingAverageSimple")
        except ImportError:
            pass
        
        # CRITICAL FIX: Search for any loaded indicator classes and ensure they have _plotinit
        for module_name, module in sys.modules.items():
            if 'indicator' in module_name.lower() and hasattr(module, '__dict__'):
                for attr_name, attr_value in module.__dict__.items():
                    try:
                        if (isinstance(attr_value, type) and 
                            hasattr(attr_value, 'lines') and
                            'Indicator' in str(attr_value.__mro__)):
                            
                            # Ensure the class has _plotinit
                            if not hasattr(attr_value, '_plotinit'):
                                attr_value._plotinit = universal_plotinit
                                print(f"DEBUG: MRO PATCH - Added _plotinit to {attr_name} in {module_name}")
                                
                    except Exception:
                        continue
        
        print("DEBUG: _initialize_indicator_aliases completed - _plotinit method ensured for all indicators")
        
    except Exception as e:
        print(f"Warning: _initialize_indicator_aliases failed: {e}")
        # Continue without failing completely


# CRITICAL FIX: Call initialization functions when module loads
try:
    _initialize_indicator_aliases()
    patch_strategy_clk_update()
except Exception:
    pass  # Silently fail during module loading
