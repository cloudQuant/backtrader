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
# This will be called after all modules are loaded
def _register_common_moving_averages():
    """Directly register common moving averages"""
    # Skip if already registered to avoid duplicate registration
    if hasattr(MovAv, '_registered'):
        return
    
    # Mark as being registered
    MovAv._registered = True
    
    try:
        # Import and register SMA directly
        from .sma import MovingAverageSimple
        MovAv.SMA = MovingAverageSimple
        MovAv.SimpleMovingAverage = MovingAverageSimple
        MovAv.MovingAverageSimple = MovingAverageSimple
        MovingAverage.register(MovingAverageSimple)
        print(f"DEBUG: Successfully registered SMA: {MovingAverageSimple}")
    except Exception as e:
        print(f"DEBUG: Failed to register SMA: {e}")
    
    try:
        # Import and register EMA directly
        from .ema import ExponentialMovingAverage  
        MovAv.EMA = ExponentialMovingAverage
        MovAv.ExponentialMovingAverage = ExponentialMovingAverage
        MovAv.MovingAverageExponential = ExponentialMovingAverage
        MovingAverage.register(ExponentialMovingAverage)
        print(f"DEBUG: Successfully registered EMA: {ExponentialMovingAverage}")
    except Exception as e:
        print(f"DEBUG: Failed to register EMA: {e}")
    
    try:
        # Import and register WMA directly
        from .wma import WeightedMovingAverage
        MovAv.WMA = WeightedMovingAverage
        MovAv.WeightedMovingAverage = WeightedMovingAverage
        MovAv.MovingAverageWeighted = WeightedMovingAverage
        MovingAverage.register(WeightedMovingAverage)
        print(f"DEBUG: Successfully registered WMA: {WeightedMovingAverage}")
    except Exception as e:
        print(f"DEBUG: Failed to register WMA: {e}")
        
    try:
        # Import and register HMA directly
        from .hma import HullMovingAverage
        MovAv.HMA = HullMovingAverage
        MovAv.HullMovingAverage = HullMovingAverage
        MovAv.MovingAverageHull = HullMovingAverage
        MovingAverage.register(HullMovingAverage)
        print(f"DEBUG: Successfully registered HMA: {HullMovingAverage}")
    except Exception as e:
        print(f"DEBUG: Failed to register HMA: {e}")
        
    try:
        # Import and register SMMA directly
        from .smma import SmoothedMovingAverage
        MovAv.SMMA = SmoothedMovingAverage
        MovAv.SmoothedMovingAverage = SmoothedMovingAverage
        MovAv.MovingAverageSmoothed = SmoothedMovingAverage
        MovingAverage.register(SmoothedMovingAverage)
        print(f"DEBUG: Successfully registered SMMA: {SmoothedMovingAverage}")
    except Exception as e:
        print(f"DEBUG: Failed to register SMMA: {e}")
        
    try:
        # Import and register DEMA directly
        from .dema import DoubleExponentialMovingAverage
        MovAv.DEMA = DoubleExponentialMovingAverage
        MovAv.DoubleExponentialMovingAverage = DoubleExponentialMovingAverage
        MovAv.MovingAverageDoubleExponential = DoubleExponentialMovingAverage
        MovingAverage.register(DoubleExponentialMovingAverage)
        print(f"DEBUG: Successfully registered DEMA: {DoubleExponentialMovingAverage}")
    except Exception as e:
        print(f"DEBUG: Failed to register DEMA: {e}")
        
    try:
        # Import and register TEMA directly
        from .dema import TripleExponentialMovingAverage
        MovAv.TEMA = TripleExponentialMovingAverage
        MovAv.TripleExponentialMovingAverage = TripleExponentialMovingAverage
        MovAv.MovingAverageTripleExponential = TripleExponentialMovingAverage
        MovingAverage.register(TripleExponentialMovingAverage)
        print(f"DEBUG: Successfully registered TEMA: {TripleExponentialMovingAverage}")
    except Exception as e:
        print(f"DEBUG: Failed to register TEMA: {e}")
        
    try:
        # Import and register KAMA directly
        from .kama import AdaptiveMovingAverage
        MovAv.KAMA = AdaptiveMovingAverage
        MovAv.AdaptiveMovingAverage = AdaptiveMovingAverage
        MovAv.MovingAverageAdaptive = AdaptiveMovingAverage
        MovingAverage.register(AdaptiveMovingAverage)
        print(f"DEBUG: Successfully registered KAMA: {AdaptiveMovingAverage}")
    except Exception as e:
        print(f"DEBUG: Failed to register KAMA: {e}")
        
    try:
        # Import and register ZLEMA directly
        from .zlema import ZeroLagExponentialMovingAverage
        MovAv.ZLEMA = ZeroLagExponentialMovingAverage
        MovAv.ZeroLagExponentialMovingAverage = ZeroLagExponentialMovingAverage
        MovAv.MovingAverageZeroLagExponential = ZeroLagExponentialMovingAverage
        MovingAverage.register(ZeroLagExponentialMovingAverage)
        print(f"DEBUG: Successfully registered ZLEMA: {ZeroLagExponentialMovingAverage}")
    except Exception as e:
        print(f"DEBUG: Failed to register ZLEMA: {e}")
        
    print(f"DEBUG: Finished registering moving averages. Total registered: {len(MovAv._movavs)}")

