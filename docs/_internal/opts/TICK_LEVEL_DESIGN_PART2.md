# Backtrader Tick 级架构设计 - Part 2: 详细设计

> 承接 [TICK_LEVEL_ARCHITECTURE_DESIGN.md](./TICK_LEVEL_ARCHITECTURE_DESIGN.md)
>
> 版本: v1.1 | 日期: 2026-02-28 | 状态: 设计阶段（已优化）

- --

## 5. 流式时间戳排序事件队列

### 5.1 设计目标

回测时所有频率数据必须按**全局时间戳严格排序**回放，保证因果关系正确。

- *核心约束**：BTC/USDT 每天约 17M 条 tick，全量预加载需 1.7GB 内存，必须使用流式加载。

### 5.2 StreamingEventQueue 实现

```python
import heapq
from dataclasses import dataclass, field
from enum import IntEnum, Enum
from typing import Any, List, Tuple, Dict, Iterator
from collections import deque
import bisect

class EventPriority(IntEnum):
    """同一时间戳内的优先级（越小越优先）"""
    FUNDING_RATE = 10   # 资金费率最先（影响持仓成本）
    ORDERBOOK = 20      # OrderBook 其次（影响撮合判断）
    TICK = 30           # Tick 紧随（逐笔成交）
    BAR_OPEN = 40       # Bar 开盘
    BAR_CLOSE = 50      # Bar 收盘（触发 next()）
    CUSTOM = 60         # 自定义事件最后

class EventType(str, Enum):
    BAR_OPEN = 'bar_open'
    BAR_CLOSE = 'bar_close'
    DATA = 'data'              # tick/orderbook/funding/custom

@dataclass(order=True)
class Event:
    """全局事件，支持 heapq 排序"""
    timestamp: float                          # 主排序键
    priority: int = field(default=50)         # 同时间戳优先级
    sequence: int = field(default=0)          # 稳定排序序号
    channel_type: str = field(compare=False, default='')  # e.g. 'tick' / 'orderbook' / 'bar'
    channel_name: str = field(compare=False, default='')
    event_type: str = field(compare=False, default=EventType.DATA.value)
    data: Any = field(compare=False, default=None)


class _BufferedIterator:
    """带缓冲的迭代器，减少 I/O 开销

    内存优化：只保持 BUFFER_SIZE 条数据在内存中
    """
    BUFFER_SIZE = 1000

    def __init__(self, source_iter):
        self._source = source_iter
        self._buffer = deque()
        self._eof = False
        self._fill_buffer()

    def _fill_buffer(self):
        """从源迭代器填充缓冲区"""
        for _ in range(self.BUFFER_SIZE):
            try:
                self._buffer.append(next(self._source))
            except StopIteration:
                self._eof = True
                break

    def next(self):
        """获取下一个元素"""
        if not self._buffer:
            if self._eof:
                return None
            self._fill_buffer()
        return self._buffer.popleft() if self._buffer else None

    def peek(self):
        """查看下一个元素但不移除"""
        if not self._buffer:
            if self._eof:
                return None
            self._fill_buffer()
        return self._buffer[0] if self._buffer else None


class _BarIterator:
    """Bar 数据迭代器，生成 bar_open/bar_close 事件"""

    def __init__(self, data):
        self._data = data
        self._idx = 0
        self._bar_count = len(data) if hasattr(data, '__len__') else 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._idx >= self._bar_count:
            raise StopIteration

# 获取当前 bar
        bar = self._data[self._idx]
        self._idx += 1

# 返回 bar_open 和 bar_close 事件
        return (bar, 'open'), (bar, 'close')

    def peek(self):
        """查看下一个 bar 时间戳"""
        if self._idx < self._bar_count:
            bar = self._data[self._idx]
            return bar.datetime[0] if hasattr(bar, 'datetime') else None
        return None


class StreamingEventQueue:
    """流式事件队列 - 内存可控的全局时间戳排序队列

    核心特性：

    1. 分批加载：只加载未来 N 秒的数据到内存
    2. 自动预加载：当数据量低于阈值时自动加载下一批
    3. 内存可控：默认 5 分钟窗口，内存约 100MB

    内存估算：

    - 5 分钟窗口：约 1000 tick × 100 字节 = 100KB（实际含开销约 1MB）
    - 加上 heapq 结构：约 5-10MB

    """

    def __init__(self, channels: List, bars: List, preload_window: float = 300.0):
        """
        Args:
            channels: DataChannel 列表
            bars: DataBase 列表
            preload_window: 预加载窗口（秒），默认 5 分钟
        """
        self._channels = channels
        self._bars = bars
        self._window = preload_window
        self._heap = []
        self._sequence = 0

# 当前处理时间戳
        self._current_ts = float('-inf')
        self._preload_up_to = float('-inf')

# 分块加载的迭代器
        self._channel_iters: Dict = self._create_channel_iters()
        self._bar_iters: Dict = self._create_bar_iters()

    def _create_channel_iters(self) -> Dict:
        """创建每个 channel 的缓冲迭代器"""
        iters = {}
        for ch in self._channels:
            iters[(ch.channel_type, ch.symbol)] = _BufferedIterator(ch.load())
        return iters

    def _create_bar_iters(self) -> Dict:
        """创建 bar 数据迭代器"""
        iters = {}
        for data in self._bars:
            name = getattr(data, '_name', f'data{id(data)}')
            iters[name] = _BarIterator(data)
        return iters

    def _ensure_preload(self, target_ts: float):
        """确保 heap 中有足够的事件直到 target_ts

        Args:
            target_ts: 目标时间戳
        """

# 计算需要预加载到的截止时间
        cutoff = min(target_ts + self._window, self._preload_up_to + 600)

# 从 channels 加载
        for key, it in self._channel_iters.items():
            while True:
                event = it.peek()
                if event is None or event.timestamp > cutoff:
                    break

                it.next()  # 消费 peek 的结果
                self._push_event(event, key[0], key[1])

# 从 bars 加载
        for name, it in self._bar_iters.items():
            while True:

# BarIterator 返回(bar, type)对
                result = it.peek()
                if result is None:
                    break

                bar_open, bar_close = result
                bar = bar_open[0]
                bar_ts = bar.datetime[0] if hasattr(bar, 'datetime') else 0

                if bar_ts > cutoff:
                    break

                it.next()  # 消费 peek 的结果

# 压入 bar_open 和 bar_close 事件
                self._push_bar_event(bar, name, 'open')
                self._push_bar_event(bar, name, 'close')

        self._preload_up_to = cutoff

    def _push_event(self, event, channel_type: str, channel_name: str):
        """压入 channel 事件到 heap"""
        priority_map = {
            'funding_rate': EventPriority.FUNDING_RATE,
            'orderbook': EventPriority.ORDERBOOK,
            'tick': EventPriority.TICK,
        }
        priority = priority_map.get(channel_type, EventPriority.CUSTOM)

        heapq.heappush(self._heap, Event(
            timestamp=event.timestamp,
            priority=priority,
            sequence=self._sequence,
            channel_type=channel_type,
            channel_name=channel_name,
            event_type=EventType.DATA.value,
            data=event
        ))
        self._sequence += 1

    def _push_bar_event(self, bar, bar_name: str, bar_type: str):
        """压入 bar 事件到 heap"""
        if bar_type == 'open':
            priority = EventPriority.BAR_OPEN
            event_type = EventType.BAR_OPEN.value
        else:
            priority = EventPriority.BAR_CLOSE
            event_type = EventType.BAR_CLOSE.value

        bar_ts = float(bar.datetime[0]) if hasattr(bar, 'datetime') else 0.0

        heapq.heappush(self._heap, Event(
            timestamp=bar_ts,
            priority=priority,
            sequence=self._sequence,
            channel_type='bar',
            channel_name=bar_name,
            event_type=event_type,
            data=bar
        ))
        self._sequence += 1

    def pop(self) -> Event:
        """弹出下一个事件，自动触发预加载"""
        if not self._heap:

# 尝试预加载更多数据
            self._ensure_preload(self._current_ts + 60)

        if not self._heap:
            raise StopIteration("No more events")

        event = heapq.heappop(self._heap)
        self._current_ts = event.timestamp
        return event

    def peek(self) -> Event:
        """查看下一个事件但不移除"""
        if not self._heap:
            self._ensure_preload(self._current_ts + 60)
        return self._heap[0] if self._heap else None

    def pop_batch(self, timestamp: float) -> List[Event]:
        """弹出所有指定时间戳的事件"""
        self._ensure_preload(timestamp)

        events = []
        while self._heap and self._heap[0].timestamp == timestamp:
            events.append(heapq.heappop(self._heap))
        return events

    def __len__(self):
        return len(self._heap)

    def __bool__(self):

# 即使 heap 为空，也可能还有未加载的数据
        if self._heap:
            return True

# 检查是否还有未加载的数据
        for it in self._channel_iters.values():
            if it.peek() is not None:
                return True

        for it in self._bar_iters.values():
            if it.peek() is not None:
                return True

        return False

```bash

