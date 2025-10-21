#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-


from . import Indicator


# 移动平均类，用于设置指标的名字
class MovingAverage(object):
    """MovingAverage (alias MovAv)

    A placeholder to gather all Moving Average Types in a single place.

    Instantiating a SimpleMovingAverage can be achieved as follows::

      sma = MovingAverage.Simple(self.data, period)

    Or using the shorter aliases::

      sma = MovAv.SMA(self.data, period)

    or with the full (forwards and backwards) names:

      sma = MovAv.SimpleMovingAverage(self.data, period)

      sma = MovAv.MovingAverageSimple(self.data, period)

    """

    # 移动平均类的保存
    _movavs = []

    @classmethod
    def register(cls, regcls):
        # 如果指标中没有_notregister或者_notregister的值是False，就继续运行，进行注册，否则直接返回
        if getattr(regcls, "_notregister", False):
            return
        # 把需要计算的指标类添加进去
        cls._movavs.append(regcls)
        # 类的名称，并且把类名称设置成cls的属性，属性值为具体的类
        clsname = regcls.__name__
        setattr(cls, clsname, regcls)

        # 具体指标的别名，如果指标开头是MovingAverage,那么，用后面的值作为别名，如果结尾是MovingAverage，用前面的值作为别名
        # 如果取得的别名不是空字符串，那么就把别名也设置成属性，该属性的值为这个类
        clsalias = ""
        if clsname.endswith("MovingAverage"):
            clsalias = clsname.split("MovingAverage")[0]
        elif clsname.startswith("MovingAverage"):
            clsalias = clsname.split("MovingAverage")[1]

        if clsalias:
            setattr(cls, clsalias, regcls)
        
        # CRITICAL FIX: Process the alias attribute if it exists
        # Many indicators define their own aliases like alias = ("SMA", "SimpleMovingAverage")
        if hasattr(regcls, 'alias'):
            aliases = regcls.alias
            # Support both tuple and single string
            if isinstance(aliases, str):
                aliases = (aliases,)
            # Register each alias
            for alias_name in aliases:
                if alias_name and isinstance(alias_name, str):
                    setattr(cls, alias_name, regcls)


# 移动平均的别名
class MovAv(MovingAverage):
    pass  # alias


# 移动平均的基类，增加参数和画图的设置 - refactored to remove metaclass
class MovingAverageBase(Indicator):
    # 参数
    params = (("period", 30),)
    # 默认画到主图上
    plotinfo = dict(subplot=False)

    def __init_subclass__(cls, **kwargs):
        """Register moving average classes automatically"""
        super().__init_subclass__(**kwargs)
        # Register any MovingAverage with the placeholder to allow the automatic
        # creation of envelopes and oscillators
        MovingAverage.register(cls)


