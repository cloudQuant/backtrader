### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/flow
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### flow项目简介
flow是一个数据流处理框架，可用于量化交易数据处理，具有以下核心特点：
- **数据流**: 数据流处理架构
- **管道设计**: 管道式数据处理
- **实时处理**: 支持实时数据处理
- **可组合**: 组件可组合设计
- **异步支持**: 异步数据处理
- **流式计算**: 流式计算支持

### 重点借鉴方向
1. **数据流**: 数据流架构设计
2. **管道模式**: 管道处理模式
3. **实时处理**: 实时数据处理
4. **组件化**: 可组合组件设计
5. **异步处理**: 异步数据处理
6. **流式计算**: 流式计算技术

---

## 项目对比分析

### Backtrader vs Flow 架构对比

| 维度 | Backtrader | Flow |
|------|------------|------|
| **核心定位** | 回测和实盘框架 | 数据流处理+强化学习交易 |
| **架构风格** | 事件驱动+OOP | 数据流+智能体 |
| **数据粒度** | Bar级（K线） | 多时间粒度（1/50/1000秒） |
| **数据处理** | Line系统 | Quote Stream+Buffer |
| **时间管理** | 单一时间框架 | 多Scope并行 |
| **决策模式** | 策略模式 | 强化学习（Q-Learning） |
| **组件管理** | 手动注册 | 自动生命周期管理 |
| **并行处理** | 单线程优化 | 多Scope并行 |
| **学习机制** | 无 | Q-Learning在线学习 |
| **状态管理** | LineIterator状态机 | Agent状态向量 |
| **数据源** | 多种Feed支持 | CSV为主 |
| **技术指标** | 60+内置指标 | 自定义流式计算 |

### Flow可借鉴的核心优势

#### 1. 多时间粒度架构
- **Scope概念**: 每个Scope代表一个时间粒度的处理管道
- **并行处理**: 多个Scope（1/50/1000秒）同时处理同一数据流
- **独立决策**: 不同时间粒度的智能体独立决策
- **触发机制**: 基于时间间隔触发管道处理

#### 2. 数据流管道
- **Quote Stream**: 持续的报价数据流
- **Quote Buffer**: 全局报价缓冲区
- **Scope Sampling**: 按时间粒度采样数据
- **流式计算**: 技术指标基于滑动窗口计算

#### 3. 智能体生命周期
- **自动创建**: 当空闲槽位时自动创建新智能体
- **自动淘汰**: 性能差的智能体自动被移除
- **自我进化**: 通过Q-Learning不断优化决策
- **资源管理**: 固定数量的智能体槽位管理

#### 4. 强化学习集成
- **Q-Learning**: 在线学习最优交易策略
- **状态向量**: 多维状态空间（均线交叉、MACD、RSI等）
- **动作空间**: 买入/卖出/持有
- **奖励函数**: 基于盈亏的即时奖励

#### 5. 流式计算技术
- **滑动窗口**: 基于滑动窗口计算技术指标
- **实时更新**: 每个新报价更新状态向量
- **状态编码**: 将市场状态编码为固定维度的向量

#### 6. 组件化设计
- **Executive**: 主控制器，负责调度
- **Bankroll**: 资金流管理
- **Scope**: 时间粒度容器
- **Agent**: 智能体
- **Order**: 订单执行
- **Indicators**: 技术指标
- **Learning**: 学习算法

---

## 需求文档

### 需求概述

借鉴flow项目的数据流处理和强化学习设计理念，为backtrader添加以下功能模块，提升数据处理能力和策略学习能力：

### 功能需求

#### FR1: 数据流架构

**FR1.1 数据流管道**
- 需求描述: 建立数据流处理管道架构
- 优先级: 高
- 验收标准:
  - 实现DataFlow数据流基类
  - 支持管道式数据传递
  - 支持管道分支和合并
  - 支持管道插件

**FR1.2 Quote Stream**
- 需求描述: 支持报价数据流
- 优先级: 高
- 验收标准:
  - 实现QuoteStream数据流
  - 支持实时报价推送
  - 支持历史报价回放
  - 支持多数据源

**FR1.3 数据缓冲区**
- 需求描述: 实现数据缓冲机制
- 优先级: 中
- 验收标准:
  - 实现QuoteBuffer缓冲区
  - 支持固定窗口大小
  - 支持滑动窗口
  - 支持时间索引查询

#### FR2: 多时间粒度

**FR2.1 Scope时间粒度**
- 需求描述: 支持多时间粒度并行处理
- 优先级: 高
- 验收标准:
  - 实现Scope时间粒度类
  - 支持多个Scope并行运行
  - 支持Scope间数据共享
  - 支持Scope独立调度

**FR2.2 时间采样**
- 需求描述: 按时间粒度采样数据
- 优先级: 高
- 验收标准:
  - 实现时间采样器
  - 支持多种采样策略
  - 支持实时采样
  - 支持历史采样

**FR2.3 Scope触发器**
- 需求描述: 基于时间间隔触发Scope处理
- 优先级: 中
- 验收标准:
  - 实现ScopeTrigger触发器
  - 支持周期性触发
  - 支持条件触发
  - 支持一次性触发

#### FR3: 强化学习集成

**FR3.1 Q-Learning算法**
- 需求描述: 集成Q-Learning算法
- 优先级: 高
- 验收标准:
  - 实现QLearningAgent基类
  - 支持Q表更新
  - 支持探索-利用平衡
  - 支持经验回放

**FR3.2 状态空间**
- 需求描述: 定义交易状态空间
- 优先级: 高
- 验收标准:
  - 定义StateEncoder状态编码器
  - 支持多维状态向量
  - 支持状态归一化
  - 支持状态历史窗口

**FR3.3 动作空间**
- 需求描述: 定义交易动作空间
- 优先级: 中
- 验收标准:
  - 定义ActionSpace动作空间
  - 支持离散动作（买/卖/持有）
  - 支持连续动作（仓位比例）
  - 支持动作约束