### 5.3 事件时间线示例

```bash
09:00:00.000  FundingRate(rate=0.0001)           [pri=10]
09:00:00.100  OrderBook(bids/asks)               [pri=20]
09:00:00.150  Tick(price=50000, vol=0.5, buy)    [pri=30]
09:00:00.200  Tick(price=50001, vol=0.3, buy)    [pri=30]
09:00:00.350  OrderBook(bids/asks)               [pri=20]
09:00:00.400  Tick(price=49999, vol=1.0, sell)   [pri=30]
...
09:01:00.000  Bar(o=50000,h=50100,l=49950,c=50050) [pri=50]

```bash

### 5.4 内存优化效果

| 场景 | 全量预加载 | 流式加载（5 分钟窗口） |

|------|-----------|---------------------|

| 1 天 Tick 数据 | 1.7GB | ~10MB |

| 1 天 OrderBook | 350MB | ~5MB |

| 总内存 | ~2GB | ~100MB |

| 加载时间 | 10-30 秒 | 即时启动 |

- --

## 6. 三种运行模式设计

### 6.1 模式定义

```python
class RunMode(IntEnum):
    BAR = 0      # 纯 K 线（默认，完全向后兼容）
    TICK = 1     # 纯 Tick（事件驱动，无固定 K 线时钟）
    MIXED = 2    # 混合（K 线主时钟 + Tick/OB 子事件）

```bash