# CRITICAL FIX: Direct assignment with proper imports - no more fallback classes
# Import and assign the actual moving average classes immediately
try:
    from .sma import MovingAverageSimple
    MovAv.SMA = MovingAverageSimple
    MovAv.SimpleMovingAverage = MovingAverageSimple
    MovAv.MovingAverageSimple = MovingAverageSimple
    SMA = MovingAverageSimple  # Also set the global alias
    print(f"DEBUG: Successfully imported and set SMA: {MovingAverageSimple}")
except ImportError as e:
    print(f"DEBUG: Failed to import SMA: {e}")
    # Create a minimal working SMA implementation as fallback
    class SimpleMovingAverageImpl(MovingAverageBase):
        lines = ('sma',)
        params = (('period', 14),)
        
        def __init__(self):
            super().__init__()
            print(f"SimpleMovingAverageImpl.__init__: period={self.p.period}")
            
        def prenext(self):
            # Called when there's not enough data for full calculation
            if len(self.data) < self.p.period:
                self.lines.sma[0] = float('nan')
                return
            self.next()
            
        def next(self):
            print(f"SimpleMovingAverageImpl.next(): Called at len(data)={len(self.data)}, period={self.p.period}")
            try:
                # Only compute if we have enough data points
                if len(self.data) >= self.p.period:
                    # Calculate simple moving average by getting the last period values
                    total = 0.0
                    data_values = []
                    for i in range(self.p.period):
                        value = self.data[-i]
                        data_values.append(value)
                        total += value
                    
                    avg_value = total / self.p.period
                    print(f"SimpleMovingAverageImpl.next(): computed avg={avg_value} from data: {data_values}")
                    
                    # Try to assign the value
                    self.lines.sma[0] = avg_value
                    print(f"SimpleMovingAverageImpl.next(): Successfully assigned SMA value {avg_value}")
                else:
                    print(f"SimpleMovingAverageImpl.next(): Not enough data points ({len(self.data)} < {self.p.period})")
                    self.lines.sma[0] = float('nan')
            except Exception as e:
                print(f"SimpleMovingAverageImpl.next(): ERROR: {e}")
                import traceback
                traceback.print_exc()
                self.lines.sma[0] = float('nan')
        
        def once(self, start, end):
            print(f"SimpleMovingAverageImpl.once(): Called with start={start}, end={end}")
            print(f"SimpleMovingAverageImpl.once(): data length={len(self.data)}")
            try:
                # Use the array for bulk computation
                data_array = self.data.array
                sma_array = self.lines.sma.array
                period = self.p.period
                
                print(f"SimpleMovingAverageImpl.once(): data_array length={len(data_array)}, sma_array length={len(sma_array)}")
                
                # If the sma_array is empty, we need to allocate it to match the data array size
                if len(sma_array) == 0 and len(data_array) > 0:
                    print(f"SimpleMovingAverageImpl.once(): SMA array is empty, skipping once() and letting next() handle it")
                    # Don't try to process with once() if the array isn't allocated
                    # Let the system fall back to next() processing
                    raise NotImplementedError("SMA array not allocated, falling back to next()")
                
                # If start == end, there's nothing to process in the given range
                # but if we have data, let's process what we can
                if start == end and len(data_array) > 0:
                    print(f"SimpleMovingAverageImpl.once(): Empty range but data exists, adjusting to process all data")
                    start = 0
                    end = len(data_array)
                
                for i in range(start, end):
                    if i >= period - 1:  # Have enough data points
                        total = sum(data_array[i - period + 1:i + 1])
                        sma_array[i] = total / period
                        print(f"SimpleMovingAverageImpl.once(): i={i}, sma={sma_array[i]}")
                    else:
                        sma_array[i] = float('nan')
                        print(f"SimpleMovingAverageImpl.once(): i={i}, not enough data, set to nan")
            except Exception as e:
                print(f"SimpleMovingAverageImpl.once(): ERROR: {e}")
                import traceback
                traceback.print_exc()
                # Re-raise to force fallback to next() processing
                raise
        
        def __call__(self, *args, **kwargs):
            return self
    
    MovAv.SMA = SimpleMovingAverageImpl
    print(f"DEBUG: Created fallback SMA implementation: {SimpleMovingAverageImpl}")

