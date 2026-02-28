---
title: TS (时间序列) 模式指南
description: 时间序列向量化加速回测
---

# TS (时间序列) 模式指南

TS (Time Series) 模式是一项性能优化功能,使用 pandas 和 NumPy 的向量化操作来加速回测。本指南将介绍如何有效使用 TS 模式。

## 什么是 TS 模式?

TS 模式通过一次性处理整个时间序列而不是逐根K线处理来实现**向量化回测**。这种方法利用:

- **pandas DataFrame/Series 操作** 实现高效数据处理
- **NumPy 数组操作** 进行数值计算
- **Cython 加速** 处理性能关键函数

### 工作原理

在标准 backtrader 模式下,数据逐根K线流动:

```python
# 标准模式: 逐根K线处理
for i in range(len(data)):
    indicator.calculate(i)
    strategy.next(i)
```

在 TS 模式下,数据分批向量化处理:

```python
# TS 模式: 向量化批量处理
indicator.once(0, len(data))  # 一次性计算所有值
```

## 性能优势

| 操作 | 标准模式 | TS 模式 | 加速比 |
|------|----------|---------|--------|
| SMA(20) 计算 | 1x | 10-20x | 快 10-20 倍 |
| EMA(20) 计算 | 1x | 15-25x | 快 15-25 倍 |
| RSI 计算 | 1x | 8-15x | 快 8-15 倍 |
| 完整回测 (10万根K线) | 基准 | 3-5x | 快 3-5 倍 |

*实际性能取决于策略复杂度和数据规模*

## 启用 TS 模式

### 方法 1: cerebro.run() 参数

```python
import backtrader as bt

cerebro = bt.Cerebro()

# 添加策略、数据、指标...
cerebro.adddata(data)
cerebro.addstrategy(MyStrategy)

# 启用 TS 模式
cerebro.run(ts_mode=True)
```

### 方法 2: 环境变量

```bash
# 运行前设置环境变量
export BACKTRADER_TS_MODE=1

python my_backtest.py
```

### 方法 3: 配置文件

```python
# backtrader_config.py
ts_mode = {
    'enabled': True,
    'use_cython': True,
}
```

## 何时使用 TS 模式

### 理想使用场景

1. **大数据集**: 10万+ 根K线
2. **多指标**: 5个以上技术指标
3. **优化运行**: 参数扫描
4. **历史回测**: 无实时交易需求
5. **简单策略**: 没有复杂状态管理的策略

### 不适合使用 TS 模式的场景

1. **实时交易**: 需要实时逐根K线处理
2. **复杂状态**: 有跨周期依赖的策略
3. **自定义指标**: 没有向量化 `once()` 方法的指标
4. **多数据源**: 不同步数据源的策略
5. **Tick 数据**: 高频数据 (改用 tick 模式)

## 代码示例

### 示例 1: 简单均线交叉

```python
import backtrader as bt
import pandas as pd

class SMACross(bt.Strategy):
    params = (('fast', 10), ('slow', 30))

    def __init__(self):
        # 这些指标支持向量化计算
        self.fast_sma = bt.indicators.SMA(self.data.close, period=self.p.fast)
        self.slow_sma = bt.indicators.SMA(self.data.close, period=self.p.slow)
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)

    def next(self):
        if not self.position:
            if self.crossover[0] > 0:
                self.buy()
        elif self.crossover[0] < 0:
            self.close()

# 加载数据
df = pd.read_csv('data.csv', parse_dates=['datetime'], index_col='datetime')
data = bt.feeds.PandasData(dataname=df)

# 创建 cerebro 并使用 TS 模式运行
cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(SMACross)

# 启用 TS 模式
result = cerebro.run(ts_mode=True)
```

### 示例 2: 多指标策略