### 6.2 模式 A：纯 K 线（BAR）

完全向后兼容，现有策略无需修改。即使注册了 Channel 也不触发 on_tick 等回调。

```bash
主时钟: data0 (K 线)
回调:   只触发 next()
EventQueue: 不使用

cerebro.run()  # 默认 BAR 模式

```bash

### 6.3 模式 B：纯 Tick（TICK）

无固定 K 线时钟，所有事件从 StreamingEventQueue 按时间戳顺序弹出触发。

```python
def _run_tick_mode(self, runstrats):
    """纯 Tick 模式：事件驱动，批处理通知"""
    queue = self._event_queue

    while queue:
        ts = queue.peek().timestamp
        events = queue.pop_batch(ts)  # 同一时间戳的事件批处理
        has_main_bar_close = False

# 1. 收集所有 broker 通知（不立即发送）
        for event in events:

# 更新 channel 状态
            if event.channel_type != 'bar':
                channel = self._channel_instances.get(
                    (event.channel_type, event.channel_name))
                if channel:
                    channel.push(event.data)

# Broker 处理事件
            self._broker.process_event(event)

# 2. 分发事件到策略回调
        for event in events:
            for strat in runstrats:
                if event.event_type == EventType.BAR_CLOSE.value:
                    data = self._bar_by_name.get(event.channel_name)
                    if data:
                        strat.on_bar(data, event.data)
                    if data is self.datas[0]:
                        has_main_bar_close = True
                elif event.event_type == EventType.DATA.value:
                    strat._dispatch_event(event)
                if self._event_stop:
                    return

# 3. 统一发送 broker 通知（在同 timestamp 所有事件后）
        self._deliver_notifications(runstrats)

# 4. 主时钟 bar_close 后触发 next()
        if has_main_bar_close:
            for strat in runstrats:
                strat._next()
                if self._event_stop:
                    return

```bash