**FR3.4 奖励函数**
- 需求描述: 定义奖励计算函数
- 优先级: 中
- 验收标准:
  - 实现RewardFunction奖励类
  - 支持多种奖励计算方式
  - 支持奖励归一化
  - 支持奖励延迟

#### FR4: 智能体管理

**FR4.1 智能体生命周期**
- 需求描述: 自动管理智能体生命周期
- 优先级: 中
- 验收标准:
  - 实现AgentManager管理器
  - 支持自动创建智能体
  - 支持自动淘汰智能体
  - 支持智能体复制和变异

**FR4.2 智能体评估**
- 需求描述: 评估智能体性能
- 优先级: 中
- 验收标准:
  - 实现性能评估指标
  - 支持夏普比率评估
  - 支持最大回撤评估
  - 支持综合评分

**FR4.3 智能体槽位**
- 需求描述: 管理智能体槽位资源
- 优先级: 低
- 验收标准:
  - 实现固定数量槽位
  - 支持槽位分配
  - 支持槽位释放
  - 支持槽位优先级

#### FR5: 流式计算

**FR5.1 滑动窗口**
- 需求描述: 实现滑动窗口计算
- 优先级: 高
- 验收标准:
  - 实现SlidingWindow类
  - 支持固定窗口大小
  - 支持动态窗口大小
  - 支持窗口步进

**FR5.2 流式指标**
- 需求描述: 实现流式技术指标
- 优先级: 高
- 验收标准:
  - 实现StreamingIndicator基类
  - 支持增量计算
  - 支持状态保持
  - 支持多输出

**FR5.3 状态编码器**
- 需求描述: 将市场数据编码为状态向量
- 优先级: 中
- 验收标准:
  - 实现StateEncoder类
  - 支持多种编码方式
  - 支持特征选择
  - 支持特征缩放

#### FR6: 异步处理

**FR6.1 异步数据流**
- 需求描述: 支持异步数据处理
- 优先级: 中
- 验收标准:
  - 实现AsyncDataFlow异步数据流
  - 支持async/await语法
  - 支持并发数据处理
  - 支持背压控制

**FR6.2 异步执行**
- 需求描述: 支持异步执行策略
- 优先级: 中
- 验收标准:
  - 实现AsyncStrategy异步策略
  - 支持异步数据获取
  - 支持异步订单执行
  - 支持超时控制

**FR6.3 事件循环**
- 需求描述: 集成事件循环
- 优先级: 低
- 验收标准:
  - 支持asyncio事件循环
  - 支持多事件循环协调
  - 支持循环生命周期管理

### 非功能需求

#### NFR1: 性能
- 数据流延迟 < 10ms
- 状态更新延迟 < 5ms
- 智能体决策延迟 < 50ms
- 吞吐量 > 10000 ticks/秒

#### NFR2: 可扩展性
- 支持水平扩展（多进程）
- 支持垂直扩展（多线程）
- 支持分布式部署

#### NFR3: 可靠性
- 系统稳定性 > 99.9%
- 数据完整性 100%
- 故障恢复时间 < 1s

---

## 设计文档

### 整体架构设计

#### 新增模块结构

```
backtrader/
├── backtrader/
│   ├── flow/               # 新增：数据流处理模块
│   │   ├── __init__.py
│   │   ├── core.py         # 数据流核心
│   │   ├── pipe.py         # 数据管道
│   │   ├── buffer.py       # 数据缓冲区
│   │   └── stream.py       # 数据流
│   ├── scope/             # 新增：时间粒度模块
│   │   ├── __init__.py
│   │   ├── scope.py        # 时间粒度
│   │   ├── sampler.py      # 采样器
│   │   ├── trigger.py      # 触发器
│   │   └── manager.py      # Scope管理器
│   ├── agents/            # 新增：强化学习智能体模块
│   │   ├── __init__.py
│   │   ├── base.py         # 智能体基类
│   │   ├── qlearning.py    # Q-Learning智能体
│   │   ├── manager.py      # 智能体管理器
│   │   └── evaluator.py    # 性能评估器
│   ├── rl/                # 新增：强化学习模块
│   │   ├── __init__.py
│   │   ├── qtable.py       # Q表实现
│   │   ├── policy.py       # 策略（ε-greedy等）
│   │   ├── memory.py       # 经验回放
│   │   └── trainer.py      # 训练器
│   ├── streaming/         # 新增：流式计算模块
│   │   ├── __init__.py
│   │   ├── window.py       # 滑动窗口
│   │   ├── indicator.py    # 流式指标
│   │   └── encoder.py      # 状态编码器
│   ├── async_engine/      # 新增：异步引擎模块
│   │   ├── __init__.py
│   │   ├── engine.py       # 异步引擎
│   │   ├── strategy.py     # 异步策略
│   │   └── loop.py         # 事件循环
│   └── pipeline/          # 新增：管道模块
│       ├── __init__.py
│       ├── pipeline.py     # 管道
│       ├── stage.py        # 管道阶段
│       └── graph.py        # 管道图
```

### 详细设计

#### 1. 数据流架构

**1.1 数据流核心**

