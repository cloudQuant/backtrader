### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/BackTest-Cpp
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### BackTest-Cpp项目简介
BackTest-Cpp是一个C++实现的高性能回测框架，具有以下核心特点：
- **C++实现**: 高性能C++实现
- **CRTP设计**: 使用奇异递归模板模式实现编译期多态
- **批量处理**: 支持批量数据读取和处理
- **列式存储**: SoA (Structure of Arrays) 内存布局
- **Header-only**: 纯头文件设计，易于集成
- **零开销抽象**: 无虚函数调用开销

### 重点借鉴方向
1. **批量处理**: 批量数据读取和处理模式
2. **内存布局**: SoA 列式存储布局
3. **CRTP设计**: 编译期多态替代虚函数
4. **增量计算**: 技术指标的增量计算优化
5. **预分配策略**: 内存预分配和对象复用
6. **noexcept优化**: 关键路径异常声明优化

---

## 一、项目对比分析

### 1.1 BackTest-Cpp 核心特性

| 特性 | 描述 |
|------|------|
| **CRTP 模式** | 奇异递归模板模式实现编译期多态 |
| **批量处理** | 默认1024条数据批量读取 |
| **SoA 布局** | OHLCBatch 列式存储结构 |
| **增量计算** | SMA/EMA/RSI 使用增量算法 |
| **Header-only** | 纯头文件设计 |
| **noexcept** | 关键函数异常声明 |
| **内存预分配** | reserve() 预分配内存 |

### 1.2 backtrader 现有能力对比

| 能力 | backtrader | BackTest-Cpp | 差距 |
|------|-----------|-------------|------|
| **执行模式** | 逐条处理 (next()) | 批量处理 | Cpp 更高效 |
| **内存布局** | AoS (Array of Structures) | SoA (Structure of Arrays) | Cpp 缓存友好 |
| **多态** | 虚函数 | CRTP 编译期多态 | Cpp 零开销 |
| **指标计算** | 逐条计算 | 增量计算 | Cpp 算法优化 |
| **内存管理** | 动态分配 | 预分配复用 | Cpp 更高效 |

### 1.3 差距分析

| 方面 | BackTest-Cpp | backtrader | 可借鉴点 |
|------|-------------|-----------|---------|
| **批量处理** | 批量读取 CSV | 逐条处理 | backtrader 可添加批量模式 |
| **内存布局** | 列式存储 | 行式存储 | backtrader 可优化数据结构 |
| **指标计算** | 增量算法 | 完整计算 | backtrader 可优化指标 |
| **异常保证** | noexcept 关键路径 | 无特殊声明 | backtrader 可添加优化 |

---

## 二、需求规格文档

### 2.1 功能需求

#### FR1: 批量数据处理
支持批量数据读取和处理以提升性能：

- **FR1.1**: BatchDataFeed - 批量数据源
- **FR1.2**: `next_batch()` - 批量获取数据
- **FR1.3**: 可配置批次大小
- **FR1.4**: 批量模式策略执行

#### FR2: 内存布局优化
优化数据存储结构以提高缓存命中率：

- **FR2.1**: SoA 数据结构设计
- **FR2.2**: 列式存储实现
- **FR2.3**: 向量化友好布局
- **FR2.4**: 内存预分配策略

#### FR3: 增量指标计算
优化技术指标计算性能：

- **FR3.1**: 增量 SMA 计算
- **FR3.2**: 增量 EMA 计算
- **FR3.3**: 增量 RSI 计算
- **FR3.4**: 通用增量计算框架

#### FR4: 性能优化
C++ 性能优化技术移植：

- **FR4.1**: noexcept 声明
- **FR4.2**: 内存预分配
- **FR4.3**: 对象复用
- **FR4.4**: 缓存友好设计

### 2.2 非功能需求

- **NFR1**: 性能 - 提升回测速度 20%+
- **NFR2**: 兼容性 - 与现有 API 兼容
- **NFR3**: 可选性 - 批量模式为可选
- **NFR4**: 内存 - 内存使用不增加