```python
import backtrader as bt

class MultiIndicator(bt.Strategy):
    params = (
        ('rsi_period', 14),
        ('atr_period', 14),
        ('bb_period', 20),
    )

    def __init__(self):
        # 所有这些指标都支持向量化 once() 方法
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.bollinger = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period
        )

        # 使用内置操作进行自定义计算
        self.signal = (
            (self.rsi < 30) &  # 超卖
            (self.data.close < self.bollinger.lines.bot)  # 低于下轨
        )

    def next(self):
        if self.signal[0] and not self.position:
            size = cerebro.broker.getcash() * 0.95 / self.data.close[0]
            self.buy(size=size)

cerebro = bt.Cerebro()
# ... 添加数据 ...
cerebro.addstrategy(MultiIndicator)

# TS 模式在多指标情况下提供显著加速
result = cerebro.run(ts_mode=True)
```

### 示例 3: 自定义向量化指标

```python
import backtrader as bt
import numpy as np

class VectorizedMomentum(bt.Indicator):
    """支持向量化计算的自定义动量指标"""

    lines = ('momentum',)
    params = (('period', 10),)

    def __init__(self):
        # 标准模式计算 (逐根K线)
        # TS 模式将使用 once() (如果可用)

    def next(self):
        # 标准逐根K线计算
        self.lines.momentum[0] = (
            self.data.close[0] - self.data.close[-self.p.period]
        )

    def once(self, start, end):
        """TS 模式的向量化计算"""
        # 批量处理访问底层数组
        src = self.data.close.array
        dst = self.lines.momentum.array

        for i in range(start, end):
            if i >= self.p.period:
                dst[i] = src[i] - src[i - self.p.period]
            else:
                dst[i] = float('nan')

# 在策略中使用
class MomentumStrategy(bt.Strategy):
    def __init__(self):
        self.mom = VectorizedMomentum(self.data.close, period=20)

    def next(self):
        if self.mom[0] > 0 and not self.position:
            self.buy()
        elif self.mom[0] < 0:
            self.close()

cerebro = bt.Cerebro()
# ... 添加数据 ...
cerebro.addstrategy(MomentumStrategy)
result = cerebro.run(ts_mode=True)  # 使用向量化 once()
```

## Cython 加速

TS 模式可以使用 Cython 加速函数获得额外性能提升:

### 编译 Cython 扩展

```bash
# 进入 backtrader 目录
cd backtrader

# 编译 Cython 文件 (Unix/Mac)
python -W ignore compile_cython_numba_files.py

# 编译 Cython 文件 (Windows)
python -W ignore compile_cython_numba_files.py

# 安装带 Cython 扩展的版本
cd ..
pip install -U .
```

### 验证 Cython 可用

```python
import backtrader as bt

# 检查 Cython 加速是否可用
print(f"Cython 可用: {bt.use_cython()}")

# 运行时启用 Cython
cerebro = bt.Cerebro()
# ... 设置 ...
result = cerebro.run(ts_mode=True, use_cython=True)
```

## 性能基准测试

### 基准测试配置

| 参数 | 值 |
|------|-----|
| 数据点 | 100,000 根K线 |
| 指标 | SMA(10), SMA(30), RSI(14), ATR(14) |
| 策略 | 简单交叉 |
| 硬件 | M1 Pro, 16GB RAM |

### 结果

| 模式 | 执行时间 | K线/秒 |
|------|----------|--------|
| 标准模式 | 12.5s | 8,000 |
| TS 模式 (Python) | 4.2s | 23,800 |
| TS 模式 (Cython) | 2.8s | 35,700 |

### 基准测试你的策略

```python
import time
import backtrader as bt

# 标准模式
start = time.time()
result_standard = cerebro.run()
standard_time = time.time() - start

# TS 模式
start = time.time()
result_ts = cerebro.run(ts_mode=True)
ts_time = time.time() - start

print(f"标准模式: {standard_time:.2f}秒")
print(f"TS 模式: {ts_time:.2f}秒")
print(f"加速比: {standard_time/ts_time:.2f}x")
```

## 限制与注意事项

### 1. 策略兼容性

并非所有策略都能很好地使用 TS 模式:

```python
# 适用于 TS 模式
class GoodStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):
        if self.data.close[0] > self.sma[0]:
            self.buy()

# 可能不适用于 TS 模式
class ProblematicStrategy(bt.Strategy):
    def __init__(self):
        self.counter = 0

    def next(self):
        # 复杂状态跟踪
        self.counter += 1
        if self.counter > 5:
            self.counter = 0
            # 基于 counter 的某些操作
```