```python
# backtrader/flow/core.py
from typing import AsyncIterator, Callable, Any, List
from abc import ABC, abstractmethod
import asyncio

class DataFlow(ABC):
    """数据流抽象基类"""

    @abstractmethod
    async def process(self, data: Any) -> Any:
        """处理数据"""
        pass

class Pipe(DataFlow):
    """数据管道"""

    def __init__(self, stages: List[DataFlow] = None):
        self.stages = stages or []
        self._source = None

    def add_stage(self, stage: DataFlow) -> 'Pipe':
        """添加管道阶段"""
        self.stages.append(stage)
        return self

    def set_source(self, source: 'DataSource'):
        """设置数据源"""
        self._source = source
        return self

    async def process(self, data: Any) -> Any:
        """管道处理"""
        result = data
        for stage in self.stages:
            result = await stage.process(result)
        return result

    async def run(self):
        """运行管道"""
        if not self._source:
            raise RuntimeError("No source set")

        async for data in self._source:
            result = await self.process(data)
            yield result

class DataSource(DataFlow):
    """数据源基类"""

    def __init__(self):
        self._subscribers: List[Callable] = []

    def subscribe(self, callback: Callable):
        """订阅数据"""
        self._subscribers.append(callback)

    async def emit(self, data: Any):
        """发送数据"""
        for callback in self._subscribers:
            if asyncio.iscoroutinefunction(callback):
                await callback(data)
            else:
                callback(data)
```

**1.2 数据流管道**

```python
# backtrader/flow/pipe.py
from typing import Callable, Any, List, Dict
from .core import DataFlow

class PipelineStage(DataFlow):
    """管道阶段基类"""

    def __init__(self, name: str = None):
        self.name = name or self.__class__.__name__
        self._next_stage = None

    def set_next(self, stage: 'PipelineStage'):
        """设置下一阶段"""
        self._next_stage = stage
        return self

    async def process(self, data: Any) -> Any:
        """处理数据并传递到下一阶段"""
        result = await self._process(data)
        if self._next_stage:
            result = await self._next_stage.process(result)
        return result

    async def _process(self, data: Any) -> Any:
        """子类实现具体处理逻辑"""
        return data

class FilterStage(PipelineStage):
    """过滤阶段"""

    def __init__(self, predicate: Callable[[Any], bool]):
        super().__init__()
        self.predicate = predicate

    async def _process(self, data: Any) -> Any:
        if self.predicate(data):
            return data
        return None  # 过滤掉

class TransformStage(PipelineStage):
    """转换阶段"""

    def __init__(self, transform: Callable[[Any], Any]):
        super().__init__()
        self.transform = transform

    async def _process(self, data: Any) -> Any:
        return self.transform(data)

class BufferStage(PipelineStage):
    """缓冲阶段"""

    def __init__(self, size: int = 100):
        super().__init__()
        self.size = size
        self._buffer: List[Any] = []

    async def _process(self, data: Any) -> Any:
        self._buffer.append(data)
        if len(self._buffer) > self.size:
            self._buffer.pop(0)
        return data

    def get_buffer(self) -> List[Any]:
        """获取缓冲区数据"""
        return self._buffer.copy()
```

**1.3 数据缓冲区**

```python
# backtrader/flow/buffer.py
from collections import deque
from typing import Any, List, Optional
from datetime import datetime, timedelta

class QuoteBuffer:
    """报价缓冲区"""

    def __init__(self, maxlen: int = 10000):
        self.buffer = deque(maxlen=maxlen)
        self._time_index: Dict[datetime, Any] = {}

    def append(self, quote: 'Quote'):
        """添加报价"""
        self.buffer.append(quote)
        self._time_index[quote.timestamp] = quote

    def get_latest(self, n: int = 1) -> List['Quote']:
        """获取最新n条报价"""
        if not self.buffer:
            return []
        return list(self.buffer)[-n:]

    def get_range(self, start: datetime, end: datetime) -> List['Quote']:
        """获取时间范围内的报价"""
        result = []
        for quote in self.buffer:
            if start <= quote.timestamp <= end:
                result.append(quote)
            elif quote.timestamp > end:
                break
        return result

    def get_by_time(self, timestamp: datetime) -> Optional['Quote']:
        """根据时间获取报价"""
        return self._time_index.get(timestamp)

    def clear(self):
        """清空缓冲区"""
        self.buffer.clear()
        self._time_index.clear()

    def __len__(self):
        return len(self.buffer)

class WindowBuffer:
    """滑动窗口缓冲区"""

    def __init__(self, size: int):
        self.size = size
        self._data: List[Any] = []

    def append(self, value: Any):
        """添加数据"""
        self._data.append(value)
        if len(self._data) > self.size:
            self._data.pop(0)

    def get_window(self) -> List[Any]:
        """获取窗口数据"""
        return self._data.copy()

    def is_full(self) -> bool:
        """窗口是否已满"""
        return len(self._data) >= self.size

    def __len__(self):
        return len(self._data)
```

**1.4 数据流**

```python
# backtrader/flow/stream.py
from typing import AsyncIterator, Callable, Any
import asyncio

class QuoteStream:
    """报价数据流"""

    def __init__(self, source: AsyncIterator = None):
        self._source = source
        self._running = False
        self._task = None

    async def __aiter__(self):
        """异步迭代器"""
        return self

    async def __anext__(self):
        """获取下一个数据"""
        if not self._running:
            raise StopAsyncIteration

        if self._source:
            return await self._source.__anext__()

        # 等待新数据
        data = await self._wait_for_data()
        return data

    async def _wait_for_data(self) -> Any:
        """等待新数据（子类实现）"""
        await asyncio.sleep(0.01)
        return None

    async def start(self):
        """启动数据流"""
        self._running = True

    async def stop(self):
        """停止数据流"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

class ReplayStream(QuoteStream):
    """回放数据流"""

    def __init__(self, quotes: List[Any]):
        super().__init__()
        self._quotes = quotes
        self._index = 0

    async def _wait_for_data(self) -> Any:
        """回放下一条数据"""
        if self._index < len(self._quotes):
            data = self._quotes[self._index]
            self._index += 1
            return data
        raise StopAsyncIteration

class LiveStream(QuoteStream):
    """实时数据流"""

    def __init__(self, feed_callback: Callable):
        super().__init__()
        self._callback = feed_callback
        self._queue = asyncio.Queue()

    async def _wait_for_data(self) -> Any:
        """从队列获取数据"""
        return await self._queue.get()
```

#### 2. 多时间粒度

**2.1 时间粒度**