### 6.4 模式 C：混合（MIXED）

K 线仍作为时间脉冲，但通过 EventQueue 显式注入`bar_open`/`bar_close`事件。

```python
def _run_mixed_mode(self, runstrats):
    """混合模式：bar 时间脉冲 + tick/OB 子事件"""
    queue = self._event_queue

    while queue:
        ts = queue.peek().timestamp
        events = queue.pop_batch(ts)
        has_main_bar_close = False

# 1. 收集所有 broker 通知
        for event in events:
            if event.channel_type != 'bar':
                channel = self._channel_instances.get(
                    (event.channel_type, event.channel_name))
                if channel:
                    channel.push(event.data)

            self._broker.process_event(event)

# 2. MixBroker: 处理完所有事件后，执行 bar 兜底撮合
        if hasattr(self._broker, 'finalize_bar'):
            self._broker.finalize_bar(ts)

# 3. 分发事件到策略
        for event in events:
            for strat in runstrats:
                if event.event_type == EventType.BAR_CLOSE.value:
                    data = self._bar_by_name.get(event.channel_name)
                    if data:
                        strat.on_bar(data, event.data)
                    if data is self.datas[0]:
                        has_main_bar_close = True
                elif event.event_type == EventType.DATA.value:
                    strat._dispatch_event(event)
                if self._event_stop:
                    return

# 4. 统一发送 broker 通知
        self._deliver_notifications(runstrats)

# 5. 主时钟 bar_close 后触发 next()
        if has_main_bar_close:
            for strat in runstrats:
                strat._next()
                if self._event_stop:
                    return

```bash

### 6.5 批处理通知机制

```python
def _deliver_notifications(self, runstrats):
    """统一分发 broker 收集的通知

    放在每个事件后立即调用_brokernotify()的替代方案：

    - 收集所有待发送通知
    - 在同 timestamp 所有事件处理完后统一发送
    - 避免策略在同 timestamp 内收到"未来"通知

    """
    while True:
        order = self._broker.get_notification()
        if order is None:
            break

        owner = order.owner or self.runningstrats[0]
        owner._addnotification(order, quicknotify=True)

```bash

### 6.6 模式对比

| 特性 | BAR | TICK | MIXED |

|------|:---:|:----:|:-----:|

| 向后兼容 | ✅100% | ⚠️需新回调 | ⚠️需新回调 |

| next()调用 | ✅每 bar | ⚠️可选 | ✅每 bar |

| on_tick()调用 | ❌ | ✅每 tick | ✅bar 间 tick |

| 指标可用 | ✅ | ⚠️需桥接 | ✅bar 级 |

| 适用场景 | 传统量化 | 高频/做市 | 中频策略 |

| K 线数据 | 必须 | 可选 | 必须 |

| 内存优化 | 现有 | ✅StreamingEventQueue | ✅StreamingEventQueue |

- --

## 7. Broker 撮合模型设计

### 7.1 现有 BackBroker

```bash
BackBroker.next() 每根 bar 后调用:
  for order in pending:
    _try_exec_market  → 下一 bar 的 open 撮合
    _try_exec_limit   → bar 的 high/low 是否触及 limit
    _try_exec_stop    → bar 的 high/low 是否触及 stop
    _try_exec_close   → bar 的 close 撮合

```bash

