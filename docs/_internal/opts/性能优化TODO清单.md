# 性能优化 TODO 清单

基于完整日志分析，按需求 10.md 要求制定的详细优化流程。

## 📊 完整性能对比数据

### 关键数据对比

| 指标 | Master 版本 | Remove 版本 | 增量 | 增长率 |

|------|-----------|-----------|------|--------|

| **总执行时间**| 33.42 秒 | 58.96 秒 | +25.54 秒 |**+76.4%**|

|**总函数调用**| 114,083,132 | 195,811,488 | +81,728,356 |**+71.6%**|

|**hasattr 调用**| 352,382 | 21,672,655 | +21,320,273 |**+6050%**⚠️⚠️⚠️ |

|**getattr 调用**| 3,054,733 | 8,647,232 | +5,592,499 |**+183%**|

|**setattr 调用**| 1,363,602 | 3,813,989 | +2,450,387 |**+180%**|

|**isinstance 调用**| 0 | 20,174,868 | +20,174,868 |**NEW** |

### TOP 10 性能下降最严重的函数

| 排名 | 函数 | Master 耗时 | Remove 耗时 | 增加耗时 | 增长率 |

|------|------|-----------|-----------|---------|--------|

| 1 | `lineseries.__getitem__:969` | 0s | 4.027s | +4.027s | NEW |

| 2 | `lineseries.__getattr__:784` | 0s | 4.342s | +4.342s | NEW |

| 3 | `lineseries.__setattr__:876` | 0s | 3.289s | +3.289s | NEW |

| 4 | `hasattr (内建)` | 0.030s | 2.255s | +2.225s | +7417% |

| 5 | `linebuffer.forward:441` | 0s | 2.488s | +2.488s | NEW |

| 6 | `feed._tick_fill:432` | 1.038s | 4.216s | +3.178s | +306% |

| 7 | `lineseries.safe_clk_update` | 0s | 0.624s | +0.624s | NEW |

| 8 | `parameters.get_param` | 0s | 0.420s | +0.420s | NEW |

| 9 | `lineseries.forward:1061` | 0s | 4.219s | +4.219s | NEW |

| 10 | `lineseries.__len__:957` | 0s | 0.755s | +0.755s | NEW |

- --

## 🎯 优化 TODO 清单（按执行顺序）

### 阶段 1：紧急优化 - 优化属性访问（预计恢复 40-50%性能）

- *目标**：将执行时间从 58.96 秒降至 45-48 秒

#### ✅ TODO 1.1: 优化 lineseries.__getattr__（已在之前尝试中发现问题）

- *状态**: 需要重新设计
- *文件**: `backtrader/lineseries.py`
- *问题分析**:
- 当前调用：3,255,140 次，耗时 4.342 秒
- 每次都触发 hasattr 检查
- 需要缓存机制

- *优化方案**:

```python
def __getattr__(self, name):

# 方案 A: 属性缓存到__dict__（首选）
    try:

# 查找逻辑...
        result = find_attribute(name)

# 缓存：下次直接从__dict__获取，不再触发__getattr__
        object.__setattr__(self, name, result)
        return result
    except AttributeError:
        raise

# 方案 B: 类级缓存（备选）
    _attr_cache = {}  # 类变量
    cache_key = (type(self).__name__, name)
    if cache_key in _attr_cache:
        return _attr_cache[cache_key](self)

```bash

- *验证标准**:
- `__getattr__`调用次数减少 80%以上
- `hasattr`调用减少 1000 万+
- 执行时间减少 3-5 秒

- --

#### ✅ TODO 1.2: 优化 lineseries.__setattr__

- *状态**: 待执行
- *文件**: `backtrader/lineseries.py`
- *当前问题**:
- 调用 8,137,580 次，耗时 3.289 秒
- 内部使用大量 hasattr 检查

- *优化方案**:

```python
def __setattr__(self, name, value):

# 1. 快速路径：内部属性
    if name[0] == '_':
        object.__setattr__(self, name, value)
        return

# 2. 已知属性集合（一次性检查）
    if name in _KNOWN_ATTRS:  # 预定义集合
        object.__setattr__(self, name, value)
        return

# 3. 简单类型：直接设置
    if type(value) in _SIMPLE_TYPES:  # 预定义类型集合
        object.__setattr__(self, name, value)
        return

# 4. 复杂对象：EAFP 模式
    try:
        _ = value._minperiod  # 直接访问，不用 hasattr

# ... 处理逻辑
    except AttributeError:

# ... fallback

```bash

- *验证标准**:
- `__setattr__`耗时减少 50%以上
- `hasattr`调用减少 500 万+

- --

#### ✅ TODO 1.3: 优化 lineseries.__getitem__

- *状态**: 待执行
- *文件**: `backtrader/lineseries.py:969`
- *当前问题**:
- 调用 5,770,820 次，耗时 4.027 秒
- 每次都做 isinstance 和 isnan 检查

- *优化方案**:

```python
def __getitem__(self, key):
    try:
        value = self.lines[0][key]

# 方案 1: 移除 isinstance 检查，用 duck typing
        if value is None:
            return 0.0

# 方案 2: NaN 检查用 value != value（比 math.isnan 快）
        if value != value:  # NaN 的特性
            return 0.0
        return value
    except (IndexError, TypeError, AttributeError):
        return 0.0

```bash

- *验证标准**:
- `isinstance`调用减少 2000 万+
- 执行时间减少 2-3 秒

- --

#### ✅ TODO 1.4: 继续优化 lineiterator 中的 hasattr

- *状态**: 部分完成，需继续
- *文件**: `backtrader/lineiterator.py`
- *已优化**: donew, dopreinit, dopostinit 函数（减少 21 个 hasattr）
- *还需优化**: 其他函数中的 hasattr 调用