### 2.3 用户故事

| ID | 故事描述 | 优先级 |
|----|---------|--------|
| US1 | 作为量化研究员，我希望使用批量处理加速回测，节省时间 | P0 |
| US2 | 作为系统开发者，我希望优化内存布局减少缓存未命中 | P1 |
| US3 | 作为策略开发者，我希望指标计算更快，提高回测效率 | P1 |
| US4 | 作为性能专家，我希望使用 noexcept 优化关键路径 | P2 |

---

## 三、设计文档

### 3.1 模块结构设计

```
backtrader/
├── core/
│   ├── batch.py              # 批量处理模块
│   │   ├── batchfeed.py      # 批量数据源
│   │   └── batchstrategy.py  # 批量策略基类
├── utils/
│   ├── soa.py                # SoA 数据结构
│   └── memory.py             # 内存管理工具
└── indicators/
    └── incremental.py        # 增量指标计算
```

### 3.2 核心类设计

#### 3.2.1 批量数据源

```python
"""
Batch Data Feed for backtrader
参考：BackTest-Cpp/FileIterator.h
"""
import numpy as np
import pandas as pd
from backtrader import FeedBase
from backtrader.utils.py3 import iteritems


class SOAData:
    """
    Structure of Arrays 数据结构

    参考 BackTest-Cpp OHLCBatch 设计，使用列式存储提高缓存局部性
    """

    def __init__(self, size=0, dtype=np.float64):
        """
        Args:
            size: 预分配大小
            dtype: 数据类型
        """
        self.size = 0
        self.capacity = size

        # 列式存储 - 每列是一个 numpy 数组
        if size > 0:
            self.date = np.empty(size, dtype='datetime64[ns]')
            self.open = np.empty(size, dtype=dtype)
            self.high = np.empty(size, dtype=dtype)
            self.low = np.empty(size, dtype=dtype)
            self.close = np.empty(size, dtype=dtype)
            self.volume = np.empty(size, dtype=dtype)
            self.openinterest = np.empty(size, dtype=dtype)
        else:
            self.date = None
            self.open = None
            self.high = None
            self.low = None
            self.close = None
            self.volume = None
            self.openinterest = None

    def ensure_capacity(self, min_capacity):
        """确保足够的容量"""
        if self.capacity >= min_capacity:
            return

        new_capacity = max(min_capacity, self.capacity * 2)
        self._resize(new_capacity)

    def _resize(self, new_capacity):
        """调整数组大小"""
        if self.size == 0:
            self.date = np.empty(new_capacity, dtype='datetime64[ns]')
            self.open = np.empty(new_capacity, dtype=np.float64)
            self.high = np.empty(new_capacity, dtype=np.float64)
            self.low = np.empty(new_capacity, dtype=np.float64)
            self.close = np.empty(new_capacity, dtype=np.float64)
            self.volume = np.empty(new_capacity, dtype=np.float64)
            self.openinterest = np.empty(new_capacity, dtype=np.float64)
        else:
            self.date = np.resize(self.date, new_capacity)
            self.open = np.resize(self.open, new_capacity)
            self.high = np.resize(self.high, new_capacity)
            self.low = np.resize(self.low, new_capacity)
            self.close = np.resize(self.close, new_capacity)
            self.volume = np.resize(self.volume, new_capacity)
            self.openinterest = np.resize(self.openinterest, new_capacity)

        self.capacity = new_capacity

    def append(self, date, open_, high, low, close, volume, openinterest=0):
        """追加单条数据"""
        if self.size >= self.capacity:
            self.ensure_capacity(self.size + 1)

        self.date[self.size] = date
        self.open[self.size] = open_
        self.high[self.size] = high
        self.low[self.size] = low
        self.close[self.size] = close
        self.volume[self.size] = volume
        self.openinterest[self.size] = openinterest
        self.size += 1

    def clear(self):
        """清空数据（保留内存）"""
        self.size = 0

    def to_dataframe(self):
        """转换为 pandas DataFrame"""
        if self.size == 0:
            return pd.DataFrame()

        return pd.DataFrame({
            'open': self.open[:self.size],
            'high': self.high[:self.size],
            'low': self.low[:self.size],
            'close': self.close[:self.size],
            'volume': self.volume[:self.size],
            'openinterest': self.openinterest[:self.size],
        }, index=self.date[:self.size])

    def __len__(self):
        return self.size

    def __getitem__(self, key):
        """支持切片访问"""
        if isinstance(key, slice):
            # 返回新的 SOAData
            result = SOAData()
            slices = slice(0, self.size)[key]
            result.size = min(self.size, slices.stop or self.size) - (slices.start or 0)
            result.capacity = result.size
            result.date = self.date[key]
            result.open = self.open[key]
            result.high = self.high[key]
            result.low = self.low[key]
            result.close = self.close[key]
            result.volume = self.volume[key]
            result.openinterest = self.openinterest[key]
            return result
        return SOADataSlice(self, key)


class SOADataSlice:
    """SOAData 的切片视图（零拷贝）"""

    def __init__(self, soa_data, index):
        self._soa = soa_data
        self._idx = index

    @property
    def date(self):
        return self._soa.date[self._idx]

    @property
    def open(self):
        return self._soa.open[self._idx]

    @property
    def high(self):
        return self._soa.high[self._idx]

    @property
    def low(self):
        return self._soa.low[self._idx]

    @property
    def close(self):
        return self._soa.close[self._idx]

    @property
    def volume(self):
        return self._soa.volume[self._idx]


class BatchDataFeed:
    """
    批量数据源

    参考 BackTest-Cpp FileIterator，支持批量读取和处理
    """

    def __init__(self, data_feed, batch_size=1024):
        """
        Args:
            data_feed: backtrader 数据源
            batch_size: 批次大小
        """
        self._data_feed = data_feed
        self._batch_size = batch_size
        self._current_batch = SOAData(size=batch_size)
        self._batch_index = 0
        self._total_index = 0

        # 预加载所有数据到内存（如果数据量不大）
        self._load_all_data()

    def _load_all_data(self):
        """将所有数据加载到 SoA 结构"""
        # 重置数据源
        self._data_feed.reset()

        # 收集所有数据
        dates = []
        opens = []
        highs = []
        lows = []
        closes = []
        volumes = []
        openinterests = []

        for i in range(len(self._data_feed)):
            dates.append(self._data_feed.datetime.date(0))
            opens.append(self._data_feed.open[0])
            highs.append(self._data_feed.high[0])
            lows.append(self._data_feed.low[0])
            closes.append(self._data_feed.close[0])
            volumes.append(self._data_feed.volume[0])
            openinterests.append(self._data_feed.openinterest[0])
            self._data_feed.advance()

        # 存储到 numpy 数组
        self._all_data = {
            'date': np.array(dates),
            'open': np.array(opens, dtype=np.float64),
            'high': np.array(highs, dtype=np.float64),
            'low': np.array(lows, dtype=np.float64),
            'close': np.array(closes, dtype=np.float64),
            'volume': np.array(volumes, dtype=np.float64),
            'openinterest': np.array(openinterests, dtype=np.float64),
        }
        self._total_bars = len(dates)

    def next_batch(self):
        """
        获取下一批数据

        Returns:
            bool: 是否还有数据
        """
        if self._batch_index >= self._total_bars:
            return False

        # 计算当前批次的结束位置
        end_index = min(self._batch_index + self._batch_size, self._total_bars)
        batch_length = end_index - self._batch_index

        # 更新当前批次
        self._current_batch.size = batch_length
        self._current_batch.date = self._all_data['date'][self._batch_index:end_index]
        self._current_batch.open = self._all_data['open'][self._batch_index:end_index]
        self._current_batch.high = self._all_data['high'][self._batch_index:end_index]
        self._current_batch.low = self._all_data['low'][self._batch_index:end_index]
        self._current_batch.close = self._all_data['close'][self._batch_index:end_index]
        self._current_batch.volume = self._all_data['volume'][self._batch_index:end_index]
        self._current_batch.openinterest = self._all_data['openinterest'][self._batch_index:end_index]

        self._batch_index = end_index
        return True

    @property
    def current_batch(self):
        """获取当前批次"""
        return self._current_batch

    def reset(self):
        """重置数据源"""
        self._batch_index = 0
```

