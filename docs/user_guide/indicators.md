# 指标系统指南

本指南详细介绍 Backtrader 的技术指标系统，包括内置指标的使用和自定义指标的开发。

## 内置指标

### 1. 趋势指标

#### 移动平均线
```python
# 简单移动平均线 (SMA)
sma = bt.indicators.SimpleMovingAverage(period=20)

# 指数移动平均线 (EMA)
ema = bt.indicators.ExponentialMovingAverage(period=20)

# 加权移动平均线 (WMA)
wma = bt.indicators.WeightedMovingAverage(period=20)

# 自适应移动平均线 (AMA)
ama = bt.indicators.AdaptiveMovingAverage(period=20)
```

#### 趋势跟踪
```python
# MACD
macd = bt.indicators.MACD(
    period_me1=12,    # 快线周期
    period_me2=26,    # 慢线周期
    period_signal=9   # 信号线周期
)

# 抛物线转向 (SAR)
sar = bt.indicators.ParabolicSAR(
    period=2,
    af=0.02,
    afmax=0.2
)
```

### 2. 震荡指标

#### 相对强弱指数 (RSI)
```python
rsi = bt.indicators.RSI(
    period=14,
    upperband=70,
    lowerband=30
)
```

#### 随机指标 (KD)
```python
stoch = bt.indicators.Stochastic(
    period=14,
    period_dfast=3,
    period_dslow=3
)
```

### 3. 波动率指标

#### 布林带
```python
bbands = bt.indicators.BollingerBands(
    period=20,
    devfactor=2.0
)
```

#### 平均真实波幅 (ATR)
```python
atr = bt.indicators.ATR(period=14)
```

## 自定义指标

### 1. 基本结构

```python
class MyIndicator(bt.Indicator):
    # 定义生成的线
    lines = ('myline',)
    
    # 定义参数
    params = (
        ('period', 20),
        ('factor', 2.0),
    )
    
    def __init__(self):
        # 初始化代码
        super(MyIndicator, self).__init__()
        
    def next(self):
        # 计算逻辑
        self.lines.myline[0] = self.data[0]
```

### 2. 计算方法

#### 使用 next() 方法
```python
class SimpleIndicator(bt.Indicator):
    lines = ('result',)
    params = (('period', 20),)
    
    def next(self):
        datasum = 0
        for i in range(self.p.period):
            datasum += self.data[-i]
        self.lines.result[0] = datasum / self.p.period
```

#### 使用 once() 方法
```python
class FastIndicator(bt.Indicator):
    lines = ('result',)
    params = (('period', 20),)
    
    def once(self, start, end):
        for i in range(start, end):
            datasum = sum(self.data.get(size=self.p.period, ago=i))
            self.lines.result[i] = datasum / self.p.period
```

### 3. 指标优化

#### 缓存计算结果
```python
class CachedIndicator(bt.Indicator):
    lines = ('result',)
    params = (('period', 20),)
    
    def __init__(self):
        super(CachedIndicator, self).__init__()
        self._cache = {}
        
    def next(self):
        key = tuple(self.data.get(size=self.p.period))
        if key in self._cache:
            self.lines.result[0] = self._cache[key]
            return
            
        result = self._calculate(key)
        self._cache[key] = result
        self.lines.result[0] = result
```

#### 使用 Cython
```python
# myindicator.pyx
cdef class FastIndicator:
    cdef double calculate(self, double[:] data):
        cdef double sum = 0
        cdef int i
        for i in range(len(data)):
            sum += data[i]
        return sum / len(data)
```

## 指标组合

### 1. 指标叠加

```python
class CombinedIndicator(bt.Indicator):
    lines = ('signal',)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(period=20)
        self.rsi = bt.indicators.RSI(period=14)
        
    def next(self):
        if self.sma[0] > self.data[0] and self.rsi[0] < 30:
            self.lines.signal[0] = 1
        elif self.sma[0] < self.data[0] and self.rsi[0] > 70:
            self.lines.signal[0] = -1
        else:
            self.lines.signal[0] = 0
```

### 2. 指标继承

```python
class EnhancedSMA(bt.indicators.SMA):
    lines = ('trigger',)
    params = (('trigger_level', 0),)
    
    def __init__(self):
        super(EnhancedSMA, self).__init__()
        self.lines.trigger = self.lines.sma > self.p.trigger_level
```

## 指标绘图

### 1. 基本绘图

```python
class PlottableIndicator(bt.Indicator):
    lines = ('line1', 'line2')
    plotinfo = dict(
        plot=True,
        subplot=True,
        plotname='My Indicator',
        plotabove=False
    )
    plotlines = dict(
        line1=dict(color='red'),
        line2=dict(color='blue')
    )
```

### 2. 高级绘图

```python
class AdvancedPlotIndicator(bt.Indicator):
    lines = ('upper', 'middle', 'lower')
    
    plotinfo = dict(
        plot=True,
        subplot=False,
        plotlinelabels=True
    )
    
    plotlines = dict(
        upper=dict(
            _name='Upper',
            color='green',
            ls='--'
        ),
        middle=dict(
            _name='Middle',
            color='blue',
            ls='-'
        ),
        lower=dict(
            _name='Lower',
            color='red',
            ls='--'
        )
    )
```

## 最佳实践

### 1. 性能优化

```python
class OptimizedIndicator(bt.Indicator):
    # 使用 __slots__ 减少内存使用
    __slots__ = ['_cache']
    
    # 预计算常用值
    def __init__(self):
        self._cache = {}
        self._precompute()
        
    def _precompute(self):
        # 预计算常用值
        pass
```

### 2. 错误处理

```python
class RobustIndicator(bt.Indicator):
    def next(self):
        try:
            # 计算逻辑
            pass
        except ZeroDivisionError:
            self.lines.result[0] = float('nan')
        except Exception as e:
            self.error(f"指标计算错误: {e}")
```

### 3. 文档和测试

```python
class WellDocumentedIndicator(bt.Indicator):
    """
    指标描述
    
    参数:
        - period (int): 计算周期
        - factor (float): 计算因子
    
    线:
        - result: 计算结果
    """
    
    def next(self):
        """
        计算当前值
        """
        pass
```

## 常见问题

1. **计算效率低**
   - 使用 once() 方法
   - 实现缓存机制
   - 使用 Cython 优化

2. **内存使用高**
   - 使用 __slots__
   - 清理缓存数据
   - 优化数据结构

3. **绘图问题**
   - 检查 plotinfo 设置
   - 验证数据有效性
   - 调整绘图参数

## 下一步

- 学习[策略开发](./strategies.md)
- 了解[参数优化](./optimization.md)
- 探索[回测分析](./analysis.md)
- 研究[实盘应用](../advanced/live_trading.md)