### 2. 数据源要求

TS 模式需要:

- **预加载数据**: 使用 `preload=True` (默认值)
- **单一时间周期**: TS 模式中不支持重采样过滤器
- **一致的数据**: 无缺口或缺失K线

```python
# TS 模式正确用法
data = bt.feeds.PandasData(
    dataname=df,
    preload=True,  # TS 模式必需
)

# 可能不适用于 TS 模式
data = bt.feeds.CSVGeneric(
    dataname='data.csv',
    preload=False  # TS 模式需要预加载数据
)
```

### 3. 指标要求

在 TS 模式下获得最佳性能,指标应实现 `once()`:

```python
class MyIndicator(bt.Indicator):
    lines = ('output',)

    def next(self):
        # 标准模式回退
        self.lines.output[0] = self.data.close[0] * 2

    def once(self, start, end):
        # TS 模式的向量化实现
        for i in range(start, end):
            self.lines.output.array[i] = self.data.close.array[i] * 2
```

### 4. 内存使用

TS 模式可能使用更多内存:

```python
# 对于非常大的数据集,控制内存使用
cerebro = bt.Cerebro()

# 即使在 TS 模式也使用 qbuffer 限制内存
data = bt.feeds.PandasData(dataname=df)
data.qbuffer(10000)  # 内存中只保留 1万根K线
cerebro.adddata(data)
```

## 高级配置

### 微调 TS 模式

```python
cerebro.run(
    ts_mode=True,          # 启用 TS 模式
    ts_batch_size=10000,   # 批量处理 (可选)
    runonce=True,          # 使用 once() 方法
    preload=True,          # 预加载所有数据
)
```

### 禁用特定优化

```python
# 如果需要,禁用特定 TS 功能
cerebro.run(
    ts_mode=True,
    ts_use_numpy=False,    # 使用纯 Python 而非 NumPy
    ts_vectorize=False,    # 禁用向量化
)
```

## 故障排查

### 问题: 策略结果不同

如果标准模式和 TS 模式结果不同:

1. **检查指标 `once()` 实现**:
   ```python
   # 确保 once() 产生与 next() 相同的结果
   ```

2. **验证数据加载**:
   ```python
   # 确保使用 preload=True
   ```

3. **检查状态依赖**:
   ```python
   # TS 模式可能不保留复杂状态
   ```

### 问题: 没有性能提升

1. **验证 TS 模式已启用**:
   ```python
   print(f"TS 模式激活: {cerebro.p.ts_mode}")
   ```

2. **检查指标兼容性**:
   ```python
   # 指标必须实现 once() 才能加速
   print(hasattr(my_indicator, 'once'))
   ```

3. **使用 Cython 扩展**:
   ```bash
   python setup.py build_ext --inplace
   ```

## 对比: TS 模式 vs CS 模式

| 特性 | TS 模式 | CS 模式 |
|------|---------|---------|
| **用途** | 时间序列向量化 | 横截面优化 |
| **使用场景** | 单资产,长历史 | 多资产组合 |
| **数据结构** | 2D (时间 x 特征) | 3D (时间 x 资产 x 特征) |
| **典型加速** | 3-5x | 2-3x |
| **内存使用** | 中等 | 较高 |

## 最佳实践

1. **TS 模式始终预加载数据**:
   ```python
   data = bt.feeds.PandasData(dataname=df, preload=True)
   ```

2. **使用支持 `once()` 的内置指标**:
   ```python
   # 好: 支持 once() 的内置指标
   sma = bt.indicators.SMA(self.data.close, period=20)
   ```

3. **优化前先分析**:
   ```python
   # 验证 TS 模式确实有助于你的特定策略
   ```

4. **充分测试**:
   ```python
   # 验证 TS 模式产生与标准模式相同的结果
   ```

5. **生产环境使用 Cython**:
   ```bash
   # 编译 Cython 扩展以获得最大性能
   ```

## 相关文档

- [CS 模式指南](cs-mode_zh.md) - 横截面优化
- [性能优化](performance-optimization_zh.md) - 通用优化技巧
- [策略 API](../api_reference/strategy.md) - 策略开发
- [指标参考](../api_reference/indicators.md) - 内置指标
