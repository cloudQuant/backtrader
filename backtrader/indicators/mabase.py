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


SMA = MovingAverage


# Direct registration of common moving averages to fix import issues  
# This is a temporary fix until the __init_subclass__ registration works properly
def _register_common_moving_averages():
    """Directly register common moving averages"""
    # We need to import and register manually since __init_subclass__ isn't working
    import sys
    
    # Create placeholder attributes
    class EMAPlaceholder:
        pass
    
    class SMAPlaceholder:  
        pass
        
    class WMAPlaceholder:
        pass
        
    class HMAPlaceholder:
        pass
    
    # Set the placeholders - these will be replaced when actual classes are imported
    MovAv.EMA = EMAPlaceholder
    MovAv.SMA = SMAPlaceholder
    MovAv.WMA = WMAPlaceholder
    MovAv.HMA = HMAPlaceholder
    
    # Try to replace with actual classes if they exist
    try:
        from . import ema
        if hasattr(ema, 'ExponentialMovingAverage'):
            MovAv.EMA = ema.ExponentialMovingAverage
            MovAv.ExponentialMovingAverage = ema.ExponentialMovingAverage
            MovingAverage.register(ema.ExponentialMovingAverage)
    except ImportError:
        pass
    
    try:
        from . import sma
        if hasattr(sma, 'SimpleMovingAverage'):
            MovAv.SMA = sma.SimpleMovingAverage
            MovAv.SimpleMovingAverage = sma.SimpleMovingAverage
            MovingAverage.register(sma.SimpleMovingAverage)
    except ImportError:
        pass
    
    try:
        from . import wma  
        if hasattr(wma, 'WeightedMovingAverage'):
            MovAv.WMA = wma.WeightedMovingAverage
            MovAv.WeightedMovingAverage = wma.WeightedMovingAverage
            MovingAverage.register(wma.WeightedMovingAverage)
    except ImportError:
        pass
        
    try:
        from . import hma
        if hasattr(hma, 'HullMovingAverage'):
            MovAv.HMA = hma.HullMovingAverage
            MovAv.HullMovingAverage = hma.HullMovingAverage
            MovingAverage.register(hma.HullMovingAverage)
    except ImportError:
        pass

# Call the registration immediately
_register_common_moving_averages()