# SMA = MovingAverage
#
#
# # Direct registration of common moving averages to fix import issues
# # This will be called after all modules are loaded
# def _register_common_moving_averages():
#     """Directly register common moving averages"""
#     # Skip if already registered to avoid duplicate registration
#     if hasattr(MovAv, '_registered'):
#         return
#
#     # Mark as being registered
#     MovAv._registered = True
#
#     try:
#         # Import and register SMA directly
#         from .sma import MovingAverageSimple
#         MovAv.SMA = MovingAverageSimple
#         MovAv.SimpleMovingAverage = MovingAverageSimple
#         MovAv.MovingAverageSimple = MovingAverageSimple
#         MovingAverage.register(MovingAverageSimple)
#     except Exception:
#         pass
#
#     try:
#         # Import and register EMA directly
#         from .ema import ExponentialMovingAverage
#         MovAv.EMA = ExponentialMovingAverage
#         MovAv.ExponentialMovingAverage = ExponentialMovingAverage
#         MovAv.MovingAverageExponential = ExponentialMovingAverage
#         MovingAverage.register(ExponentialMovingAverage)
#     except Exception:
#         pass
#
#     try:
#         # Import and register WMA directly
#         from .wma import WeightedMovingAverage
#         MovAv.WMA = WeightedMovingAverage
#         MovAv.WeightedMovingAverage = WeightedMovingAverage
#         MovAv.MovingAverageWeighted = WeightedMovingAverage
#         MovingAverage.register(WeightedMovingAverage)
#     except Exception:
#         pass
#
#     try:
#         # Import and register HMA directly
#         from .hma import HullMovingAverage
#         MovAv.HMA = HullMovingAverage
#         MovAv.HullMovingAverage = HullMovingAverage
#         MovAv.MovingAverageHull = HullMovingAverage
#         MovingAverage.register(HullMovingAverage)
#     except Exception:
#         pass
#
#     try:
#         # Import and register SMMA directly
#         from .smma import SmoothedMovingAverage
#         MovAv.SMMA = SmoothedMovingAverage
#         MovAv.SmoothedMovingAverage = SmoothedMovingAverage
#         MovAv.MovingAverageSmoothed = SmoothedMovingAverage
#         MovingAverage.register(SmoothedMovingAverage)
#     except Exception:
#         pass
#
#     try:
#         # Import and register DEMA directly
#         from .dema import DoubleExponentialMovingAverage
#         MovAv.DEMA = DoubleExponentialMovingAverage
#         MovAv.DoubleExponentialMovingAverage = DoubleExponentialMovingAverage
#         MovAv.MovingAverageDoubleExponential = DoubleExponentialMovingAverage
#         MovingAverage.register(DoubleExponentialMovingAverage)
#     except Exception:
#         pass
#
#     try:
#         # Import and register TEMA directly
#         from .dema import TripleExponentialMovingAverage
#         MovAv.TEMA = TripleExponentialMovingAverage
#         MovAv.TripleExponentialMovingAverage = TripleExponentialMovingAverage
#         MovAv.MovingAverageTripleExponential = TripleExponentialMovingAverage
#         MovingAverage.register(TripleExponentialMovingAverage)
#     except Exception:
#         pass
#
#     try:
#         # Import and register KAMA directly
#         from .kama import AdaptiveMovingAverage
#         MovAv.KAMA = AdaptiveMovingAverage
#         MovAv.AdaptiveMovingAverage = AdaptiveMovingAverage
#         MovAv.MovingAverageAdaptive = AdaptiveMovingAverage
#         MovingAverage.register(AdaptiveMovingAverage)
#     except Exception:
#         pass
#
#     try:
#         # Import and register ZLEMA directly
#         from .zlema import ZeroLagExponentialMovingAverage
#         MovAv.ZLEMA = ZeroLagExponentialMovingAverage
#         MovAv.ZeroLagExponentialMovingAverage = ZeroLagExponentialMovingAverage
#         MovAv.MovingAverageZeroLagExponential = ZeroLagExponentialMovingAverage
#         MovingAverage.register(ZeroLagExponentialMovingAverage)
#     except Exception:
#         pass
#
# # Optimized import and assignment with proper error handling
# try:
#     from .sma import MovingAverageSimple
#     MovAv.SMA = MovingAverageSimple
#     MovAv.SimpleMovingAverage = MovingAverageSimple
#     MovAv.MovingAverageSimple = MovingAverageSimple
#     SMA = MovingAverageSimple  # Also set the global alias
# except ImportError:
#     # Create an optimized minimal working SMA implementation as fallback
#     class SimpleMovingAverageImpl(MovingAverageBase):
#         lines = ('sma',)
#         params = (('period', 14),)
#
#         def __init__(self):
#             super().__init__()
#
#         def prenext(self):
#             # Called when there's not enough data for full calculation
#             if len(self.data) < self.p.period:
#                 self.lines.sma[0] = float('nan')
#                 return
#             self.next()
#
#         def next(self):
#             """Optimized next() method for SMA calculation"""
#             if len(self.data) >= self.p.period:
#                 # Efficient calculation using list comprehension
#                 period_data = [self.data[-i] for i in range(self.p.period)]
#                 self.lines.sma[0] = sum(period_data) / self.p.period
#             else:
#                 self.lines.sma[0] = float('nan')
#
#         def once(self, start, end):
#             """Optimized batch calculation method"""
#             try:
#                 data_array = self.data.array
#                 sma_array = self.lines.sma.array
#                 period = self.p.period
#
#                 # If arrays aren't available, fallback to next() processing
#                 if not hasattr(data_array, '__len__') or not hasattr(sma_array, '__len__'):
#                     for i in range(start, end):
#                         self._next()
#                     return
#
#                 # If the sma_array is empty, fallback to next() processing
#                 if len(sma_array) == 0 and len(data_array) > 0:
#                     raise NotImplementedError("SMA array not allocated, falling back to next()")
#
#                 # Adjust range if needed
#                 if start == end and len(data_array) > 0:
#                     start = 0
#                     end = len(data_array)
#
#                 # Vectorized calculation for better performance
#                 for i in range(start, end):
#                     if i >= period - 1:
#                         window_sum = sum(data_array[i - period + 1:i + 1])
#                         sma_array[i] = window_sum / period
#                     else:
#                         sma_array[i] = float('nan')
#
#             except Exception:
#                 # Fallback to next() processing if once() fails
#                 for i in range(start, end):
#                     self._next()
#
#         def __call__(self, *args, **kwargs):
#             return self
#
#     MovAv.SMA = SimpleMovingAverageImpl
#
#     try:
#         from .ema import ExponentialMovingAverage
#         MovAv.EMA = ExponentialMovingAverage
#         MovAv.ExponentialMovingAverage = ExponentialMovingAverage
#         EMA = ExponentialMovingAverage  # Also set the global alias
#     except ImportError:
#         # Create an optimized minimal working EMA implementation as fallback
#         class ExponentialMovingAverageImpl(MovingAverageBase):
#             lines = ('ema',)
#             params = (('period', 14), ('alpha', None))
#
#             def __init__(self):
#                 super().__init__()
#                 self.ema = self.lines[0]
#                 if self.p.alpha is None:
#                     self.alpha = 2.0 / (self.p.period + 1)
#                 else:
#                     self.alpha = self.p.alpha
#
#             def next(self):
#                 if len(self.ema) == 0:
#                     self.ema[0] = self.data[0]
#                 else:
#                     self.ema[0] = (self.data[0] * self.alpha) + (self.ema[-1] * (1 - self.alpha))
#
#             def __call__(self, *args, **kwargs):
#                 return self
#
#         MovAv.EMA = ExponentialMovingAverageImpl
#         EMA = ExponentialMovingAverageImpl
#
#     try:
#         from .wma import WeightedMovingAverage
#         MovAv.WMA = WeightedMovingAverage
#         MovAv.WeightedMovingAverage = WeightedMovingAverage
#         WMA = WeightedMovingAverage  # Also set the global alias
#     except ImportError:
#         # Create an optimized minimal working WMA implementation as fallback
#         class WeightedMovingAverageImpl(MovingAverageBase):
#             lines = ('wma',)
#             params = (('period', 14),)
#
#             def __init__(self):
#                 super().__init__()
#                 self.wma = self.lines[0]
#
#             def next(self):
#                 if len(self.data) >= self.p.period:
#                     weights = range(1, self.p.period + 1)
#                     total_weight = sum(weights)
#                     weighted_sum = sum(self.data.get(ago=-i) * weights[i] for i in range(self.p.period))
#                     self.wma[0] = weighted_sum / total_weight
#
#             def __call__(self, *args, **kwargs):
#                 return self
#
#         MovAv.WMA = WeightedMovingAverageImpl
#         WMA = WeightedMovingAverageImpl
#
#     try:
#         from .hma import HullMovingAverage
#         MovAv.HMA = HullMovingAverage
#         MovAv.HullMovingAverage = HullMovingAverage
#         HMA = HullMovingAverage  # Also set the global alias
#     except ImportError:
#         # Create an optimized minimal working HMA implementation as fallback
#         class HullMovingAverageImpl(MovingAverageBase):
#             lines = ('hma',)
#             params = (('period', 14),)
#
#             def __init__(self):
#                 super().__init__()
#                 self.hma = self.lines[0]
#
#             def next(self):
#                 # Simplified HMA calculation for fallback
#                 if len(self.data) >= self.p.period:
#                     self.hma[0] = self.data[0]  # Simple fallback
#
#             def __call__(self, *args, **kwargs):
#                 return self
#
#         MovAv.HMA = HullMovingAverageImpl
#         HMA = HullMovingAverageImpl
#
# # Update the global SMA alias to point to the actual implementation
# SMA = MovAv.SMA
