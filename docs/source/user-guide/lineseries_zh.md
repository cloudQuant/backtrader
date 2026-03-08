---
title: LineSeries 时间序列 API
description: Backtrader LineSeries 完整 API 参考文档

---
# LineSeries 时间序列 API

`LineSeries` 是 Backtrader 中管理多线时间序列数据的核心类。它为数据源、指标、观察器等提供统一的时间序列数据访问接口，支持历史数据访问、切片操作、pandas 转换等功能。

## 类层次结构

```bash
LineRoot (所有线对象的基类)
    LineSingle (单线对象)
        LineBuffer (环形缓冲区实现)
    LineMultiple (多线对象)
        LineSeries (多线时间序列)
            Indicator (技术指标基类)
            DataSeries (数据源基类)
            Strategy (策略基类)

```

## 核心概念

### Line（线）

Line 是 Backtrader 中存储时间序列数据的基本单元。它使用环形缓冲区实现，具有以下特性：

- **索引 0 始终指向当前值**：最新的数据值总是在索引 0 位置
- **正索引访问历史数据**：`data[-1]` 获取前一个值，`data[-2]` 获取再前一个值
- **负索引访问未来数据**：`data[1]` 在重放或实时场景中可访问下一个值
- **自动内存管理**：通过 qbuffer 模式控制内存使用

### 时间索引模式

```bash
历史数据              当前            未来数据
    |                 |               |

    v                 v               v
  ...  [-3]  [-2]  [-1]   [0]   [1]   [2]  ...
                  前一根 K 线   当前 K 线

```

## LineSeries 类

### 类定义

```python
class backtrader.LineSeries(LineMultiple, LineSeriesMixin, ParamsMixin):
    """管理多条线的时间序列对象基类。"""

```

### 核心属性

| 属性 | 类型 | 描述 |

|------|------|------|

| `lines` | Lines | 线条容器对象，存储所有 LineBuffer |

| `plotinfo` | PlotInfoObj | 绘图配置对象 |

| `plotlines` | PlotLinesObj | 线条绘图配置 |

| `csv` | bool | 是否支持 CSV 导出 |

### 线条操作属性

| 属性 | 返回值 | 描述 |

|------|--------|------|

| `array` | array | 第一条线的底层数组 |

| `line` | LineBuffer | 第一条线（单线指标快捷访问） |

| `l` | Lines | lines 的别名 |

## 时间序列操作

### 数据访问

```python
class MyStrategy(bt.Strategy):
    def next(self):

# 当前值（索引 0）
        current_close = self.data.close[0]
        current_sma = self.sma[0]

# 历史值（负索引）
        prev_close = self.data.close[-1]    # 前一根 K 线
        prev_close_2 = self.data.close[-2]  # 前两根 K 线
        prev_close_5 = self.data.close[-5]  # 前五根 K 线

# 未来值（正索引，仅在重放/实时场景有效）

# next_close = self.data.close[1]

```

### 数据长度

```python
def next(self):

# 获取数据长度（已加载的 K 线数量）
    current_bar = len(self.data)
    total_bars = len(self)

# 检查是否有足够的历史数据
    if len(self.data) >= 20:

# 可以计算 20 周期指标
        pass

```

### 时间操作

```python
def next(self):

# 获取当前 K 线时间（多种方式）
    dt_num = self.data.datetime[0]              # 内部数字格式
    dt = self.data.datetime.datetime(0)         # datetime 对象
    dt_date = self.data.datetime.date(0)        # date 对象
    dt_time = self.data.datetime.time(0)        # time 对象

# 前一根 K 线时间
    prev_dt = self.data.datetime.datetime(-1)

```

## 数据访问模式表

| 表达式 | 含义 | 使用场景 |

|--------|------|----------|

| `data[0]` | 当前 K 线值 | 获取最新数据 |

| `data[-1]` | 前一根 K 线值 | 获取上一个历史值 |

| `data[-n]` | 前 n 根 K 线值 | 获取 n 个周期前的值 |

| `data[1]` | 下一根 K 线值 | 重放/实时场景中的未来值 |

| `len(data)` | 数据长度 | 获取已加载 K 线数 |

| `data.array` | 底层数组 | 直接访问完整数据 |

## 切片和索引

### get() 方法

获取指定位置和大小的一片数据：