#### 3.2.2 增量指标计算

```python
"""
Incremental Indicators
参考：BackTest-Cpp/Indicators.h
"""
import numpy as np
from backtrader import Indicator


class IncrementalSMA(Indicator):
    """
    增量计算简单移动平均

    参考 BackTest-Cpp 的 SMA 实现，使用增量算法避免重复求和
    时间复杂度：O(n) 而非 O(n×period)
    """

    lines = ('sma',)
    params = (('period', 20),)

    def __init__(self):
        # 初始窗口期使用标准方法
        self._sum = 0.0
        self._window = []

    def next(self):
        price = self.data[0]

        if len(self) <= self.p.period:
            self._window.append(price)
            self._sum += price

            if len(self) == self.p.period:
                self.lines.sma[0] = self._sum / self.p.period
        else:
            # 增量更新：新值进入，旧值移出
            old_value = self._window.pop(0)
            self._window.append(price)
            self._sum += price - old_value
            self.lines.sma[0] = self._sum / self.p.period


class IncrementalEMA(Indicator):
    """
    增量计算指数移动平均

    参考 BackTest-Cpp 的 EMA 实现，使用递归公式
    EMA = α × (current - prev) + prev
    其中 α = 2 / (period + 1)
    """

    lines = ('ema',)
    params = (('period', 20),)

    def __init__(self):
        self._alpha = 2.0 / (self.p.period + 1)
        self._prev = None
        self._initialized = False

    def next(self):
        price = self.data[0]

        if not self._initialized:
            # 前期使用 SMA 初始化
            if len(self) == self.p.period:
                # 计算初始 SMA
                self._prev = sum(self.data.get(size=self.p.period)) / self.p.period
                self.lines.ema[0] = self._prev
                self._initialized = True
        else:
            # 增量更新：EMA = α × (current - prev) + prev
            self._prev = self._alpha * (price - self._prev) + self._prev
            self.lines.ema[0] = self._prev


class IncrementalRSI(Indicator):
    """
    增量计算相对强弱指标

    参考 BackTest-Cpp 的 RSI 实现，使用增量平均收益/损失
    """

    lines = ('rsi',)
    params = (('period', 14),)

    def __init__(self):
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._initialized = False
        self._prev_price = None

    def next(self):
        price = self.data[0]

        if self._prev_price is None:
            self._prev_price = price
            return

        delta = price - self._prev_price
        self._prev_price = price

        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0

        if not self._initialized:
            # 初始化阶段
            if len(self) > self.p.period:
                # 使用前期平均值初始化
                self._avg_gain = gain / self.p.period
                self._avg_loss = loss / self.p.period
                self._initialized = True
                self._calc_rsi()
        else:
            # 增量更新平均收益和损失
            self._avg_gain = (self._avg_gain * (self.p.period - 1) + gain) / self.p.period
            self._avg_loss = (self._avg_loss * (self.p.period - 1) + loss) / self.p.period
            self._calc_rsi()

    def _calc_rsi(self):
        """计算 RSI 值"""
        if self._avg_loss == 0:
            self.lines.rsi[0] = 100.0
        else:
            rs = self._avg_gain / self._avg_loss
            self.lines.rsi[0] = 100.0 - 100.0 / (1.0 + rs)


class VectorizedSMA(Indicator):
    """
    向量化 SMA - 使用 numpy 批量计算

    适用于批量处理模式，一次性计算整个批次的 SMA
    """

    lines = ('sma',)
    params = (('period', 20),)

    def __init__(self):
        # 检查数据源是否是批量数据
        if hasattr(self.data, 'batch_mode') and self.data.batch_mode:
            self._batch_mode = True
        else:
            self._batch_mode = False
            self._window = []

    def next(self):
        if self._batch_mode:
            # 批量模式下，一次性计算整个批次
            self._calc_batch()
        else:
            # 单条模式
            self._calc_single()

    def _calc_single(self):
        """单条计算"""
        price = self.data[0]
        self._window.append(price)

        if len(self._window) > self.p.period:
            self._window.pop(0)

        if len(self._window) >= self.p.period:
            self.lines.sma[0] = sum(self._window) / len(self._window)

    def _calc_batch(self):
        """批量计算 - 利用 numpy 向量化"""
        if not hasattr(self.data, 'close'):
            return

        close = self.data.close
        if len(close) < self.p.period:
            return

        # 使用 numpy 的卷积计算移动平均
        kernel = np.ones(self.p.period) / self.p.period
        sma = np.convolve(close, kernel, mode='valid')

        # 更新当前值
        if len(sma) > 0:
            self.lines.sma[0] = sma[-1]
```

