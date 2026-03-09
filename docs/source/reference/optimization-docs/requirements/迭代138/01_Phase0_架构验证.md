# Phase 0: 架构验证与必须优化

> 周期: 1 周 | 优先级: 🔴 最高 | 风险: 低

- --

## 1. 目标

验证 Tick 级架构的可行性，并实施必须的优化项，为后续 Phase 奠定基础。

### 1.1 核心目标

- ✅ 验证 StreamingEventQueue 的内存控制能力
- ✅ 验证事件时间戳排序的正确性
- ✅ 实施自适应预加载窗口优化
- ✅ 实施数据验证与修复机制
- ✅ 实施策略异常隔离机制

### 1.2 成功标准

| 指标 | 目标 | 测量方法 |

|------|------|---------|

| 内存使用 | < 200MB (1 天 tick) | memory_profiler |

| 事件排序 | 100%正确 | 单元测试 |

| 数据验证 | 识别并修复 90%+ | 集成测试 |

| 异常隔离 | 单策略崩溃不影响其他 | 集成测试 |

- --

## 2. 实施内容

### 2.1 StreamingEventQueue 原型（2 天）

#### 2.1.1 基础实现

- *文件**: `backtrader/channel.py`

```python
import heapq
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, List, Dict
from collections import deque

class EventPriority(IntEnum):
    """事件优先级"""
    FUNDING_RATE = 10
    ORDERBOOK = 20
    TICK = 30
    BAR_OPEN = 40
    BAR_CLOSE = 50
    CUSTOM = 60

@dataclass(order=True)
class Event:
    """全局事件"""
    timestamp: float
    priority: int = field(default=50)
    sequence: int = field(default=0)
    channel_type: str = field(compare=False, default='')
    channel_name: str = field(compare=False, default='')
    event_type: str = field(compare=False, default='data')
    data: Any = field(compare=False, default=None)

class StreamingEventQueue:
    """流式事件队列 - 基础版本"""

    def __init__(self, channels: List, bars: List,
                 preload_window: float = 300.0):
        self._channels = channels
        self._bars = bars
        self._window = preload_window
        self._heap = []
        self._sequence = 0
        self._current_ts = float('-inf')
        self._preload_up_to = float('-inf')

# 迭代器
        self._channel_iters = {}
        self._bar_iters = {}

    def _ensure_preload(self, target_ts: float):
        """预加载到目标时间戳"""
        cutoff = target_ts + self._window

# 从 channels 加载
        for key, it in self._channel_iters.items():
            while True:
                event = it.peek()
                if event is None or event.timestamp > cutoff:
                    break
                it.next()
                self._push_event(event, key[0], key[1])

        self._preload_up_to = cutoff

    def pop(self) -> Event:
        """弹出下一个事件"""
        if not self._heap:
            self._ensure_preload(self._current_ts + 60)

        if not self._heap:
            raise StopIteration("No more events")

        event = heapq.heappop(self._heap)
        self._current_ts = event.timestamp
        return event

    def peek(self) -> Event:
        """查看下一个事件"""
        if not self._heap:
            self._ensure_preload(self._current_ts + 60)
        return self._heap[0] if self._heap else None

```bash

- *测试**: `tests/phase0/test_streaming_queue_basic.py`

```python
import pytest
from backtrader.channel import StreamingEventQueue, Event

def test_event_ordering():
    """测试事件时间戳排序"""
    events = [
        Event(timestamp=100.0, priority=30, sequence=0),
        Event(timestamp=100.0, priority=20, sequence=1),
        Event(timestamp=99.0, priority=30, sequence=2),
    ]

    heap = []
    for e in events:
        heapq.heappush(heap, e)

# 验证排序：时间戳 -> 优先级 -> 序列号
    e1 = heapq.heappop(heap)
    assert e1.timestamp == 99.0

    e2 = heapq.heappop(heap)
    assert e2.timestamp == 100.0 and e2.priority == 20

    e3 = heapq.heappop(heap)
    assert e3.timestamp == 100.0 and e3.priority == 30

def test_memory_usage():
    """测试内存使用"""

# 模拟 1 天 tick 数据（约 17M 条）

# 使用 5 分钟窗口，应该只加载约 60K 条
    pass  # 详细实现

```bash

- --

#### 2.1.2 统一事件数据结构（1 天）

- *新增**: `backtrader/events.py`