```python
def next(self):

# 获取最近 3 根 K 线的收盘价

# 返回: [close[-2], close[-1], close[0]]
    recent_3 = self.data.close.get(ago=0, size=3)

# 获取从当前往前的 5 根 K 线
    last_5 = self.data.close.get(ago=-4, size=5)

# 使用方式
    avg_price = sum(recent_3) / len(recent_3)

```

### 切片操作

```python
def next(self):

# 获取数组切片（基于内部数组索引）

# 注意：这是直接操作底层数组，需要理解内部结构
    array_data = self.data.close.array

# 常用模式：获取最近 N 个值
    recent_values = array_data[-self.p.period:]

```

## 对齐和同步

### 多数据源同步

当使用多个数据源时，Backtrader 会自动对齐它们：

```python
cerebro = bt.Cerebro()

# 添加多个数据源

cerebro.adddata(daily_data, name='daily')
cerebro.adddata(weekly_data, name='weekly')

class MyStrategy(bt.Strategy):
    def next(self):

# 数据源自动按日期对齐

# 当周线有新 K 线时，两个数据源的 next() 都会被调用
        daily_len = len(self.data0)  # 日线数据长度
        weekly_len = len(self.data1)  # 周线数据长度

# 访问不同数据源
        if self.data0.close[0] > self.data1.close[0]:
            self.buy(data=self.data0)

```

### 数据源访问方式

```python
class MyStrategy(bt.Strategy):
    def __init__(self):

# 方式 1：通过索引访问
        self.data0 = self.datas[0]
        self.data1 = self.datas[1]

# 方式 2：通过名称访问（需要先设置 name）
        self.daily = self.getdatabyname('daily')
        self.weekly = self.getdatabyname('weekly')

```

## 周期和时间框架处理

### TimeFrame 常量

```python

# TimeFrame 定义

TimeFrame.Ticks        # 1 - Tick 数据

TimeFrame.MicroSeconds # 2 - 微秒

TimeFrame.Seconds      # 3 - 秒

TimeFrame.Minutes      # 4 - 分钟

TimeFrame.Days         # 5 - 天

TimeFrame.Weeks        # 6 - 周

TimeFrame.Months       # 7 - 月

TimeFrame.Years        # 8 - 年

TimeFrame.NoTimeFrame  # 9 - 无时间周期

```

### 获取数据源时间框架

```python
class MyStrategy(bt.Strategy):
    def next(self):

# 获取时间框架类型
        tf = self.data._timeframe
        comp = self.data._compression

# 判断数据类型
        if tf == bt.TimeFrame.Days:
            if comp == 1:
                print("日线数据")
            elif comp == 7:
                print("周线数据（7 天压缩）")

```

### TimeFrame 方法

```python

# 获取时间框架名称

name = bt.TimeFrame.getname(bt.TimeFrame.Days)

# 返回: 'Day'

name = bt.TimeFrame.getname(bt.TimeFrame.Minutes, 5)

# 返回: 'Minutes'

# 从常量获取名称

name = bt.TimeFrame.TName(bt.TimeFrame.Days)

# 返回: 'Days'

# 从名称获取常量

tf = bt.TimeFrame.TFrame('Days')

# 返回: TimeFrame.Days (5)

```

## 与 pandas 的关系

### 转换为 pandas Series

```python
import backtrader as bt
import pandas as pd

class MyStrategy(bt.Strategy):
    def stop(self):

# 获取完整数据数组
        close_array = self.data.close.array

# 创建 pandas Series

# 注意：需要手动构建日期索引
        dates = []
        for i in range(len(self.data)):
            dt = self.data.datetime.date(i)
            dates.append(dt)

        df = pd.DataFrame({
            'close': close_array[:len(dates)],
        }, index=dates)
        df.index.name = 'date'

```

### 从 pandas 创建数据源

```python
import pandas as pd
import backtrader as bt

# 创建 DataFrame

df = pd.DataFrame({
    'datetime': pd.date_range('2020-01-01', periods=100),
    'open': np.random.randn(100).cumsum() + 100,
    'high': np.random.randn(100).cumsum() + 102,
    'low': np.random.randn(100).cumsum() + 98,
    'close': np.random.randn(100).cumsum() + 100,
    'volume': np.random.randint(1000, 10000, 100),
})

# 设置索引

df.set_index('datetime', inplace=True)

# 创建数据源

data = bt.feeds.PandasData(dataname=df)

```

### PandasData 参数映射