#### 3.2.3 批量策略基类

```python
"""
Batch Strategy
参考：BackTest-Cpp/Strategy.h
"""
from backtrader import Strategy


class BatchStrategy(Strategy):
    """
    批量策略基类

    参考 BackTest-Cpp 的 Engine.run() 设计，支持批量处理
    策略可以实现 on_batch 方法来处理整批数据
    """

    params = (
        ('batch_size', 1024),
    )

    def __init__(self):
        self._batch_data = []
        self._batch_index = 0

    def next(self):
        """
        累积数据到批次大小，然后调用 on_batch
        """
        # 收集当前 bar 数据
        self._collect_bar()

        # 检查是否达到批次大小
        if len(self._batch_data) >= self.p.batch_size:
            self._process_batch()
            self._batch_data.clear()

    def _collect_bar(self):
        """收集当前 bar 数据"""
        bar = {
            'datetime': self.data.datetime.datetime(0),
            'open': self.data.open[0],
            'high': self.data.high[0],
            'low': self.data.low[0],
            'close': self.data.close[0],
            'volume': self.data.volume[0],
        }
        self._batch_data.append(bar)

    def _process_batch(self):
        """
        处理当前批次

        将批量数据转换为 numpy 数组，然后调用 on_batch
        """
        if not self._batch_data:
            return

        # 转换为 numpy 数组
        batch = {
            'datetime': [bar['datetime'] for bar in self._batch_data],
            'open': np.array([bar['open'] for bar in self._batch_data], dtype=np.float64),
            'high': np.array([bar['high'] for bar in self._batch_data], dtype=np.float64),
            'low': np.array([bar['low'] for bar in self._batch_data], dtype=np.float64),
            'close': np.array([bar['close'] for bar in self._batch_data], dtype=np.float64),
            'volume': np.array([bar['volume'] for bar in self._batch_data], dtype=np.float64),
        }

        # 调用子类实现的 on_batch
        self.on_batch(batch)

    def on_batch(self, batch):
        """
        子类实现此方法来处理批量数据

        Args:
            batch: 包含 'datetime', 'open', 'high', 'low', 'close', 'volume' 的字典
                    每个值（除 datetime 外）都是 numpy 数组
        """
        pass

    def stop(self):
        """处理剩余数据"""
        if self._batch_data:
            self._process_batch()


# 使用示例
class MAStrategy(BatchStrategy):
    """
    移动平均策略 - 使用批量处理
    """

    params = (
        ('fast_period', 20),
        ('slow_period', 50),
        ('batch_size', 256),
    )

    def __init__(self):
        super().__init__()

    def on_batch(self, batch):
        """
        批量处理数据
        """
        # 获取收盘价数组
        close = batch['close']

        if len(close) < self.p.slow_period:
            return

        # 使用 numpy 批量计算 SMA
        fast_sma = self._calc_sma_numpy(close, self.p.fast_period)
        slow_sma = self._calc_sma_numpy(close, self.p.slow_period)

        # 检查金叉/死叉
        if len(fast_sma) >= 2:
            # 最近的交叉
            if fast_sma[-1] > slow_sma[-1] and fast_sma[-2] <= slow_sma[-2]:
                # 金叉 - 买入
                if not self.position:
                    self.buy(size=100)
            elif fast_sma[-1] < slow_sma[-1] and fast_sma[-2] >= slow_sma[-2]:
                # 死叉 - 卖出
                if self.position:
                    self.sell(size=self.position.size)

    def _calc_sma_numpy(self, data, period):
        """使用 numpy 计算 SMA"""
        kernel = np.ones(period) / period
        return np.convolve(data, kernel, mode='valid')
```