```python
from dataclasses import dataclass
from typing import Optional
from abc import ABC, abstractmethod

@dataclass
class EventData(ABC):
    """事件数据基类 - 统一所有事件格式"""
    timestamp: float                    # Unix 时间戳（秒）
    symbol: str                         # 交易对符号
    exchange: str = ''                  # 交易所名称
    asset_type: str = 'spot'           # 资产类型
    local_time: Optional[float] = None  # 本地接收时间

    @property
    @abstractmethod
    def event_type(self) -> str:
        """事件类型标识"""
        pass

    def validate(self) -> bool:
        """验证数据有效性"""
        if self.timestamp <= 0:
            return False
        if not self.symbol:
            return False
        return True

@dataclass
class TickEvent(EventData):
    """Tick 事件（统一格式，兼容现有 TickerData）"""
    price: float
    volume: float
    direction: str  # 'buy'/'sell'
    trade_id: str = ''

# 兼容 TickerData 的字段
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    bid_volume: Optional[float] = None
    ask_volume: Optional[float] = None

    @property
    def event_type(self) -> str:
        return 'tick'

    def validate(self) -> bool:
        if not super().validate():
            return False
        if self.price <= 0 or self.volume < 0:
            return False
        if self.direction not in ('buy', 'sell'):
            return False
        return True

```bash

- *说明**：
- 统一现有的`TickerData`、`OrderBookData`、`FundingRateData`格式
- 使用 dataclass 提升性能（内存减少 60%，访问速度提升 5-10 倍）
- 保持向后兼容（现有容器作为适配器）

#### 2.1.3 自适应窗口优化（1 天）

- *增强**: `backtrader/channel.py`

```python
class StreamingEventQueue:
    """增加自适应窗口"""

    def __init__(self, *args,
                 max_memory_mb: int = 200,
                 adaptive: bool = True, **kwargs):

# ... 基础初始化 ...
        self._max_memory = max_memory_mb *1024*1024
        self._adaptive = adaptive
        self._window_min = 60.0
        self._window_max = 600.0
        self._adjustment_count = 0

    def _adjust_window(self):
        """动态调整窗口大小"""
        if not self._adaptive:
            return

        current_memory = self._estimate_memory_usage()

        if current_memory > self._max_memory*0.9:

# 内存压力大，缩小窗口
            old_window = self._window
            self._window = max(self._window*0.8, self._window_min)
            self._adjustment_count += 1
            logger.info(f"Window shrink: {old_window:.1f}s -> {self._window:.1f}s")

        elif current_memory < self._max_memory*0.5:

# 内存充足，扩大窗口
            old_window = self._window
            self._window = min(self._window*1.2, self._window_max)
            self._adjustment_count += 1
            logger.info(f"Window expand: {old_window:.1f}s -> {self._window:.1f}s")

    def _estimate_memory_usage(self) -> int:
        """估算内存使用（字节）"""
        event_size = 200  # 保守估计
        heap_overhead = 1.5

        heap_memory = len(self._heap)*event_size*heap_overhead

        buffer_memory = 0
        for it in self._channel_iters.values():
            if hasattr(it, '_buffer'):
                buffer_memory += len(it._buffer)*event_size

        return int(heap_memory + buffer_memory)

    def pop(self) -> Event:
        """弹出事件 - 增加自适应调整"""
        if not self._heap:
            self._ensure_preload(self._current_ts + 60)

        if not self._heap:
            raise StopIteration("No more events")

        event = heapq.heappop(self._heap)
        self._current_ts = event.timestamp

# 定期调整窗口
        if len(self._heap) % 1000 == 0:
            self._adjust_window()

        return event

```bash

- *测试**: `tests/phase0/test_adaptive_window.py`

```python
def test_window_shrink_on_memory_pressure():
    """测试内存压力下窗口缩小"""
    queue = StreamingEventQueue(
        channels=[], bars=[],
        preload_window=300.0,
        max_memory_mb=10,  # 设置很小的限制
        adaptive=True
    )

# 模拟大量事件

# ... 验证窗口缩小 ...
    assert queue._window < 300.0

def test_window_expand_on_low_memory():
    """测试内存充足时窗口扩大"""

# ... 详细实现 ...

```bash

- --

### 2.2 数据验证与修复（1.5 天）

#### 2.2.1 DataChannel 基类

- *文件**: `backtrader/channel.py`

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class DataValidationResult:
    """数据验证结果"""
    valid: bool
    error: Optional[str] = None
    fixed: bool = False
    original_value: Any = None
    fixed_value: Any = None