### 7.2 TickBroker（纯 Tick/OrderBook）

```python
class TickBroker(BackBroker):
    """Tick 级订单撮合（可选 OrderBook 辅助）

    - 纯 Tick 模式的默认 Broker
    - 若有 OrderBook 事件，可用于更精细的限价判断/深度撮合

    """

# 新增参数
    tick_slippage = ParameterDescriptor(
        default=0, type_=int,
        doc="撮合延迟 tick 数：0=当前 tick,1=下一 tick")
    partial_fill = ParameterDescriptor(
        default=False, type_=bool,
        doc="是否按 tick volume 部分成交")
    market_impact = ParameterDescriptor(
        default=False, type_=bool,
        doc="市价单是否按最新 OrderBook 深度撮合")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._last_orderbook = {}  # {symbol: OrderBookSnapshot}

    def process_event(self, event):
        """处理 tick/orderbook 事件"""
        if event.channel_type == 'tick':
            self._process_pending_orders(event.data)
        elif event.channel_type == 'orderbook':
            self._last_orderbook[event.channel_name] = event.data
            self._check_limits_with_ob(event.data)

# ... 其他撮合方法与原设计一致 ...

```bash

### 7.3 MixBroker（Tick + Bar 混合）

```python
class MixBroker(TickBroker):
    """混合撮合：tick 即时撮合 + bar 兜底撮合

    关键设计：finalize_bar 模式

    - tick/OB 事件：即时撮合（继承自 TickBroker）
    - bar_close 事件：延迟处理，在同 timestamp 所有事件后执行兜底撮合
    - 避免与 BackBroker.next()的撮合逻辑冲突

    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._pending_bar_close = []  # 待处理的 bar_close 事件
        self._data_by_name = {}      # data 名称映射

    def process_event(self, event):
        """统一事件入口"""
        if event.channel_type in ('tick', 'orderbook'):

# tick/OB 事件：即时撮合
            super().process_event(event)
        elif event.event_type == EventType.BAR_CLOSE.value:

# bar_close：延迟到同 timestamp 所有事件处理完后
            self._pending_bar_close.append(event)

    def finalize_bar(self, timestamp: float):
        """处理完同 timestamp 所有事件后调用

        用 bar 的 OHLC 兜底撮合未被 tick 撮合的订单
        """
        for event in self._pending_bar_close:
            data = self._data_by_name.get(event.channel_name)
            if data:
                self._try_fill_remaining_orders(data, event.data)
        self._pending_bar_close.clear()

    def _try_fill_remaining_orders(self, data, bar):
        """用 bar 的 OHLC 兜底撮合剩余订单

        只处理未被 tick 撮合的订单（remsize > 0）
        """
        for order in list(self.pending):
            if order.data._name != data._name:
                continue

# 如果订单已被 tick 撮合完成，跳过
            if order.executed.remsize == 0:
                continue

# 使用 BackBroker 的撮合逻辑
            if order.exectype == Order.Market:
                self._try_exec_market(order, bar)
            elif order.exectype == Order.Limit:
                self._try_exec_limit(order, bar)
            elif order.exectype == Order.Stop:
                self._try_exec_stop(order, bar)
            elif order.exectype == Order.StopLimit:
                self._try_exec_stoplimit(order, bar)

```bash

### 7.4 三种 Broker 对比

| 特性 | BackBroker | TickBroker | MixBroker |

|------|:----------:|:----------:|:---------:|

| 数据需求 | OHLC bar | Tick 流(+可选 OB) | Bar + Tick(+可选 OB) |

| 撮合精度 | bar 级 | tick 级 | tick 即时 + bar 兜底 |

| 市价单 | 下一 bar open | 当前 tick | 当前 tick / bar 兜底 |

| 限价单 | high/low 判断 | tick 价格/OB | tick 价格/OB + bar 兜底 |

| 滑点 | 固定/百分比 | tick 真实 | tick 真实 + bar 兜底 |