#### 3.2.4 内存优化工具

```python
"""
Memory Optimization Tools
参考：BackTest-Cpp 内存管理策略
"""
import numpy as np


class MemoryPool:
    """
    内存池 - 对象复用

    参考 BackTest-Cpp 的 batch_.clear() 模式，复用内存而非频繁分配
    """

    def __init__(self, dtype=np.float64, initial_capacity=1024):
        """
        Args:
            dtype: 数据类型
            initial_capacity: 初始容量
        """
        self.dtype = dtype
        self._capacity = initial_capacity
        self._size = 0
        self._data = np.empty(initial_capacity, dtype=dtype)

    def allocate(self, size):
        """分配指定大小的内存"""
        if size > self._capacity:
            # 扩容（两倍增长策略）
            new_capacity = max(size, self._capacity * 2)
            self._data = np.resize(self._data, new_capacity)
            self._capacity = new_capacity

        result = self._data[self._size:self._size + size]
        self._size += size
        return result

    def reset(self):
        """重置内存池（保留内存）"""
        self._size = 0

    @property
    def data(self):
        """获取当前有效数据"""
        return self._data[:self._size]


class ArrayCache:
    """
    数组缓存 - 用于缓存计算结果

    避免重复计算相同的数据切片
    """

    def __init__(self, max_size=100):
        """
        Args:
            max_size: 最大缓存条目数
        """
        self._cache = {}
        self._max_size = max_size
        self._access_order = []

    def get(self, key):
        """获取缓存值"""
        if key in self._cache:
            # 更新访问顺序
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
        return None

    def put(self, key, value):
        """存入缓存"""
        if key in self._cache:
            self._access_order.remove(key)
        elif len(self._cache) >= self._max_size:
            # 移除最久未使用的条目
            oldest = self._access_order.pop(0)
            del self._cache[oldest]

        self._cache[key] = value
        self._access_order.append(key)

    def clear(self):
        """清空缓存"""
        self._cache.clear()
        self._access_order.clear()


def preallocate_arrays(size, columns=None):
    """
    预分配数组

    Args:
        size: 数组大小
        columns: 列名列表

    Returns:
        dict: 列名到数组的映射
    """
    if columns is None:
        columns = ['open', 'high', 'low', 'close', 'volume']

    return {col: np.empty(size, dtype=np.float64) for col in columns}
```