```python
class CustomPandasData(bt.feeds.PandasData):

# 自定义列名映射
    lines = ('close', 'volume', 'custom_line')

# 参数映射
    params = (
        ('datetime', None),      # None = 使用索引
        ('open', 'open_price'),
        ('high', 'high_price'),
        ('low', 'low_price'),
        ('close', 'close_price'),
        ('volume', 'vol'),
        ('openinterest', None),  # None = 列不存在
    )

```

## 常见使用模式

### 模式 1：访问历史数据计算指标

```python
class CustomIndicator(bt.Indicator):
    lines = ('value',)
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)

    def next(self):

# 计算最近 N 个周期的平均值
        total = 0.0
        for i in range(self.p.period):
            total += self.data.close[-i]

        self.lines.value[0] = total / self.p.period

```

### 模式 2：比较当前和之前值

```python
def next(self):

# 检查收盘价是否连续上涨
    if (self.data.close[0] > self.data.close[-1] and
        self.data.close[-1] > self.data.close[-2] and
        self.data.close[-2] > self.data.close[-3]):

# 连续 3 根 K 线上涨
        self.buy()

```

### 模式 3：条件访问避免越界

```python
def next(self):

# 确保有足够的历史数据
    if len(self.data) < self.p.period:
        return

# 安全访问历史数据
    prev_close = self.data.close[-self.p.period]

# 或者使用 minperiod
    if len(self.data) > self.p.period:

# 此处数据足够
        pass

```

### 模式 4：获取完整历史数据

```python
def next(self):

# 方式 1：使用 array 属性
    all_closes = self.data.close.array

# 方式 2：循环获取
    closes = []
    for i in range(len(self.data)):
        closes.append(self.data.close[i - len(self.data) + 1])

# 方式 3：使用 getzero
    all_data = self.data.close.getzero(0, len(self.data))

```

### 模式 5：多线指标访问

```python
class BollingerBands(bt.Indicator):
    lines = ('mid', 'top', 'bot')
    params = (('period', 20), ('devfactor', 2.0))

    def next(self):

# 访问不同输出线
        mid = self.lines.mid[0]
        top = self.lines.top[0]
        bot = self.lines.bot[0]

# 或通过名称访问
        mid = self.mid[0]
        top = self.top[0]
        bot = self.bot[0]

```

## LineSeries 方法

### 长度操作

#### `len(self)`

返回 LineSeries 的长度（已处理的数据点数量）。

```python
current_length = len(self.indicator)

```

#### `size(self)`

返回线条数量（不包括额外线条）。

```python
num_lines = self.indicator.size()

```

### 索引操作

#### `__getitem__(self, key)`

获取主线条的值。

```python
value = self.indicator[0]      # 当前值

value = self.indicator[-1]     # 前一个值

```

#### `__call__(self, ago=None, line=-1)`

返回延迟的线或指定索引/名称的值。

```python

# 返回当前线

current = self.indicator()

# 返回延迟 3 个周期的线

delayed = self.indicator(ago=3)

# 返回指定线的当前值

value = self.indicator(line='close')

```

### 缓冲区操作

#### `qbuffer(self, savemem=0)`

启用队列缓冲模式以节省内存。

```python

# 仅保留最近的数据

self.data.qbuffer(savemem=1000)

# 对于指标

self.sma.qbuffer()

```

#### `minbuffer(self, size)`

设置最小缓冲区大小。

```python

# 确保至少有 100 个数据点

self.indicator.minbuffer(100)

```

### 导航操作

#### `home(self)`

将所有线条重置到起始位置。

```python
self.indicator.home()

```

#### `rewind(self, size=1)`

回退指定数量的位置。

```python
self.indicator.rewind(5)  # 回退 5 个位置

```

#### `advance(self, size=1)`

前进指定数量的位置。

```python
self.indicator.advance(1)  # 前进 1 个位置

```

#### `forward(self, value=0.0, size=1)`

前进所有线条并填充值。

```python
self.indicator.forward(size=1)

```

#### `backwards(self, size=1, force=False)`

向后移动所有线条。

```python
self.indicator.backwards(size=1)

```

#### `reset(self)`

重置所有线条到初始状态。

```python
self.indicator.reset()

```

#### `extend(self, value=0.0, size=0)`

扩展所有线条。

```python
self.indicator.extend(size=10)

```

### 线条操作

#### `_getline(self, line, minusall=False)`

通过名称或索引获取线条。

```python

# 通过索引

line = self.indicator._getline(0)

# 通过名称

line = self.indicator._getline('close')

# 使用 minusall 参数

line = self.indicator._getline(-1, minusall=True)  # 最后一条线

```