| 部分成交 | filler | tick volume | tick volume |

| 真实度 | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |

- --

## 8. Strategy 回调接口

### 8.1 新增回调

```python
class Strategy(StrategyBase):

# === 现有不变 ===
    def next(self): pass
    def prenext(self): pass
    def start(self): pass
    def stop(self): pass
    def notify_order(self, order): pass
    def notify_trade(self, trade): pass

# === 新增 Channel 回调 ===

    def on_tick(self, channel, tick):
        """Tick 到达时调用"""
        pass

    def on_orderbook(self, channel, orderbook):
        """OrderBook 更新时调用"""
        pass

    def on_bar(self, data, bar):
        """Bar 到达时调用（MIX/TICK 模式）

        语义：

        - 每个 bar_close 事件触发一次，对应各自 data
        - 与 on_tick/on_orderbook 处于同一时间序列
        - next() 在主时钟数据的 bar_close 且该时间戳的所有 bar_close 处理完后触发

        """
        pass

    def on_funding(self, channel, funding):
        """FundingRate 更新时调用"""
        pass

    def on_channel(self, channel, event):
        """通用 Channel 回调（自定义类型）"""
        pass

```bash

### 8.2 回调执行顺序（v1.1 优化版）

```bash
同一 timestamp 内的执行顺序：

1. broker.process_event() × N  # 处理所有事件，收集通知

2. MixBroker.finalize_bar()     # bar 兜底撮合（仅 MIXED 模式）

3. on_funding()/on_orderbook()/on_tick() × N  # 策略回调

4. on_bar() × N                 # bar 回调

5. _deliver_notifications()      # 统一发送 broker 通知

6. next()                        # 主时钟 bar_close 后触发

```bash

- --

## 9. 数据通道实现

### 9.1 DataChannel 基类

```python
from collections import deque

class DataChannel:
    channel_type = 'generic'

    def __init__(self, symbol, maxlen=10000, **kwargs):
        self.symbol = symbol
        self.maxlen = maxlen
        self.params = kwargs
        self._buffer = deque(maxlen=maxlen)
        self._event_count = 0

    def push(self, event):
        self._buffer.append(event)
        self._event_count += 1

    @property
    def latest(self):
        return self._buffer[-1] if self._buffer else None

    def history(self, n=None):
        if n is None:
            return list(self._buffer)
        return list(self._buffer)[-n:]

    def load(self):
        """回测：从文件加载，按时间升序 yield 事件"""
        raise NotImplementedError

```bash

### 9.2 数据事件定义

```python
from dataclasses import dataclass

@dataclass
class TickEvent:
    timestamp: float
    price: float
    volume: float
    direction: str       # 'buy'/'sell'
    trade_id: str = ''
    symbol: str = ''

@dataclass
class OrderBookSnapshot:
    timestamp: float
    symbol: str
    bids: list           # [(price, qty), ...] 降序
    asks: list           # [(price, qty), ...] 升序

    @property
    def best_bid(self):
        return self.bids[0] if self.bids else (0.0, 0.0)

    @property
    def best_ask(self):
        return self.asks[0] if self.asks else (0.0, 0.0)

    @property
    def spread(self):
        return self.best_ask[0] - self.best_bid[0]

    @property
    def mid_price(self):
        return (self.best_ask[0] + self.best_bid[0]) / 2

@dataclass
class FundingEvent:
    timestamp: float
    symbol: str
    rate: float
    mark_price: float
    next_funding_time: float
    predicted_rate: float = 0.0

```bash

### 9.3 ChannelBridge（可选 LineSeries 桥接）