```python
# backtrader/scope/scope.py
from typing import List, Optional, Callable
from datetime import datetime

class Scope:
    """时间粒度Scope"""

    def __init__(self, scope: int, name: str = None):
        """
        Args:
            scope: 时间粒度（秒）
            name: 名称
        """
        self.scope = scope  # 时间粒度（秒）
        self.name = name or f"Scope_{scope}s"
        self.agents: List['Agent'] = []
        self._hop = 0  # 当前跳数

    def add_agent(self, agent: 'Agent'):
        """添加智能体"""
        self.agents.append(agent)

    def remove_agent(self, agent: 'Agent'):
        """移除智能体"""
        if agent in self.agents:
            self.agents.remove(agent)

    def is_active(self, hop: int) -> bool:
        """检查是否激活"""
        return hop % self.scope == 0

    def process(self, data: Any, hop: int):
        """处理数据"""
        if not self.is_active(hop):
            return

        for agent in self.agents:
            agent.process(data, hop)

    def get_quotes(self, global_buffer: 'QuoteBuffer',
                   current_time: datetime) -> List:
        """获取当前Scope的报价"""
        # 根据时间粒度采样数据
        return global_buffer.get_latest(
            int(self.scope / 10)  # 假设每10秒一个数据点
        )
```

**2.2 采样器**

```python
# backtrader/scope/sampler.py
from typing import List, Any
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

class Sampler(ABC):
    """采样器基类"""

    @abstractmethod
    def sample(self, data: List[Any], timestamp: datetime) -> Any:
        """采样数据"""
        pass

class TimeBasedSampler(Sampler):
    """基于时间的采样器"""

    def __init__(self, interval: timedelta):
        self.interval = interval
        self._last_sample: Optional[datetime] = None

    def sample(self, data: List[Any], timestamp: datetime) -> Any:
        """按时间间隔采样"""
        if self._last_sample is None:
            self._last_sample = timestamp
            return data[-1] if data else None

        if timestamp - self._last_sample >= self.interval:
            self._last_sample = timestamp
            return data[-1] if data else None

        return None  # 跳过

class TickSampler(Sampler):
    """Tick采样器"""

    def __init__(self, tick_count: int = 1):
        self.tick_count = tick_count
        self._counter = 0

    def sample(self, data: List[Any], timestamp: datetime) -> Any:
        """按Tick数采样"""
        self._counter += 1

        if self._counter >= self.tick_count:
            self._counter = 0
            return data[-1] if data else None

        return None

class OHLCSampler(Sampler):
    """OHLC采样器"""

    def __init__(self):
        self._current_open = None
        self._current_high = float('-inf')
        self._current_low = float('inf')
        self._current_close = None
        self._current_volume = 0

    def sample(self, data: List[Any], timestamp: datetime) -> Optional[dict]:
        """采样为OHLC"""
        if not data:
            return None

        quote = data[-1]

        if self._current_open is None:
            self._current_open = quote.price
            self._current_high = quote.price
            self._current_low = quote.price
        else:
            self._current_high = max(self._current_high, quote.price)
            self._current_low = min(self._current_low, quote.price)

        self._current_close = quote.price
        self._current_volume += quote.volume

        return {
            'open': self._current_open,
            'high': self._current_high,
            'low': self._current_low,
            'close': self._current_close,
            'volume': self._current_volume
        }

    def reset(self):
        """重置采样器"""
        self._current_open = None
        self._current_high = float('-inf')
        self._current_low = float('inf')
        self._current_close = None
        self._current_volume = 0
```

**2.3 触发器**

```python
# backtrader/scope/trigger.py
from abc import ABC, abstractmethod
from datetime import datetime

class ScopeTrigger(ABC):
    """Scope触发器"""

    @abstractmethod
    def should_trigger(self, scope: 'Scope', hop: int,
                       timestamp: datetime) -> bool:
        """判断是否应该触发"""
        pass

class IntervalTrigger(ScopeTrigger):
    """时间间隔触发器"""

    def __init__(self, interval: int):
        self.interval = interval

    def should_trigger(self, scope: 'Scope', hop: int,
                       timestamp: datetime) -> bool:
        return hop % self.interval == 0

class TimeTrigger(ScopeTrigger):
    """时间触发器"""

    def __init__(self, hour: int = None, minute: int = None, second: int = None):
        self.hour = hour
        self.minute = minute
        self.second = second

    def should_trigger(self, scope: 'Scope', hop: int,
                       timestamp: datetime) -> bool:
        if self.hour is not None and timestamp.hour != self.hour:
            return False
        if self.minute is not None and timestamp.minute != self.minute:
            return False
        if self.second is not None and timestamp.second != self.second:
            return False
        return True

class ConditionTrigger(ScopeTrigger):
    """条件触发器"""

    def __init__(self, condition: Callable[['Scope', int, datetime], bool]):
        self.condition = condition

    def should_trigger(self, scope: 'Scope', hop: int,
                       timestamp: datetime) -> bool:
        return self.condition(scope, hop, timestamp)
```

**2.4 Scope管理器**

```python
# backtrader/scope/manager.py
from typing import List, Dict, Optional
from .scope import Scope
from .trigger import ScopeTrigger, IntervalTrigger

class ScopeManager:
    """Scope管理器"""

    def __init__(self):
        self._scopes: Dict[int, Scope] = {}
        self._triggers: List[ScopeTrigger] = []
        self._hop = 0

    def add_scope(self, scope: Scope):
        """添加Scope"""
        self._scopes[scope.scope] = scope

    def remove_scope(self, scope: int):
        """移除Scope"""
        if scope in self._scopes:
            del self._scopes[scope]

    def add_trigger(self, trigger: ScopeTrigger):
        """添加触发器"""
        self._triggers.append(trigger)

    def get_active_scopes(self) -> List[Scope]:
        """获取活跃的Scope"""
        active = []
        for scope in self._scopes.values():
            if self._should_activate(scope):
                active.append(scope)
        return active

    def _should_activate(self, scope: Scope) -> bool:
        """判断Scope是否应该激活"""
        # 检查内置触发器
        for trigger in self._triggers:
            if trigger.should_trigger(scope, self._hop, datetime.now()):
                return True

        # 检查默认触发器
        return scope.is_active(self._hop)

    def process(self, data: Any, timestamp: datetime = None):
        """处理数据"""
        self._hop += 1
        timestamp = timestamp or datetime.now()

        for scope in self.get_active_scopes():
            scope.process(data, self._hop)

    @property
    def hop(self) -> int:
        """当前跳数"""
        return self._hop
```