class DataChannel:
    """数据通道基类"""

    channel_type = 'generic'

    def __init__(self, symbol, maxlen=10000,
                 validate=True, auto_fix=True, **kwargs):
        self.symbol = symbol
        self.maxlen = maxlen
        self.params = kwargs
        self._buffer = deque(maxlen=maxlen)
        self._event_count = 0

# 验证配置
        self._validate = validate
        self._auto_fix = auto_fix
        self._validation_errors = []
        self._last_timestamp = None

    def push(self, event):
        """推送事件 - 增加验证"""
        if self._validate:
            result = self._validate_event(event)

            if not result.valid:
                self._validation_errors.append(result)

                if self._auto_fix and result.fixed:
                    event = result.fixed_value
                    logger.warning(f"Data fixed: {result.error}")
                else:
                    logger.error(f"Invalid data dropped: {result.error}")
                    return

        self._buffer.append(event)
        self._event_count += 1

    def _validate_event(self, event) -> DataValidationResult:
        """验证事件 - 子类实现"""
        return DataValidationResult(valid=True)

    @property
    def latest(self):
        return self._buffer[-1] if self._buffer else None

    def history(self, n=None):
        if n is None:
            return list(self._buffer)
        return list(self._buffer)[-n:]

    def load(self):
        """加载数据 - 子类实现"""
        raise NotImplementedError

```bash

- --

#### 2.2.2 TickChannel 验证

- *文件**: `backtrader/channels/tick.py`

```python
from dataclasses import dataclass
from backtrader.channel import DataChannel, DataValidationResult

@dataclass
class TickEvent:
    timestamp: float
    price: float
    volume: float
    direction: str  # 'buy'/'sell'
    trade_id: str = ''
    symbol: str = ''

class TickChannel(DataChannel):
    """Tick 数据通道"""

    channel_type = 'tick'

    def _validate_event(self, event: TickEvent) -> DataValidationResult:
        """验证 tick 数据"""

# 1. 价格检查
        if event.price <= 0:
            return DataValidationResult(
                valid=False,
                error=f"Invalid price: {event.price}"
            )

# 2. 成交量检查
        if event.volume < 0:
            return DataValidationResult(
                valid=False,
                error=f"Invalid volume: {event.volume}"
            )

# 3. 方向检查
        if event.direction not in ('buy', 'sell'):

# 尝试修复
            fixed_direction = 'buy' if event.direction.lower() in ('b', '1', 'long') else 'sell'
            fixed_event = TickEvent(
                timestamp=event.timestamp,
                price=event.price,
                volume=event.volume,
                direction=fixed_direction,
                trade_id=event.trade_id,
                symbol=event.symbol
            )
            return DataValidationResult(
                valid=False,
                error=f"Invalid direction: {event.direction}",
                fixed=True,
                original_value=event,
                fixed_value=fixed_event
            )

# 4. 时间戳检查（乱序）
        if self._last_timestamp is not None:
            if event.timestamp < self._last_timestamp:

# 尝试修复：使用上一个时间戳+1ms
                fixed_event = TickEvent(
                    timestamp=self._last_timestamp + 0.001,
                    price=event.price,
                    volume=event.volume,
                    direction=event.direction,
                    trade_id=event.trade_id,
                    symbol=event.symbol
                )
                return DataValidationResult(
                    valid=False,
                    error=f"Out-of-order: {event.timestamp} < {self._last_timestamp}",
                    fixed=True,
                    original_value=event,
                    fixed_value=fixed_event
                )

        self._last_timestamp = event.timestamp
        return DataValidationResult(valid=True)

    def load(self):
        """从 CSV 加载 tick 数据"""

# 简化实现，实际应使用 pandas
        import csv

        if 'dataname' not in self.params:
            return

        with open(self.params['dataname']) as f:
            reader = csv.DictReader(f)
            for row in reader:
                event = TickEvent(
                    timestamp=float(row['timestamp']),
                    price=float(row['price']),
                    volume=float(row['volume']),
                    direction=row['direction'],
                    trade_id=row.get('trade_id', ''),
                    symbol=self.symbol
                )
                yield event

```bash

- *测试**: `tests/phase0/test_data_validation.py`

```python
def test_invalid_price_rejected():
    """测试无效价格被拒绝"""
    channel = TickChannel('BTC/USDT', validate=True, auto_fix=False)

    event = TickEvent(timestamp=100.0, price=-50000, volume=1.0, direction='buy')
    channel.push(event)

    assert len(channel._buffer) == 0
    assert len(channel._validation_errors) == 1