```python
class ChannelBridge:
    """Channel 到 LineSeries 的轻量桥接

    重要限制：

    - 本桥接不支持 runonce 模式！
    - 原因：Channel 数据是流式追加，无法预加载
    - 如需 runonce 性能，请使用 Channel 内置方法（如 vwap）

    """

    runonce_allowed = False  # 标记不支持 runonce

    def __init__(self, channel, line_mapping=None):
        self.channel = channel
        self._mapping = line_mapping or {'price': 'price'}

    def once(self, start, end):
        """once 模式下禁用，抛出明确错误"""
        raise RuntimeError(
            "ChannelBridge does not support runonce mode. "
            "Use Channel's built-in methods (vwap, buy_sell_ratio, etc.) "
            "or run with runonce=False."
        )

```bash

- --

## 10. Cerebro 集成

### 10.1 新增 API

```python
class Cerebro:
    def __init__(self, **kwargs):

# ... 现有 ...
        self._channels = []           # [(cls, symbol, kwargs, shared)]
        self._channel_instances = {}  # {(type, symbol): channel}
        self._event_queue = None
        self._run_mode = None
        self._pending_notifications = []  # 批处理通知

    def add_channel(self, channel_cls, symbol=None, shared=True, **kwargs):
        """注册数据通道

        Args:
            channel_cls: Channel 类
            symbol: 交易对标识
            shared: 是否在所有策略间共享（默认 True）
                    False 则为每个策略创建独立 Channel 实例

        Example:
            cerebro.add_channel(bt.channels.TickChannel,
                symbol='BTC/USDT', dataname='ticks.csv')
        """
        self._channels.append((channel_cls, symbol, kwargs, shared))
        return self

    def run(self, mode=None, **kwargs):

# 模式推断
        if mode is None:
            self._run_mode = self._infer_run_mode()
        else:
            self._run_mode = mode

# ChannelBridge runonce 检测
        if self._run_mode != RunMode.BAR and self._dorunonce:
            self._check_channel_bridge_compatibility(runstrats)

# ... 运行逻辑 ...

    def _check_channel_bridge_compatibility(self, runstrats):
        """检测 ChannelBridge 与 runonce 的兼容性"""
        for strat in runstrats:
            for obj in strat._getindicators():
                if isinstance(obj, ChannelBridge):
                    raise ValueError(
                        f"ChannelBridge used in strategy '{strat.__class__.__name__}' "
                        "requires runonce=False. Set cerebro.run(runonce=False)"
                    )

    def _init_channels(self, runstrats):
        """初始化 Channel 实例"""
        for ch_cls, symbol, kwargs, shared in self._channels:
            if symbol is None and self.datas:
                symbol = getattr(self.datas[0], '_name', 'default')

            if shared:

# 所有策略共享同一 Channel
                ch = ch_cls(symbol=symbol, **kwargs)
                for strat in runstrats:
                    if not hasattr(strat, '_channels'):
                        strat._channels = {}
                    strat._channels[(ch.channel_type, symbol)] = ch
            else:

# 每个策略独立 Channel
                for strat in runstrats:
                    ch = ch_cls(symbol=symbol, **kwargs)
                    if not hasattr(strat, '_channels'):
                        strat._channels = {}
                    strat._channels[(ch.channel_type, symbol)] = ch

    def _init_event_queue(self, runstrats):
        """初始化流式事件队列"""
        self._event_queue = StreamingEventQueue(
            channels=list(self._channel_instances.values()),
            bars=self.datas,
            preload_window=self.p.get('preload_window', 300)
        )

# bar 名称映射
        self._bar_by_name = {
            getattr(d, '_name', f'data{i}'): d
            for i, d in enumerate(self.datas)
        }
        for strat in runstrats:
            strat._bar_by_name = self._bar_by_name

```bash

- --

## 11. 实盘交易集成

### 11.1 实盘模式差异（v1.1 优化）

| 特性 | 回测 | 实盘 |

|------|------|------|

| 数据来源 | CSV/Parquet 文件 | WebSocket 实时推送 |

| EventQueue | StreamingEventQueue | 不使用，实时分发 |

| 时间驱动 | 事件时间戳(event time) | 事件时间 + 心跳检测 |

| Broker | 模拟撮合 | 真实交易所 |