#### 3. 强化学习集成

**3.1 Q-Learning智能体**

```python
# backtrader/agents/qlearning.py
from typing import Dict, List, Tuple, Optional
import numpy as np
from .base import Agent
from ..rl.qtable import QTable
from ..rl.policy import EpsilonGreedyPolicy

class QLearningAgent(Agent):
    """Q-Learning智能体"""

    def __init__(self, state_space: int, action_space: int,
                 learning_rate: float = 0.1,
                 discount_factor: float = 0.99,
                 epsilon: float = 0.1):
        super().__init__()

        self.state_space = state_space
        self.action_space = action_space
        self.q_table = QTable(state_space, action_space)

        # 学习参数
        self.learning_rate = learning_rate  # α
        self.discount_factor = discount_factor  # γ
        self.epsilon = epsilon  # ε

        # 策略
        self.policy = EpsilonGreedyPolicy(epsilon)

        # 经验
        self._last_state = None
        self._last_action = None

    def select_action(self, state: int) -> int:
        """选择动作"""
        return self.policy.select(state, self.q_table)

    def update(self, state: int, action: int,
               reward: float, next_state: int, done: bool = False):
        """更新Q表"""
        # Q(s,a) ← Q(s,a) + α[r + γ max Q(s',a') - Q(s,a)]
        current_q = self.q_table.get(state, action)
        max_next_q = self.q_table.get_max(next_state) if not done else 0

        new_q = current_q + self.learning_rate * (
            reward + self.discount_factor * max_next_q - current_q
        )

        self.q_table.set(state, action, new_q)

        # 衰减探索率
        self.policy.decay()

    def get_state(self) -> int:
        """获取当前状态"""
        # 由子类实现具体的状态获取逻辑
        return 0

    def get_reward(self, action: int) -> float:
        """获取奖励"""
        # 由子类实现具体的奖励计算逻辑
        return 0.0

    def decay_epsilon(self, decay_rate: float = 0.995):
        """衰减探索率"""
        self.epsilon *= decay_rate
        self.policy.epsilon = self.epsilon
```

**3.2 智能体基类**

```python
# backtrader/agents/base.py
from abc import ABC, abstractmethod

class Agent(ABC):
    """智能体基类"""

    def __init__(self, name: str = None):
        self.name = name or self.__class__.__name__

    @abstractmethod
    def process(self, data: Any, hop: int):
        """处理数据"""
        pass

    @abstractmethod
    def get_action(self) -> int:
        """获取动作"""
        pass

    @abstractmethod
    def update(self, reward: float):
        """更新智能体"""
        pass
```

**3.3 Q表实现**

```python
# backtrader/rl/qtable.py
import numpy as np
from typing import Dict, Tuple

class QTable:
    """Q表实现"""

    def __init__(self, state_space: int, action_space: int):
        self.state_space = state_space
        self.action_space = action_space
        self._table = np.zeros((state_space, action_space))

    def get(self, state: int, action: int) -> float:
        """获取Q值"""
        return self._table[state, action]

    def set(self, state: int, action: int, value: float):
        """设置Q值"""
        self._table[state, action] = value

    def get_max(self, state: int) -> float:
        """获取状态的最大Q值"""
        return np.max(self._table[state])

    def get_best_action(self, state: int) -> int:
        """获取最优动作"""
        return np.argmax(self._table[state])

    def update(self, state: int, action: int, value: float):
        """更新Q值"""
        self._table[state, action] = value

    def reset(self):
        """重置Q表"""
        self._table.fill(0)

    def __getitem__(self, key: Tuple[int, int]) -> float:
        return self._table[key]

    def __setitem__(self, key: Tuple[int, int], value: float):
        self._table[key] = value
```

**3.4 策略**

```python
# backtrader/rl/policy.py
from typing import List
import numpy as np

class Policy:
    """策略基类"""

    def __init__(self):
        pass

    def select(self, state: int, q_table: 'QTable') -> int:
        """选择动作"""
        raise NotImplementedError

class EpsilonGreedyPolicy(Policy):
    """ε-贪婪策略"""

    def __init__(self, epsilon: float = 0.1):
        self.epsilon = epsilon

    def select(self, state: int, q_table: 'QTable') -> int:
        """ε-贪婪动作选择"""
        if np.random.random() < self.epsilon:
            # 探索：随机选择
            return np.random.randint(q_table.action_space)
        else:
            # 利用：选择最优
            return q_table.get_best_action(state)

    def decay(self, decay_rate: float = 0.995):
        """衰减探索率"""
        self.epsilon *= decay_rate

class GreedyPolicy(Policy):
    """贪婪策略"""

    def select(self, state: int, q_table: 'QTable') -> int:
        """贪婪动作选择"""
        return q_table.get_best_action(state)

class BoltzmannPolicy(Policy):
    """Boltzmann策略"""

    def __init__(self, temperature: float = 1.0):
        self.temperature = temperature

    def select(self, state: int, q_table: 'QTable') -> int:
        """Boltzmann动作选择"""
        q_values = q_table._table[state]
        exp_q = np.exp(q_values / self.temperature)
        probs = exp_q / np.sum(exp_q)
        return np.random.choice(len(probs), p=probs)
```

**3.5 经验回放**