---

## 四、API 设计

### 4.1 批量数据 API

```python
from backtrader.feeds import BatchDataFeed
from backtrader import Cerebro

# 创建批量数据源
batch_feed = BatchDataFeed(data_feed, batch_size=1024)

# 批量处理
while batch_feed.next_batch():
    batch = batch_feed.current_batch
    # batch.open, batch.high 等都是 numpy 数组
    sma = np.convolve(batch.close, np.ones(20)/20, mode='valid')
```

### 4.2 增量指标 API

```python
from backtrader.indicators import IncrementalSMA, IncrementalEMA, IncrementalRSI

class MyStrategy(bt.Strategy):
    def __init__(self):
        # 使用增量指标
        self.sma = IncrementalSMA(self.data.close, period=20)
        self.ema = IncrementalEMA(self.data.close, period=20)
        self.rsi = IncrementalRSI(self.data.close, period=14)
```

### 4.3 批量策略 API

```python
from backtrader import BatchStrategy

class MyStrategy(BatchStrategy):
    params = (
        ('batch_size', 512),
    )

    def on_batch(self, batch):
        # batch 数据都是 numpy 数组
        close = batch['close']

        # 批量计算指标
        sma_fast = self._calc_sma(close, 20)
        sma_slow = self._calc_sma(close, 50)

        # 批量处理信号
        signals = np.where(sma_fast > sma_slow, 1, -1)
```