| 延迟 | 无 | 网络延迟 |

### 11.2 实盘事件队列

```python
class LiveEventQueue:
    """实盘事件队列 - 仍使用事件时间排序

    重要：实盘也使用事件时间而非 wall time，保证回测与实盘行为一致
    wall time 仅用于心跳检测和延迟告警
    """

    def __init__(self, max_latency=5.0):
        """
        Args:
            max_latency: 最大允许延迟（秒），超过则告警
        """
        self._heap = []
        self._sequence = 0
        self._max_latency = max_latency
        self._last_event_ts = 0

    def push(self, event):
        """接收 WebSocket 事件"""

# 检测延迟
        latency = time.time() - event.timestamp
        if latency > self._max_latency:
            logger.warning(f"High latency: {latency:.2f}s")

# 拒绝乱序事件
        if event.timestamp < self._last_event_ts:
            logger.warning(f"Out-of-order event rejected: {event.timestamp}")
            return False

        heapq.heappush(self._heap, Event(
            timestamp=event.timestamp,
            priority=50,
            sequence=self._sequence,
            channel_type=event.channel_type,
            channel_name=event.symbol,
            event_type=EventType.DATA.value,
            data=event
        ))
        self._sequence += 1
        self._last_event_ts = event.timestamp
        return True

    def pop(self, timeout=1.0):
        """带超时的弹出"""
        if not self._heap:
            time.sleep(timeout)
            return None
        return heapq.heappop(self._heap)

```bash

- --

## 12. 用户使用示例

（与原设计一致，略）

- --

## 13. 实现路线图（v1.1 优化）

### Phase 0: 架构验证（1 周）← 新增

- [ ] 创建 StreamingEventQueue 原型
- [ ] 简单 tick 回测验证
- [ ] 内存使用基准测试

### Phase 1: 核心基础设施（3 周）

- [ ] `channel.py`: DataChannel + StreamingEventQueue
- [ ] `channels/tick.py`: TickChannel + TickEvent
- [ ] `channels/orderbook.py`: OrderBookChannel
- [ ] `channels/funding.py`: FundingRateChannel
- [ ] `strategy.py`: 新增回调
- [ ] `cerebro.py`: add_channel() + 批处理通知
- [ ] 单元测试

### Phase 2: 回测引擎（3 周）

- [ ] `cerebro.py`: _run_tick_mode() + _run_mixed_mode()
- [ ] `brokers/tickbroker.py`: TickBroker
- [ ] `brokers/mixbroker.py`: MixBroker（finalize_bar 模式）
- [ ] 集成测试 + 性能测试

### Phase 3: OrderBook 撮合（2 周）

- [ ] 深度撮合算法
- [ ] 限价单排队模拟
- [ ] 测试

### Phase 4: 桥接与实盘（2 周）

- [ ] `channels/bridge.py`: ChannelBridge（runonce 禁用）
- [ ] `channels/ccxt/`: 实时数据
- [ ] 实盘事件分发

### Phase 5: 文档与示例（1 周）

- [ ] 文档完善
- [ ] 示例代码
- [ ] 性能调优指南

- --

## 14. 附录

### 14.1 CSV 文件格式

- *Tick CSV** (`ticks.csv`):

```csv
timestamp,price,volume,direction,trade_id
1709136000.100,50000.5,0.5,buy,12345
1709136000.200,50001.0,0.3,sell,12346

```bash

- *OrderBook JSONL** (`ob.jsonl`):

```json
{"timestamp":1709136000.1,"bids":[[50000,1.5],[49999,2.0]],"asks":[[50001,1.0],[50002,3.0]]}

```bash

### 14.2 内存估算（优化后）

| 数据类型 | 全量预加载 | 流式加载（5 分钟窗口） |

|----------|-----------|---------------------|

| Tick (1 天) | 1.7GB | ~10MB |

| OrderBook (1 天) | 350MB | ~5MB |

| 总计 | ~2GB | ~100MB |