## 性能优化

### 使用 array 属性

对于需要访问全部数据的场景，直接使用 array 属性：

```python
def next(self):

# 快速访问全部数据
    data_array = self.data.close.array

# 使用 NumPy 操作（如果已导入）
    import numpy as np
    mean = np.mean(data_array[-20:])

```

### 启用缓存模式

对于长时间运行的回测：

```python

# 在 Cerebro 中设置

cerebro = bt.Cerebro()

# 对数据源启用缓存

data = bt.feeds.PandasData(dataname=df)
cerebro.adddata(data)
data.qbuffer(savemem=1000)  # 仅保留最近 1000 根 K 线

```

### 使用 runonce 模式

```python

# 批处理模式，更快

cerebro.run(runonce=True)

```

## 完整示例

### 示例 1：自定义多线指标

```python
import backtrader as bt

class MultiOutputIndicator(bt.Indicator):
    """
    自定义指标：价格通道
    返回三条线：上轨、中轨、下轨
    """
    lines = ('upper', 'middle', 'lower')
    params = (('period', 20),)

    plotinfo = dict(
        subplot=False,  # 在主图上绘制
    )

    def __init__(self):
        super().__init__()
        self.addminperiod(self.p.period)

    def next(self):

# 计算中轨（SMA）
        total = 0.0
        high_max = self.data.high[-self.p.period]
        low_min = self.data.low[-self.p.period]

        for i in range(self.p.period):
            price = (self.data.high[-i] + self.data.low[-i] + self.data.close[-i]) / 3
            total += price
            if self.data.high[-i] > high_max:
                high_max = self.data.high[-i]
            if self.data.low[-i] < low_min:
                low_min = self.data.low[-i]

        self.lines.middle[0] = total / self.p.period
        self.lines.upper[0] = high_max
        self.lines.lower[0] = low_min


class MyStrategy(bt.Strategy):
    def __init__(self):

# 创建自定义指标
        self.channel = MultiOutputIndicator(self.data, period=20)

# 内置指标
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):

# 访问自定义指标的多条线
        if self.data.close[0] > self.channel.upper[0]:

# 价格突破上轨
            self.buy()
        elif self.data.close[0] < self.channel.lower[0]:

# 价格跌破下轨
            self.sell()

```

### 示例 2：历史数据分析

```python
class AnalysisStrategy(bt.Strategy):
    def __init__(self):
        self.sma20 = bt.indicators.SMA(self.data.close, period=20)
        self.sma50 = bt.indicators.SMA(self.data.close, period=50)

    def next(self):

# 获取最近 N 个值的列表
        recent_20 = self.data.close.get(ago=0, size=20)

# 计算自定义统计
        avg = sum(recent_20) / len(recent_20)

# 检查趋势
        if self.sma20[0] > self.sma20[-1] > self.sma20[-2]:

# 均线上升
            pass

# 时间相关分析
        current_dt = self.data.datetime.datetime(0)
        if current_dt.hour >= 9 and current_dt.hour < 15:

# 交易时段
            pass

```

### 示例 3：多时间框架分析

```python
class MultiTimeFrameStrategy(bt.Strategy):
    def __init__(self):

# 获取不同时间框架的数据
        self.daily = self.data0  # 日线
        self.weekly = self.data1  # 周线

# 为每个时间框架创建指标
        self.daily_sma = bt.indicators.SMA(self.daily.close, period=20)
        self.weekly_sma = bt.indicators.SMA(self.weekly.close, period=20)

    def next(self):

# 检查多时间框架对齐
        if len(self.weekly) > len(self.weekly_sma):

# 周线指标有效
            if self.daily.close[0] > self.daily_sma[0]:
                if self.weekly.close[0] > self.weekly_sma[0]:

# 双时间框架趋势一致
                    self.buy(data=self.daily)

```

## 常见陷阱

1. **索引越界**：在访问历史数据前检查 `len(data)`
2. **最小周期**：使用 `addminperiod()` 确保指标有足够数据
3. **未来数据泄露**：避免在回测中使用 `data[1]` 等未来数据
4. **数据对齐**：多数据源时注意数据可能不对齐
5. **时间处理**：datetime 是内部数字格式，需要转换

## 相关文档

- [Data Feeds API](data-feeds_zh.md) - 数据源配置
- [Indicator API](indicator_zh.md) - 指标开发
- [Strategy API](strategy_zh.md) - 策略开发
- [Cerebro API](cerebro_zh.md) - 回测引擎
