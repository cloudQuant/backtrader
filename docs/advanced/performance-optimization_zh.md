---
title: 性能优化
description: 优化 Backtrader 性能的技巧
---

# 性能优化

Backtrader 的 dev 分支通过移除元类和各种优化实现了 **45% 的性能提升**。本指南介绍最大化回测性能的技巧。

## 快速优化

### 1. 禁用观察器

观察器会增加开销。不需要时禁用：

```python
# 禁用默认观察器
cerebro.run(stdstats=False)

# 仅添加需要的观察器
cerebro.addobserver(bt.observers.DrawDown)
```

### 2. 禁用绘图

绘图消耗内存。长时间回测时禁用：

```python
# 禁用所有绘图
cerebro.plot = False  # 或直接不调用 cerebro.plot()

# 禁用特定指标
self.sma.plotinfo.plot = False
```

### 3. 使用 qbuffer

使用循环缓冲区限制内存使用：

```python
data = bt.feeds.CSVGeneric(dataname='data.csv')
data.qbuffer(1000)  # 内存中仅保留最后 1000 根K线
```

## 执行模式

### `next()` vs `once()`

Backtrader 有两种执行模式：

| 模式 | 速度 | 复杂度 |
|------|-------|------------|
| `next()` | 基准 | 简单 |
| `once()` | 快 2-3 倍 | 复杂 |

**next() 模式** (默认):
```python
# 简单，逐K线执行
def next(self):
    if self.data.close[0] > self.sma[0]:
        self.buy()
```

**once() 模式** (需要实现):
```python
def once(self):
    # 一次处理所有K线
    # 必须处理数组操作
    pass
```

大多数内置指标实现了优化的 `once()` 方法。

## 指标优化

### 向量化操作

在指标中使用向量化计算：

```python
class FastSMA(bt.Indicator):
    lines = ('sma',)
    params = (('period', 20),)

    def __init__(self):
        # 向量化计算
        self.lines.sma = bt.indicators.PeriodN(
            self.data.close,
            period=self.p.period
        )
```

### 避免重复计算

缓存昂贵的计算：

```python
def __init__(self):
    self.atr = bt.indicators.ATR(self.data, period=14)
    self.upper = self.data.close + self.atr * 2
    self.lower = self.data.close - self.atr * 2

def next(self):
    # 使用预计算的值
    if self.data.close[0] > self.upper[0]:
        pass
```

## 数据加载优化

### 使用二进制格式

二进制格式加载比 CSV 更快：

```python
# 对大数据集使用 HDF5 或 Parquet
import pandas as pd

# 一次性保存为二进制格式
df.to_parquet('data.parquet')

# 加载更快
df = pd.read_parquet('data.parquet')
data = bt.feeds.PandasData(dataname=df)
```

### 预加载数据

```python
# 一次性将所有数据加载到内存 (执行更快)
data = bt.feeds.CSVGeneric(
    dataname='data.csv',
    preload=True  # 启动时加载整个文件
)
```

### 提前重采样

一次性重采样数据，而不是使用过滤器：

```python
# 与其运行时重采样
cerebro.resampledata(data, timeframe=bt.TimeFrame.Days)

# 不如预先重采样数据文件
```

## Cython 加速

Backtrader 使用 Cython 进行性能关键的计算：

### TS (时间序列) 模式

```python
# 使用 pandas 进行快速向量化操作
cerebro = bt.Cerebro()
cerebro.run(ts_mode=True)  # 启用 TS 模式
```

### CS (横截面) 模式

```python
# 多资产组合优化
cerebro = bt.Cerebro()
cerebro.run(cs_mode=True)  # 启用 CS 模式
```

### 编译 Cython 扩展

```bash
cd backtrader
python -W ignore compile_cython_numba_files.py
cd ..
pip install -U .
```

## 最小化热路径操作

### 在 next() 中避免