---

## 五、实施计划

### 5.1 实施阶段

| 阶段 | 内容 | 时间 |
|------|------|------|
| Phase 1 | SOAData 数据结构实现 | 0.5天 |
| Phase 2 | BatchDataFeed 批量数据源 | 1天 |
| Phase 3 | 增量指标实现 | 1天 |
| Phase 4 | BatchStrategy 批量策略 | 1天 |
| Phase 5 | 内存优化工具 | 0.5天 |
| Phase 6 | 测试和性能对比 | 1天 |

### 5.2 优先级

1. **P0**: SOAData - 列式存储数据结构
2. **P0**: IncrementalSMA/EMA/RSI - 增量指标计算
3. **P1**: BatchDataFeed - 批量数据源
4. **P1**: BatchStrategy - 批量策略基类
5. **P2**: MemoryPool - 内存池
6. **P2**: ArrayCache - 数组缓存

---

## 六、参考资料

### 6.1 关键参考代码

- BackTest-Cpp/include/backtest/Engine.h - CRTP 引擎设计
- BackTest-Cpp/include/backtest/FileIterator.h - 批量文件读取
- BackTest-Cpp/include/backtest/Indicators.h - 增量指标计算
- BackTest-Cpp/include/backtest/Data.h - 数据结构定义
- BackTest-Cpp/Examples/SupportResistance/SupportResistance.h - 策略示例

### 6.2 BackTest-Cpp 核心设计

```cpp
// CRTP 模式实现编译期多态
template <typename Derived, typename Feed>
class Engine {
    void run() {
        static_cast<Derived*>(this)->onStart();
        while (feed_.nextBatch()) {
            const Batch& batch = feed_.currentBatch();
            for (std::size_t i = 0; i < batch.size(); ++i) {
                static_cast<Derived*>(this)->onBar(batch, i);
            }
        }
        static_cast<Derived*>(this)->onEnd();
    }
};

// SoA 数据结构
struct OHLCBatch {
    std::vector<std::string> date;
    std::vector<double> open;
    std::vector<double> high;
    std::vector<double> low;
    std::vector<double> close;
    std::vector<double> volume;
};

// 增量 SMA 计算
inline std::vector<double> SMA(const std::vector<double>& data, std::size_t period) {
    double sum = std::accumulate(data.begin(), data.begin() + period, 0.0);
    for (std::size_t i = period; i < data.size(); ++i) {
        sum += data[i] - data[i - period];  // 增量更新
        sma[i] = sum / period;
    }
}
```

### 6.3 性能优化技术总结

| 技术 | 描述 | backtrader 应用 |
|------|------|---------------|
| **批量处理** | 减少函数调用开销 | 批量数据源 |
| **SoA 布局** | 提高缓存局部性 | 列式数据结构 |
| **增量计算** | 减少重复计算 | 增量指标 |
| **内存预分配** | 减少分配次数 | 内存池 |
| **向量化** | 利用 SIMD | numpy 批量计算 |
| **noexcept** | 减少异常开销 | 关键路径声明 |

### 6.4 backtrader 可复用组件

- `backtrader/linebuffer.py` - 现有数据结构
- `backtrader/indicator.py` - 指标基类
- `backtrader/strategy.py` - 策略基类
- `backtrader/feeds/*` - 数据源接口