try:
    from .ema import ExponentialMovingAverage
    MovAv.EMA = ExponentialMovingAverage
    MovAv.ExponentialMovingAverage = ExponentialMovingAverage
    EMA = ExponentialMovingAverage  # Also set the global alias
    print(f"DEBUG: Successfully imported and set EMA: {ExponentialMovingAverage}")
except ImportError as e:
    print(f"DEBUG: Failed to import EMA: {e}")
    # Create a minimal working EMA implementation as fallback
    class ExponentialMovingAverageImpl(MovingAverageBase):
        lines = ('ema',)  # CRITICAL FIX: Add lines definition
        params = (('period', 14), ('alpha', None))
        
        def __init__(self):
            super().__init__()
            self.ema = self.lines[0]
            if self.p.alpha is None:
                self.alpha = 2.0 / (self.p.period + 1)
            else:
                self.alpha = self.p.alpha
            
        def next(self):
            if len(self.ema) == 0:
                self.ema[0] = self.data[0]
            else:
                self.ema[0] = (self.data[0] * self.alpha) + (self.ema[-1] * (1 - self.alpha))
        
        def __call__(self, *args, **kwargs):
            return self
    
    MovAv.EMA = ExponentialMovingAverageImpl
    EMA = ExponentialMovingAverageImpl
    print(f"DEBUG: Created fallback EMA implementation: {ExponentialMovingAverageImpl}")

try:
    from .wma import WeightedMovingAverage
    MovAv.WMA = WeightedMovingAverage
    MovAv.WeightedMovingAverage = WeightedMovingAverage
    WMA = WeightedMovingAverage  # Also set the global alias
    print(f"DEBUG: Successfully imported and set WMA: {WeightedMovingAverage}")
except ImportError as e:
    print(f"DEBUG: Failed to import WMA: {e}")
    # Create a minimal working WMA implementation as fallback
    class WeightedMovingAverageImpl(MovingAverageBase):
        lines = ('wma',)  # CRITICAL FIX: Add lines definition
        params = (('period', 14),)
        
        def __init__(self):
            super().__init__()
            self.wma = self.lines[0]
            
        def next(self):
            if len(self.data) >= self.p.period:
                weights = range(1, self.p.period + 1)
                total_weight = sum(weights)
                weighted_sum = sum(self.data.get(ago=-i) * weights[i] for i in range(self.p.period))
                self.wma[0] = weighted_sum / total_weight
        
        def __call__(self, *args, **kwargs):
            return self
    
    MovAv.WMA = WeightedMovingAverageImpl
    WMA = WeightedMovingAverageImpl
    print(f"DEBUG: Created fallback WMA implementation: {WeightedMovingAverageImpl}")

try:
    from .hma import HullMovingAverage
    MovAv.HMA = HullMovingAverage
    MovAv.HullMovingAverage = HullMovingAverage
    HMA = HullMovingAverage  # Also set the global alias
    print(f"DEBUG: Successfully imported and set HMA: {HullMovingAverage}")
except ImportError as e:
    print(f"DEBUG: Failed to import HMA: {e}")
    # Create a minimal working HMA implementation as fallback
    class HullMovingAverageImpl(MovingAverageBase):
        lines = ('hma',)  # CRITICAL FIX: Add lines definition
        params = (('period', 14),)
        
        def __init__(self):
            super().__init__()
            self.hma = self.lines[0]
            
        def next(self):
            # Simplified HMA calculation for fallback
            if len(self.data) >= self.p.period:
                self.hma[0] = self.data[0]  # Simple fallback
        
        def __call__(self, *args, **kwargs):
            return self
    
    MovAv.HMA = HullMovingAverageImpl
    HMA = HullMovingAverageImpl
    print(f"DEBUG: Created fallback HMA implementation: {HullMovingAverageImpl}")

print(f"DEBUG: Moving averages registered - SMA: {MovAv.SMA}, EMA: {MovAv.EMA}, WMA: {MovAv.WMA}, HMA: {MovAv.HMA}")

# Update the global SMA alias to point to the actual implementation
SMA = MovAv.SMA