```python
def next(self):
    # ❌ 避免在热路径中调用昂贵的函数
    if len(self.data) > 100:  # 每根K线都调用 len()
        pass

    # ✅ 更好 - 使用直接属性
    if self.data._len > 100:
        pass
```

### 缓存属性

```python
def __init__(self):
    # 缓存查找
    self._data_close = self.data.close
    self._sma = self.sma

def next(self):
    # 使用缓存的引用
    if self._data_close[0] > self._sma[0]:
        self.buy()
```

## 并行优化

### 多策略回测

并行运行多个策略：

```python
# 如果 maxcpu > 1 将并行运行
cerebro.optstrategy(
    MyStrategy,
    period=range(10, 50, 10)
)
results = cerebro.run(maxcpu=4)  # 使用 4 个 CPU 核心
```

## 内存优化

### 限制内存中的K线数

```python
# 仅保留必要的K线
cerebro = bt.Cerebro()
cerebro.run(
    maxcpu=1,
    runonce=True,  # 单次通过
    preload=True   # 优化内存访问
)
```

### 使用高效的数据类型

```python
# 在精度不关键时使用 float32 而非 float64
import numpy as np

data = bt.feeds.PandasData(
    dataname=df.astype(np.float32)
)
```

## 经纪人优化

### 速度测试时禁用佣金

```python
# 原始速度测试时跳过佣金计算
cerebro.broker.setcommission(commission=0.0)
```

### 使用简单的现金设置

```python
# 直接设置现金更快
cerebro.broker.setcash(100000)

# 如果不需要，避免复杂的保证金计算
cerebro.broker.set_coc(True)  # 收盘时现金 (更快)
```

## 特定优化

### 指标分组

分组相关指标：

```python
def __init__(self):
    # 将计算分组
    ma_group = bt.indicators.SMA(self.data.close, period=20)
    self.sma = ma_group
    self.sma_lag = ma_group(-1)  # 使用缓存的计算
```

### 避免循环中的数据访问

```python
# ❌ 避免
def next(self):
    for i in range(100):
        value = self.data.close[i]  # 重复访问

# ✅ 更好
def __init__(self):
    self.data_close = self.data.close.get()  # 获取一次
```

## 性能分析

### 分析您的策略

```python
import cProfile
import pstats

# 分析执行
profiler = cProfile.Profile()
profiler.enable()

cerebro.run()

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # 前 20 个函数
```

### 计时执行

```python
import time

start = time.time()
cerebro.run()
elapsed = time.time() - start

print(f'执行时间: {elapsed:.2f} 秒')
print(f'处理的K线数: {len(data)}')
print(f'每秒K线数: {len(data)/elapsed:.0f}')
```

## 性能基准

在现代硬件上的预期性能：

| 数据点 | 策略 | 时间 |
|-------------|----------|------|
| 1万 | 简单 | < 1秒 |
| 10万 | 简单 | 1-3秒 |
| 100万 | 简单 | 10-30秒 |
| 10万 | 复杂 | 5-15秒 |
| 100万 | 复杂 | 60-180秒 |

*复杂 = 多个指标、多个数据源、自定义逻辑*

## 优化清单

- [ ] 禁用未使用的观察器 (`stdstats=False`)
- [ ] 禁用未使用的指标绘图 (`plotinfo.plot = False`)
- [ ] 长时间回测使用 `qbuffer()`
- [ ] 预加载数据 (`preload=True`)
- [ ] 使用二进制数据格式
- [ ] 在 `__init__` 中缓存属性查找
- [ ] 热路径中最小化 `len()`, `isinstance()` 调用
- [ ] 大数据集考虑 TS/CS 模式
- [ ] 编译 Cython 扩展
- [ ] 优化前先分析

## 下一步学习

- [TS 模式指南](ts-mode.md) - 时间序列优化
- [CS 模式指南](cs-mode.md) - 横截面优化
- [Strategy API](../api_reference/strategy_zh.md) - 策略开发