def test_out_of_order_fixed():
    """测试乱序时间戳被修复"""
    channel = TickChannel('BTC/USDT', validate=True, auto_fix=True)

    channel.push(TickEvent(timestamp=100.0, price=50000, volume=1.0, direction='buy'))
    channel.push(TickEvent(timestamp=99.0, price=50001, volume=1.0, direction='sell'))

    assert len(channel._buffer) == 2
    assert channel._buffer[1].timestamp == 100.001  # 修复后的时间戳

```bash

- --

### 2.3 策略异常隔离（1.5 天）

#### 2.3.1 Cerebro 异常处理

- *文件**: `backtrader/cerebro.py`

```python
import traceback
import logging

logger = logging.getLogger(__name__)

class Cerebro:
    """增加策略异常隔离"""

    def __init__(self, *args, isolate_strategies=True, **kwargs):

# ... 现有初始化 ...
        self._isolate_strategies = isolate_strategies
        self._strategy_errors = {}
        self._max_errors_per_strategy = 100

    def _handle_strategy_error(self, strat, error, timestamp):
        """处理策略异常"""
        strat_name = strat.__class__.__name__

        if strat_name not in self._strategy_errors:
            self._strategy_errors[strat_name] = []

        error_record = {
            'timestamp': timestamp,
            'error': str(error),
            'traceback': traceback.format_exc()
        }
        self._strategy_errors[strat_name].append(error_record)

        logger.error(
            f"Strategy {strat_name} error at {timestamp}: {error}\n"
            f"{error_record['traceback']}"
        )

# 错误次数过多时禁用策略
        if len(self._strategy_errors[strat_name]) > self._max_errors_per_strategy:
            logger.critical(
                f"Strategy {strat_name} disabled due to {self._max_errors_per_strategy}+ errors"
            )
            return True  # 表示应该移除策略

        return False

    def _safe_strategy_call(self, strat, method_name, *args, **kwargs):
        """安全调用策略方法"""
        if not self._isolate_strategies:

# 不隔离，直接调用
            method = getattr(strat, method_name)
            return method(*args, **kwargs)

        try:
            method = getattr(strat, method_name)
            return method(*args, **kwargs)
        except Exception as e:
            should_remove = self._handle_strategy_error(
                strat, e, self._current_timestamp
            )
            if should_remove:
                raise StrategyDisabledException(
                    f"Strategy {strat.__class__.__name__} disabled"
                )
            return None

    def get_strategy_errors(self, strategy_name=None):
        """获取策略错误记录"""
        if strategy_name:
            return self._strategy_errors.get(strategy_name, [])
        return self._strategy_errors

class StrategyDisabledException(Exception):
    """策略被禁用异常"""
    pass

```bash

- *测试**: `tests/phase0/test_strategy_isolation.py`

```python
def test_single_strategy_error_isolated():
    """测试单个策略错误不影响其他策略"""

    class BuggyStrategy(bt.Strategy):
        def next(self):
            if len(self) == 5:
                raise ValueError("Intentional error")

    class GoodStrategy(bt.Strategy):
        def next(self):
            self.good_calls = getattr(self, 'good_calls', 0) + 1

    cerebro = bt.Cerebro(isolate_strategies=True)
    cerebro.addstrategy(BuggyStrategy)
    cerebro.addstrategy(GoodStrategy)

# ... 添加数据 ...

    results = cerebro.run()

# BuggyStrategy 应该有错误记录
    errors = cerebro.get_strategy_errors('BuggyStrategy')
    assert len(errors) > 0

# GoodStrategy 应该正常运行
    good_strat = results[1]
    assert good_strat.good_calls > 5

def test_strategy_disabled_after_max_errors():
    """测试策略错误过多后被禁用"""

# ... 详细实现 ...

```bash

- --

## 3. 性能基准测试（1 天）

### 3.1 内存基准

- *文件**: `tests/phase0/benchmark_memory.py`

```python
import psutil
import time
from backtrader.channel import StreamingEventQueue
from backtrader.channels.tick import TickChannel, TickEvent

def generate_tick_data(days=1):
    """生成模拟 tick 数据"""
    ticks_per_second = 200
    seconds_per_day = 86400
    total_ticks = ticks_per_second *seconds_per_day*days

    for i in range(total_ticks):
        yield TickEvent(
            timestamp=float(i) / ticks_per_second,
            price=50000 + (i % 1000)*0.1,
            volume=0.1 + (i % 10)*0.01,
            direction='buy' if i % 2 == 0 else 'sell',
            symbol='BTC/USDT'
        )

def benchmark_memory():
    """内存基准测试"""
    process = psutil.Process()