```python
# backtrader/rl/memory.py
from typing import List, Tuple, NamedTuple
from collections import deque
import random

class Transition(NamedTuple):
    state: int
    action: int
    reward: float
    next_state: int
    done: bool

class ReplayBuffer:
    """经验回放缓冲区"""

    def __init__(self, capacity: int = 10000):
        self.buffer = deque(maxlen=capacity)
        self.capacity = capacity

    def push(self, state: int, action: int, reward: float,
             next_state: int, done: bool):
        """添加经验"""
        self.buffer.append(Transition(
            state, action, reward, next_state, done
        ))

    def sample(self, batch_size: int) -> List[Transition]:
        """采样经验"""
        return random.sample(self.buffer, min(batch_size, len(self.buffer)))

    def __len__(self):
        return len(self.buffer)

    def is_ready(self, batch_size: int) -> bool:
        """检查是否有足够经验"""
        return len(self.buffer) >= batch_size
```

#### 4. 流式计算

**4.1 滑动窗口**

```python
# backtrader/streaming/window.py
from typing import List, Any, Callable, Optional
from collections import deque

class SlidingWindow:
    """滑动窗口"""

    def __init__(self, size: int, dtype: type = float):
        self.size = size
        self.dtype = dtype
        self._window: deque = deque(maxlen=size)

    def append(self, value: Any):
        """添加数据"""
        self._window.append(self.dtype(value))

    def get_window(self) -> List:
        """获取窗口数据"""
        return list(self._window)

    def is_full(self) -> bool:
        """窗口是否已满"""
        return len(self._window) >= self.size

    def apply(self, func: Callable[[List], Any]) -> Any:
        """应用函数到窗口数据"""
        return func(self.get_window())

    def mean(self) -> float:
        """计算平均值"""
        return sum(self._window) / len(self._window)

    def std(self) -> float:
        """计算标准差"""
        mean = self.mean()
        return sum((x - mean) ** 2 for x in self._window) / len(self._window)

    def min(self) -> float:
        """获取最小值"""
        return min(self._window)

    def max(self) -> float:
        """获取最大值"""
        return max(self._window)

    def __len__(self):
        return len(self._window)

    def __getitem__(self, index: int) -> Any:
        """支持负索引"""
        return list(self._window)[index]
```

**4.2 流式指标**

```python
# backtrader/streaming/indicator.py
from typing import List, Any, Optional
from .window import SlidingWindow

class StreamingIndicator:
    """流式指标基类"""

    def __init__(self, period: int):
        self.period = period
        self._window = SlidingWindow(period)

    def update(self, value: float) -> Optional[float]:
        """更新指标并返回最新值"""
        self._window.append(value)

        if not self._window.is_full():
            return None

        return self.calculate()

    def calculate(self) -> float:
        """计算指标值（子类实现）"""
        raise NotImplementedError

    def is_ready(self) -> bool:
        """检查指标是否准备就绪"""
        return self._window.is_full()

class StreamingSMA(StreamingIndicator):
    """流式简单移动平均"""

    def calculate(self) -> float:
        return self._window.mean()

class StreamingEMA(StreamingIndicator):
    """流式指数移动平均"""

    def __init__(self, period: int, alpha: float = None):
        super().__init__(period)
        self.alpha = alpha or (2.0 / (period + 1))
        self._last_ema: Optional[float] = None

    def update(self, value: float) -> Optional[float]:
        if self._last_ema is None:
            self._last_ema = value
            return None

        self._last_ema = self.alpha * value + (1 - self.alpha) * self._last_ema
        return self._last_ema

class StreamingRSI(StreamingIndicator):
    """流式RSI"""

    def __init__(self, period: int = 14):
        super().__init__(period)
        self._gains = SlidingWindow(period)
        self._losses = SlidingWindow(period)

    def update(self, value: float) -> Optional[float]:
        if len(self._window) < 2:
            self._window.append(value)
            return None

        prev = self._window[-2]
        change = value - prev

        if change > 0:
            self._gains.append(change)
            self._losses.append(0)
        else:
            self._gains.append(0)
            self._losses.append(abs(change))

        if not self._gains.is_full():
            return None

        avg_gain = self._gains.mean()
        avg_loss = self._losses.mean()

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

class StreamingMACD(StreamingIndicator):
    """流式MACD"""

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self._ema_fast = StreamingEMA(fast)
        self._ema_slow = StreamingEMA(slow)
        self._signal_ema = StreamingEMA(signal)
        self._hist: List[float] = []

    def update(self, value: float) -> Optional[tuple]:
        fast = self._ema_fast.update(value)
        slow = self._ema_slow.update(value)

        if fast is None or slow is None:
            return None

        macd = fast - slow
        signal = self._signal_ema.update(macd)

        if signal is None:
            return (macd, None, None)

        hist = macd - signal
        return (macd, signal, hist)
```

**4.3 状态编码器**

```python
# backtrader/streaming/encoder.py
from typing import List, Dict, Any
import numpy as np

class StateEncoder:
    """状态编码器"""

    def __init__(self, features: List[str] = None):
        self.features = features or []
        self._scalers: Dict[str, any] = {}

    def encode(self, data: Dict[str, Any]) -> np.ndarray:
        """将数据编码为状态向量"""
        state = []

        for feature in self.features:
            value = data.get(feature)

            # 归一化处理
            if feature in self._scalers:
                value = self._scalers[feature].transform(value)

            state.append(value)

        return np.array(state)

    def add_scaler(self, feature: str, scaler):
        """添加特征缩放器"""
        self._scalers[feature] = scaler

    def fit(self, data_list: List[Dict[str, Any]]):
        """拟合缩放器"""
        for feature in self.features:
            values = [d.get(feature) for d in data_list]
            # 计算均值和标准差
            mean = np.mean(values)
            std = np.std(values)

            class StandardScaler:
                def __init__(self, mean, std):
                    self.mean = mean
                    self.std = std

                def transform(self, value):
                    return (value - self.mean) / self.std if self.std > 0 else 0

            self.add_scaler(feature, StandardScaler(mean, std))
```