- *剩余工作**:
- [ ] 检查__new__方法
- [ ] 检查_stage1, _stage2 方法
- [ ] 检查所有循环中的 hasattr

- *验证标准**:
- `hasattr`调用再减少 200 万+

- --

### 阶段 2：重要优化 - 参数系统和缓存（预计恢复 20-30%性能）

- *目标**：将执行时间从 45-48 秒降至 38-42 秒

#### ✅ TODO 2.1: 优化 Parameters 类

- *状态**: 待执行
- *文件**: `backtrader/parameters.py`
- *当前问题**:
- `get_param`: 1,325,673 次调用，0.420 秒
- `get`: 1,668,170 次调用，0.305 秒
- `__getattr__`: 1,046,628 次调用，0.886 秒

- *优化方案**:

```python
class Parameters:
    def __init__(self, ...):

# 预创建所有参数作为实例属性
        for name, value in self._params.items():
            object.__setattr__(self, name, value)

# 这样访问 p.param_name 直接从__dict__获取，不触发__getattr__

# 简化 get_param：直接返回属性
    def get_param(self, name, default=None):
        return getattr(self, name, default)  # 简单包装

```bash

- *验证标准**:
- 参数相关函数调用减少 200 万+
- 执行时间减少 2-3 秒

- --

#### ✅ TODO 2.2: 实现智能属性缓存

- *状态**: 待执行
- *策略**: LRU 缓存或实例缓存

- *方案 A: 实例级缓存（简单高效）**:

```python
class LineSeries:
    def __getattr__(self, name):

# 查找成功后立即缓存
        result = self._find_attribute(name)
        self.__dict__[name] = result  # 缓存
        return result

# 下次访问直接从__dict__获取，不触发__getattr__

```bash

- *方案 B: LRU 缓存（适合类级别）**:

```python
from functools import lru_cache

class LineSeries:
    @lru_cache(maxsize=256)
    def _get_cached_attr(self, name):

# 缓存查找逻辑
        ...

```bash

- *验证标准**:
- 缓存命中率>70%
- `__getattr__`调用再减少 60%

- --

### 阶段 3：深度优化 - 架构改进（预计恢复 10-15%性能）

- *目标**：将执行时间从 38-42 秒降至 35-38 秒，接近 master 版本（33.42 秒）

#### ✅ TODO 3.1: 重新引入有限的描述符（不使用元类）

- *状态**: 待设计
- *目标**: 用描述符处理 line 访问，避免运行时查找

```python
class LineDescriptor:
    """轻量级描述符，不依赖元类"""
    def __init__(self, index):
        self.index = index

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.lines[self.index]

    def __set__(self, instance, value):
        instance.lines[self.index] = value

class LineSeries:

# 在类定义时（不是元类）手动创建描述符
    close = LineDescriptor(0)
    high = LineDescriptor(1)
    low = LineDescriptor(2)

# ...

```bash

- --

#### ✅ TODO 3.2: 使用__slots__优化小对象

- *状态**: 待执行
- *目标**: 减少内存，略微提升速度

```python
class Line:
    __slots__ = ['array', '_idx', '_minperiod']

class Parameters:
    __slots__ = ['_param_dict', '_defaults']

```bash

- --

### 阶段 4：验证和测试

#### ✅ TODO 4.1: 每轮优化后的验证流程

- *必须执行**:
1. 运行性能测试: `python profile_performance.py`
2. 对比日志: 检查 hasattr, getattr 等关键指标
3. 功能测试: 运行测试套件确保正确性
4. 提交代码: `git commit -m "optimize: [描述]"`

#### ✅ TODO 4.2: 性能目标验证

- *阶段 1 完成后**:
- 执行时间: ≤48 秒
- hasattr 调用: ≤1000 万
- 总函数调用: ≤170M

- *阶段 2 完成后**:
- 执行时间: ≤42 秒
- hasattr 调用: ≤500 万
- 总函数调用: ≤150M

- *阶段 3 完成后**:
- 执行时间: ≤38 秒
- hasattr 调用: ≤200 万
- 接近 master 版本性能

- --

## 📝 执行记录

### 已完成

- ✅ lineiterator.py 优化（hasattr 减少 21.2%）
- ✅ 详细性能分析和 TODO 清单

### 进行中

- ⏳ TODO 1.1: 设计 lineseries.__getattr__缓存方案

### 待执行

- ⬜ TODO 1.2-1.4
- ⬜ TODO 2.1-2.2
- ⬜ TODO 3.1-3.2
- ⬜ TODO 4.1-4.2

- --

## 🎯 优先级总结

- *立即执行** (本周内):
1. TODO 1.1: __getattr__缓存（最关键）
2. TODO 1.3: __getitem__优化（影响大）
3. TODO 1.2: __setattr__优化

- *重要执行** (下周):
1. TODO 2.1: Parameters 优化
2. TODO 2.2: 属性缓存机制

- *后续执行** (评估后):
1. TODO 3.1: 描述符重构
2. TODO 3.2: __slots__优化

- *每个 TODO 完成后都要**:

✅ 运行性能测试
✅ 验证功能正确性
✅ 对比性能日志
✅ 提交代码并记录

- --

## 📊 预期收益汇总

| 优化项 | 预计减少函数调用 | 预计节省时间 | 累计时间目标 |

|--------|----------------|-------------|-------------|

| **阶段 1 完成**| 15-20M | 10-13 秒 |**45-48 秒**|

|**阶段 2 完成**| 3-5M | 5-7 秒 |**38-42 秒**|

|**阶段 3 完成**| 2-3M | 3-5 秒 |**35-38 秒**|

|**最终目标**| | |**≈33 秒** (master 水平) |