# 记录初始内存
    initial_memory = process.memory_info().rss / 1024 / 1024
    print(f"Initial memory: {initial_memory:.1f} MB")

# 创建 StreamingEventQueue

# 模拟 1 天 tick 数据
    queue = StreamingEventQueue(
        channels=[],
        bars=[],
        preload_window=300.0,  # 5 分钟窗口
        max_memory_mb=200,
        adaptive=True
    )

# 测试内存使用
    start = time.time()
    event_count = 0

    for event in generate_tick_data(days=1):
        queue._push_event(event, 'tick', 'BTC/USDT')
        event_count += 1

        if event_count % 10000 == 0:
            current_memory = process.memory_info().rss / 1024 / 1024
            print(f"Events: {event_count}, Memory: {current_memory:.1f} MB")

    elapsed = time.time() - start
    final_memory = process.memory_info().rss / 1024 / 1024

    print(f"\n=== Results ===")
    print(f"Total events: {event_count}")
    print(f"Time: {elapsed:.2f}s")
    print(f"Final memory: {final_memory:.1f} MB")
    print(f"Memory growth: {final_memory - initial_memory:.1f} MB")
    print(f"Events/sec: {event_count / elapsed:.0f}")

# 验证目标
    assert final_memory - initial_memory < 200, "Memory usage exceeds 200MB"

if __name__ == '__main__':
    benchmark_memory()

```bash

### 3.2 性能基准

- *文件**: `tests/phase0/benchmark_performance.py`

```python
def benchmark_event_processing():
    """事件处理性能基准"""

    queue = StreamingEventQueue(...)

    start = time.time()
    processed = 0

    while queue:
        event = queue.pop()
        processed += 1

    elapsed = time.time() - start

    print(f"Processed {processed} events in {elapsed:.2f}s")
    print(f"Throughput: {processed / elapsed:.0f} events/sec")

# 目标：> 10K events/sec
    assert processed / elapsed > 10000

if __name__ == '__main__':
    benchmark_event_processing()

```bash

- --

## 4. 交付物

### 4.1 代码

- [ ] `backtrader/channel.py` - StreamingEventQueue + DataChannel
- [ ] `backtrader/channels/__init__.py`
- [ ] `backtrader/channels/tick.py` - TickChannel
- [ ] `backtrader/cerebro.py` - 策略异常隔离（部分修改）

### 4.2 测试

- [ ] `tests/phase0/test_streaming_queue_basic.py`
- [ ] `tests/phase0/test_adaptive_window.py`
- [ ] `tests/phase0/test_data_validation.py`
- [ ] `tests/phase0/test_strategy_isolation.py`
- [ ] `tests/phase0/benchmark_memory.py`
- [ ] `tests/phase0/benchmark_performance.py`

### 4.3 文档

- [ ] Phase 0 完成报告
- [ ] 性能基准测试报告
- [ ] 已知问题清单

- --

## 5. 验收标准

### 5.1 功能验收

- [ ] StreamingEventQueue 正确排序事件
- [ ] 自适应窗口在内存压力下缩小
- [ ] 数据验证识别并修复 90%+常见错误
- [ ] 策略异常隔离正常工作

### 5.2 性能验收

- [ ] 1 天 tick 数据内存使用 < 200MB
- [ ] 事件处理吞吐量 > 10K events/sec
- [ ] 窗口调整响应时间 < 1 秒

### 5.3 质量验收

- [ ] 单元测试覆盖率 >= 80%
- [ ] 所有测试通过
- [ ] 代码审查通过

- --

## 6. 风险与应对

| 风险 | 概率 | 影响 | 应对措施 |

|------|------|------|---------|

| 内存估算不准确 | 中 | 高 | 实际测量+调整系数 |

| 性能不达标 | 低 | 中 | 优化 heapq 操作 |

| 数据验证规则不完整 | 中 | 低 | 迭代完善 |

- --

## 7. 时间表

| 任务 | 工作量 | 开始 | 结束 |

|------|--------|------|------|

| StreamingEventQueue 基础 | 2 天 | Day 1 | Day 2 |

| 自适应窗口优化 | 1 天 | Day 2 | Day 3 |

| 数据验证与修复 | 1.5 天 | Day 3 | Day 4.5 |

| 策略异常隔离 | 1.5 天 | Day 4.5 | Day 6 |

| 性能基准测试 | 1 天 | Day 6 | Day 7 |

- --

## 8. 下一步

Phase 0 完成后，进入 Phase 1：核心基础设施开发。