#### 5. 智能体管理

**5.1 智能体管理器**

```python
# backtrader/agents/manager.py
from typing import List, Optional, Dict
from .base import Agent
from .evaluator import PerformanceEvaluator

class AgentManager:
    """智能体管理器"""

    def __init__(self, max_agents: int = 10):
        self.max_agents = max_agents
        self._agents: List[Agent] = []
        self._slots: List[Optional[Agent]] = [None] * max_agents
        self.evaluator = PerformanceEvaluator()

    def add_agent(self, agent: Agent) -> bool:
        """添加智能体"""
        # 查找空闲槽位
        for i, slot in enumerate(self._slots):
            if slot is None:
                self._slots[i] = agent
                self._agents.append(agent)
                return True
        return False

    def remove_agent(self, agent: Agent) -> bool:
        """移除智能体"""
        for i, slot in enumerate(self._slots):
            if slot == agent:
                self._slots[i] = None
                if agent in self._agents:
                    self._agents.remove(agent)
                return True
        return False

    def get_worst_agent(self) -> Optional[Agent]:
        """获取表现最差的智能体"""
        if not self._agents:
            return None

        scores = [(agent, self.evaluator.evaluate(agent))
                   for agent in self._agents]
        return min(scores, key=lambda x: x[1])[0]

    def get_best_agent(self) -> Optional[Agent]:
        """获取表现最好的智能体"""
        if not self._agents:
            return None

        scores = [(agent, self.evaluator.evaluate(agent))
                   for agent in self._agents]
        return max(scores, key=lambda x: x[1])[0]

    def evolve(self):
        """智能体进化"""
        # 移除表现最差的智能体
        worst = self.get_worst_agent()
        if worst:
            self.remove_agent(worst)

        # 如果有空槽位，创建新智能体
        best = self.get_best_agent()
        if best and self.has_free_slot():
            new_agent = self._create_agent(best)
            self.add_agent(new_agent)

    def has_free_slot(self) -> bool:
        """是否有空闲槽位"""
        return any(slot is None for slot in self._slots)

    def _create_agent(self, parent: Agent = None) -> Agent:
        """创建新智能体（可基于父智能体变异）"""
        # 实现具体的创建逻辑
        pass

    def get_agents(self) -> List[Agent]:
        """获取所有智能体"""
        return self._agents.copy()

    def __len__(self):
        return sum(1 for slot in self._slots if slot is not None)
```

**5.2 性能评估器**

```python
# backtrader/agents/evaluator.py
from typing import Dict, List

class PerformanceEvaluator:
    """性能评估器"""

    def __init__(self):
        self._metrics: Dict[str, float] = {}

    def evaluate(self, agent: Agent) -> float:
        """评估智能体性能"""
        metrics = self._calculate_metrics(agent)
        return self._get_score(metrics)

    def _calculate_metrics(self, agent: Agent) -> Dict[str, float]:
        """计算性能指标"""
        # 计算各种指标
        return {
            'total_return': getattr(agent, 'total_return', 0),
            'sharpe_ratio': getattr(agent, 'sharpe_ratio', 0),
            'max_drawdown': getattr(agent, 'max_drawdown', 0),
            'win_rate': getattr(agent, 'win_rate', 0),
        }

    def _get_score(self, metrics: Dict[str, float]) -> float:
        """计算综合得分"""
        # 加权计算得分
        weights = {
            'total_return': 0.3,
            'sharpe_ratio': 0.3,
            'max_drawdown': -0.2,
            'win_rate': 0.2,
        }

        score = 0
        for metric, weight in weights.items():
            score += metrics.get(metric, 0) * weight

        return score
```

#### 6. 异步引擎

**6.1 异步引擎**

```python
# backtrader/async_engine/engine.py
import asyncio
from typing import List, Optional
from ..strategy import Strategy
from ..cerebro import Cerebro

class AsyncCerebro(Cerebro):
    """异步回测引擎"""

    def __init__(self):
        super().__init__()
        self._loop = asyncio.get_event_loop()
        self._running = False

    async def run_async(self):
        """异步运行回测"""
        self._running = True

        # 初始化阶段
        await self._run_strategy_init()

        # 运行阶段
        await self._run_strategies()

        # 结束阶段
        await self._run_strategy_stop()

        self._running = False

    async def _run_strategy_init(self):
        """运行策略初始化"""
        for strat in self.strategies:
            if hasattr(strat, '_async_init'):
                await strat._async_init()

    async def _run_strategies(self):
        """运行策略"""
        while self._running and not self._should_stop():
            # 获取数据
            has_data = await self._fetch_data()

            if has_data:
                # 运行策略
                await self._run_next()

            await asyncio.sleep(0)

    async def _run_strategy_stop(self):
        """运行策略停止"""
        for strat in self.strategies:
            if hasattr(strat, '_async_stop'):
                await strat._async_stop()

    async def _fetch_data(self) -> bool:
        """获取数据（子类实现）"""
        return True

    async def _run_next(self):
        """运行next"""
        for strat in self.strategies:
            if hasattr(strat, '_async_next'):
                await strat._async_next()

    def _should_stop(self) -> bool:
        """判断是否应该停止"""
        return False
```

**6.2 异步策略**

```python
# backtrader/async_engine/strategy.py
from ..strategy import Strategy
import asyncio

class AsyncStrategy(Strategy):
    """异步策略基类"""

    async def _async_init(self):
        """异步初始化"""
        # 调用同步初始化
        self.__init__()

    async def _async_next(self):
        """异步next"""
        # 调用同步next
        self.next()

    async def _async_stop(self):
        """异步停止"""
        self.stop()

    async def buy_async(self, data=None, size=None, price=None):
        """异步买入"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.buy(data, size, price)
        )

    async def sell_async(self, data=None, size=None, price=None):
        """异步卖出"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.sell(data, size, price)
        )
```

### 实现计划

#### 第一阶段：数据流架构（优先级：高）
1. 实现DataFlow数据流基类
2. 实现Pipe管道类
3. 实现QuoteStream和ReplayStream
4. 实现QuoteBuffer缓冲区

#### 第二阶段：多时间粒度（优先级：高）
1. 实现Scope时间粒度类
2. 实现Sampler采样器
3. 实现ScopeTrigger触发器
4. 实现ScopeManager管理器

#### 第三阶段：流式计算（优先级：高）
1. 实现SlidingWindow滑动窗口
2. 实现StreamingIndicator流式指标
3. 实现StateEncoder状态编码器
4. 实现多种流式技术指标

#### 第四阶段：强化学习集成（优先级：高）
1. 实现QLearningAgent智能体
2. 实现QTable和Policy
3. 实现ReplayBuffer经验回放
4. 实现状态空间和动作空间

#### 第五阶段：智能体管理（优先级：中）
1. 实现AgentManager管理器
2. 实现PerformanceEvaluator评估器
3. 实现智能体生命周期管理
4. 实现智能体进化机制

#### 第六阶段：异步处理（优先级：中）
1. 实现AsyncCerebro异步引擎
2. 实现AsyncStrategy异步策略
3. 集成asyncio事件循环
4. 实现异步数据获取和订单执行

### API兼容性保证

所有新增功能保持与现有backtrader API的兼容性：

1. **向后兼容**: 现有代码无需修改即可运行
2. **可选启用**: 新功能通过选择使用
3. **渐进增强**: 用户可以选择使用新功能或保持原有方式

```python
# 示例：传统方式（保持不变）
import backtrader as bt

cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(MyStrategy)
result = cerebro.run()

# 示例：数据流方式（可选）
from backtrader.flow import DataFlow, Pipe, QuoteStream

pipe = Pipe()
pipe.add_stage(TransformStage(lambda x: x * 2))
pipe.add_stage(FilterStage(lambda x: x > 0))

stream = QuoteStream(source=csv_source)
stream.subscribe(pipe.process)

# 示例：多时间粒度（可选）
from backtrader.scope import Scope, ScopeManager

manager = ScopeManager()
manager.add_scope(Scope(1, "Tick"))
manager.add_scope(Scope(50, "Short"))
manager.add_scope(Scope(1000, "Long"))

# 示例：强化学习（可选）
from backtrader.agents import QLearningAgent

agent = QLearningAgent(
    state_space=100,
    action_space=3,
    learning_rate=0.1,
    epsilon=0.1
)
```

### 使用示例

**数据流使用示例：**

```python
from backtrader.flow import DataFlow, Pipe, QuoteStream
from backtrader.streaming import SlidingWindow, StreamingSMA

# 创建管道
pipe = Pipe()
sma20 = SlidingWindow(20)
sma50 = SlidingWindow(50)

@pipe.add_stage
class ComputeIndicators(DataFlow):
    async def process(self, quote):
        sma20.append(quote.price)
        sma50.append(quote.price)

        if sma20.is_full() and sma50.is_full():
            return {
                'sma20': sma20.mean(),
                'sma50': sma50.mean(),
                'price': quote.price
            }
        return None

# 连接数据流
stream = QuoteStream(source=api_stream)
stream.subscribe(pipe.process)

async for signal in stream.run():
    if signal['sma20'] > signal['sma50']:
        print("买入信号")
```

**多时间粒度使用示例：**

```python
from backtrader.scope import Scope, ScopeManager, IntervalTrigger

# 创建管理器
manager = ScopeManager()

# 添加不同时间粒度的Scope
manager.add_scope(Scope(1, "Tick"))      # 每秒
manager.add_scope(Scope(50, "Short"))   # 每50秒
manager.add_scope(Scope(1000, "Long"))   # 每1000秒

# 添加触发器
manager.add_trigger(IntervalTrigger(10))

# 在Scope中添加智能体
tick_scope = manager._scopes[1]
tick_scope.add_agent(HFTAgent())

# 处理数据流
for quote in quotes:
    manager.process(quote)
```

**强化学习使用示例：**

```python
from backtrader.agents import QLearningAgent, AgentManager
from backtrader.streaming import StateEncoder

# 创建智能体
encoder = StateEncoder(features=['sma20', 'sma50', 'rsi', 'macd'])

agent = QLearningAgent(
    state_space=encoder.get_state_dim(),
    action_space=3  # 买入/卖出/持有
)

# 创建管理器
manager = AgentManager(max_agents=10)
manager.add_agent(agent)

# 训练循环
for episode in range(1000):
    state = encoder.encode(current_data)
    action = agent.select_action(state)
    reward = execute_action(action)
    next_state = encoder.encode(next_data)
    agent.update(state, action, reward, next_state)

    # 定期进化智能体
    if episode % 100 == 0:
        manager.evolve()
```

**异步处理使用示例：**

```python
from backtrader.async_engine import AsyncCerebro, AsyncStrategy

class MyAsyncStrategy(AsyncStrategy):
    async def _async_next(self):
        # 异步获取数据
        data = await self.fetch_data_async()

        # 异步决策
        if self.should_buy(data):
            await self.buy_async(data)

async_strat = MyAsyncStrategy()
cerebro = AsyncCerebro()
cerebro.addstrategy(async_strat)

await cerebro.run_async()
```

### 测试策略

1. **单元测试**: 每个新增模块的单元测试覆盖率 > 80%
2. **集成测试**: 与现有功能的集成测试
3. **性能测试**: 数据流延迟 < 10ms，吞吐量 > 10000 ticks/秒
4. **强化学习测试**: 智能体收敛性测试
5. **兼容性测试**: 确保现有代码无需修改即可运行
