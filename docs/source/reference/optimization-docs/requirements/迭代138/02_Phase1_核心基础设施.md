# Phase 1: 核心基础设施

> 周期: 3 周 | 优先级: 🔴 高 | 风险: 中

---
## 1. 目标

实现 Tick 级架构的核心基础设施，包括完整的 Channel 体系、Strategy 回调机制和优化的通知系统。

### 1.1 核心目标

- ✅ 实现完整的 Channel 体系（Tick/OrderBook/Funding）
- ✅ 实现 Strategy 新增回调机制
- ✅ 实现优先级通知队列
- ✅ 实现 Channel 共享模式
- ✅ 集成到 Cerebro

### 1.2 成功标准

| 指标 | 目标 | 测量方法 |

|------|------|---------|

| 功能完整性 | 100% | 所有 Channel 正常工作 |

| 回调触发 | 100%准确 | 集成测试 |

| 回归测试 | 100%通过 | 1020/1020 |

| 代码覆盖率 | >= 80% | pytest-cov |

---
## 2. 实施内容

### 2.1 OrderBookChannel 实现（3 天）

#### 2.1.1 OrderBook 数据结构

- *文件**: `backtrader/channels/orderbook.py`

```python
from dataclasses import dataclass
from typing import List, Tuple
from backtrader.channel import DataChannel, DataValidationResult

@dataclass
class OrderBookSnapshot:
    """订单簿快照"""
    timestamp: float
    symbol: str
    bids: List[Tuple[float, float]]  # [(price, qty), ...] 降序
    asks: List[Tuple[float, float]]  # [(price, qty), ...] 升序

    @property
    def best_bid(self) -> Tuple[float, float]:
        """最优买价"""
        return self.bids[0] if self.bids else (0.0, 0.0)

    @property
    def best_ask(self) -> Tuple[float, float]:
        """最优卖价"""
        return self.asks[0] if self.asks else (0.0, 0.0)

    @property
    def spread(self) -> float:
        """买卖价差"""
        return self.best_ask[0] - self.best_bid[0]

    @property
    def mid_price(self) -> float:
        """中间价"""
        return (self.best_ask[0] + self.best_bid[0]) / 2

    def get_depth(self, side: str, levels: int = 5) -> List[Tuple[float, float]]:
        """获取指定档位深度"""
        if side == 'bid':
            return self.bids[:levels]
        elif side == 'ask':
            return self.asks[:levels]
        return []

    def total_volume(self, side: str, levels: int = 5) -> float:
        """计算总挂单量"""
        depth = self.get_depth(side, levels)
        return sum(qty for _, qty in depth)

class OrderBookChannel(DataChannel):
    """订单簿数据通道"""

    channel_type = 'orderbook'

    def __init__(self, symbol, maxlen=1000,
                 max_levels=20, **kwargs):
        super().__init__(symbol, maxlen, **kwargs)
        self.max_levels = max_levels

    def _validate_event(self, event: OrderBookSnapshot) -> DataValidationResult:
        """验证订单簿数据"""

# 1. 检查 bids 降序
        if len(event.bids) > 1:
            for i in range(len(event.bids) - 1):
                if event.bids[i][0] < event.bids[i+1][0]:
                    return DataValidationResult(
                        valid=False,
                        error=f"Bids not in descending order at index {i}"
                    )

# 2. 检查 asks 升序
        if len(event.asks) > 1:
            for i in range(len(event.asks) - 1):
                if event.asks[i][0] > event.asks[i+1][0]:
                    return DataValidationResult(
                        valid=False,
                        error=f"Asks not in ascending order at index {i}"
                    )

# 3. 检查价格合理性
        if event.bids and event.asks:
            if event.best_bid[0] >= event.best_ask[0]:
                return DataValidationResult(
                    valid=False,
                    error=f"Bid {event.best_bid[0]} >= Ask {event.best_ask[0]}"
                )

# 4. 检查数量为正
        for price, qty in event.bids + event.asks:
            if price <= 0 or qty <= 0:
                return DataValidationResult(
                    valid=False,
                    error=f"Invalid price/qty: {price}/{qty}"
                )

# 5. 时间戳检查
        if self._last_timestamp is not None:
            if event.timestamp < self._last_timestamp:

# 尝试修复
                fixed_event = OrderBookSnapshot(
                    timestamp=self._last_timestamp + 0.001,
                    symbol=event.symbol,
                    bids=event.bids,
                    asks=event.asks
                )
                return DataValidationResult(
                    valid=False,
                    error=f"Out-of-order timestamp",
                    fixed=True,
                    original_value=event,
                    fixed_value=fixed_event
                )

        self._last_timestamp = event.timestamp
        return DataValidationResult(valid=True)

    def load(self):
        """从 JSONL 文件加载订单簿数据"""
        import json

        if 'dataname' not in self.params:
            return

        with open(self.params['dataname']) as f:
            for line in f:
                data = json.loads(line)
                event = OrderBookSnapshot(
                    timestamp=float(data['timestamp']),
                    symbol=self.symbol,
                    bids=[(float(p), float(q)) for p, q in data['bids']],
                    asks=[(float(p), float(q)) for p, q in data['asks']]
                )
                yield event

```

- *测试**: `tests/phase1/test_orderbook_channel.py`

```python
def test_orderbook_validation():
    """测试订单簿验证"""
    channel = OrderBookChannel('BTC/USDT', validate=True)

# 正常订单簿
    ob = OrderBookSnapshot(
        timestamp=100.0,
        symbol='BTC/USDT',
        bids=[(50000, 1.0), (49999, 2.0)],
        asks=[(50001, 1.0), (50002, 2.0)]
    )
    channel.push(ob)
    assert len(channel._buffer) == 1

# 错误：bid >= ask
    bad_ob = OrderBookSnapshot(
        timestamp=101.0,
        symbol='BTC/USDT',
        bids=[(50002, 1.0)],
        asks=[(50001, 1.0)]
    )
    channel.push(bad_ob)
    assert len(channel._buffer) == 1  # 未添加
    assert len(channel._validation_errors) == 1

def test_orderbook_properties():
    """测试订单簿属性"""
    ob = OrderBookSnapshot(
        timestamp=100.0,
        symbol='BTC/USDT',
        bids=[(50000, 1.0), (49999, 2.0), (49998, 3.0)],
        asks=[(50001, 1.5), (50002, 2.5), (50003, 3.5)]
    )

    assert ob.best_bid == (50000, 1.0)
    assert ob.best_ask == (50001, 1.5)
    assert ob.spread == 1.0
    assert ob.mid_price == 50000.5
    assert ob.total_volume('bid', 3) == 6.0
    assert ob.total_volume('ask', 3) == 7.5

```

---
### 2.2 FundingRateChannel 实现（2 天）

- *文件**: `backtrader/channels/funding.py`

```python
from dataclasses import dataclass
from backtrader.channel import DataChannel, DataValidationResult

@dataclass
class FundingEvent:
    """资金费率事件"""
    timestamp: float
    symbol: str
    rate: float                    # 当前费率
    mark_price: float              # 标记价格
    next_funding_time: float       # 下次结算时间
    predicted_rate: float = 0.0    # 预测费率

class FundingRateChannel(DataChannel):
    """资金费率数据通道"""

    channel_type = 'funding_rate'

    def _validate_event(self, event: FundingEvent) -> DataValidationResult:
        """验证资金费率数据"""

# 1. 费率范围检查（通常在-0.75%到 0.75%之间）
        if abs(event.rate) > 0.0075:
            return DataValidationResult(
                valid=False,
                error=f"Funding rate {event.rate} out of range"
            )

# 2. 标记价格检查
        if event.mark_price <= 0:
            return DataValidationResult(
                valid=False,
                error=f"Invalid mark price: {event.mark_price}"
            )

# 3. 下次结算时间检查
        if event.next_funding_time <= event.timestamp:
            return DataValidationResult(
                valid=False,
                error=f"Next funding time in the past"
            )

# 4. 时间戳检查
        if self._last_timestamp is not None:
            if event.timestamp < self._last_timestamp:
                fixed_event = FundingEvent(
                    timestamp=self._last_timestamp + 0.001,
                    symbol=event.symbol,
                    rate=event.rate,
                    mark_price=event.mark_price,
                    next_funding_time=event.next_funding_time,
                    predicted_rate=event.predicted_rate
                )
                return DataValidationResult(
                    valid=False,
                    error=f"Out-of-order timestamp",
                    fixed=True,
                    original_value=event,
                    fixed_value=fixed_event
                )

        self._last_timestamp = event.timestamp
        return DataValidationResult(valid=True)

    def load(self):
        """从 CSV 加载资金费率数据"""
        import csv

        if 'dataname' not in self.params:
            return

        with open(self.params['dataname']) as f:
            reader = csv.DictReader(f)
            for row in reader:
                event = FundingEvent(
                    timestamp=float(row['timestamp']),
                    symbol=self.symbol,
                    rate=float(row['rate']),
                    mark_price=float(row['mark_price']),
                    next_funding_time=float(row['next_funding_time']),
                    predicted_rate=float(row.get('predicted_rate', 0.0))
                )
                yield event

```

---
### 2.3 Strategy 回调机制（4 天）

#### 2.3.1 Strategy 基类扩展

- *文件**: `backtrader/strategy.py`

```python
class StrategyBase(LineIterator):
    """扩展 Strategy 支持 Channel 回调"""

    def __init__(self):
        super().__init__()
        self._channels = {}  # {(channel_type, symbol): channel}
        self._bar_by_name = {}  # {data_name: data}

# === 新增 Channel 回调 ===

    def on_tick(self, channel, tick):
        """Tick 到达时调用

        Args:
            channel: TickChannel 实例
            tick: TickEvent 实例
        """
        pass

    def on_orderbook(self, channel, orderbook):
        """OrderBook 更新时调用

        Args:
            channel: OrderBookChannel 实例
            orderbook: OrderBookSnapshot 实例
        """
        pass

    def on_bar(self, data, bar):
        """Bar 到达时调用（TICK/MIXED 模式）

        Args:
            data: DataBase 实例
            bar: 当前 bar 数据

        注意：

        - 每个 bar_close 事件触发一次
        - 与 on_tick/on_orderbook 处于同一时间序列
        - next()在主时钟 bar_close 后触发

        """
        pass

    def on_funding(self, channel, funding):
        """FundingRate 更新时调用

        Args:
            channel: FundingRateChannel 实例
            funding: FundingEvent 实例
        """
        pass

    def on_channel(self, channel, event):
        """通用 Channel 回调（自定义类型）

        Args:
            channel: DataChannel 实例
            event: 自定义事件
        """
        pass

    def _dispatch_event(self, event):
        """分发事件到对应回调

        Args:
            event: Event 实例（来自 StreamingEventQueue）
        """
        channel = self._channels.get(
            (event.channel_type, event.channel_name)
        )

        if channel is None:
            return

# 根据 channel 类型调用对应回调
        if event.channel_type == 'tick':
            self.on_tick(channel, event.data)
        elif event.channel_type == 'orderbook':
            self.on_orderbook(channel, event.data)
        elif event.channel_type == 'funding_rate':
            self.on_funding(channel, event.data)
        else:
            self.on_channel(channel, event.data)

```

- *测试**: `tests/phase1/test_strategy_callbacks.py`

```python
class TestStrategy(bt.Strategy):
    def __init__(self):
        self.tick_count = 0
        self.ob_count = 0
        self.funding_count = 0
        self.bar_count = 0

    def on_tick(self, channel, tick):
        self.tick_count += 1

    def on_orderbook(self, channel, orderbook):
        self.ob_count += 1

    def on_funding(self, channel, funding):
        self.funding_count += 1

    def on_bar(self, data, bar):
        self.bar_count += 1

def test_strategy_callbacks():
    """测试策略回调触发"""
    cerebro = bt.Cerebro()

# 添加 Channels
    cerebro.add_channel(TickChannel, symbol='BTC/USDT', dataname='...')
    cerebro.add_channel(OrderBookChannel, symbol='BTC/USDT', dataname='...')
    cerebro.add_channel(FundingRateChannel, symbol='BTC/USDT', dataname='...')

# 添加策略
    cerebro.addstrategy(TestStrategy)

# 运行
    results = cerebro.run(mode=bt.RunMode.TICK)
    strat = results[0]

# 验证回调被触发
    assert strat.tick_count > 0
    assert strat.ob_count > 0
    assert strat.funding_count > 0

```

---
### 2.4 优先级通知队列（3 天）

- *文件**: `backtrader/cerebro.py`

```python
from enum import IntEnum
from dataclasses import dataclass, field
import heapq

class NotificationPriority(IntEnum):
    """通知优先级"""
    REJECTED = 10      # 拒单最先
    CANCELLED = 20     # 撤单
    MARGIN_CALL = 30   # 保证金不足
    PARTIAL = 40       # 部分成交
    COMPLETED = 50     # 完全成交
    SUBMITTED = 60     # 已提交

@dataclass(order=True)
class Notification:
    """优先级通知"""
    priority: int
    sequence: int = field(compare=False)
    order: Any = field(compare=False)
    timestamp: float = field(compare=False)

class Cerebro:
    """增加优先级通知队列"""

    def __init__(self, *args, **kwargs):

# ... 现有初始化 ...
        self._notification_queue = []
        self._notification_sequence = 0

    def _get_notification_priority(self, order) -> int:
        """确定通知优先级"""
        if order.status == Order.Rejected:
            return NotificationPriority.REJECTED
        elif order.status == Order.Cancelled:
            return NotificationPriority.CANCELLED
        elif order.status == Order.Margin:
            return NotificationPriority.MARGIN_CALL
        elif order.status == Order.Partial:
            return NotificationPriority.PARTIAL
        elif order.status == Order.Completed:
            return NotificationPriority.COMPLETED
        else:
            return NotificationPriority.SUBMITTED

    def _deliver_notifications(self, runstrats):
        """按优先级分发通知"""
        notifications = []

# 收集所有通知
        while True:
            order = self._broker.get_notification()
            if order is None:
                break

            priority = self._get_notification_priority(order)

            heapq.heappush(notifications, Notification(
                priority=priority,
                sequence=self._notification_sequence,
                order=order,
                timestamp=self._current_timestamp
            ))
            self._notification_sequence += 1

# 按优先级排序分发
        while notifications:
            notif = heapq.heappop(notifications)
            owner = notif.order.owner or runstrats[0]
            owner._addnotification(notif.order, quicknotify=True)

```

- *测试**: `tests/phase1/test_notification_priority.py`

```python
def test_notification_priority_order():
    """测试通知优先级顺序"""

    class PriorityTestStrategy(bt.Strategy):
        def __init__(self):
            self.notifications = []

        def notify_order(self, order):
            self.notifications.append({
                'status': order.status,
                'ref': order.ref
            })

    cerebro = bt.Cerebro()

# ... 设置导致多种订单状态的场景 ...

    results = cerebro.run()
    strat = results[0]

# 验证通知顺序：拒单 -> 撤单 -> 保证金 -> 部分成交 -> 完全成交

# ...

```

---
### 2.5 Channel 共享模式（4 天）

- *文件**: `backtrader/channel.py`

```python
from enum import Enum

class ChannelSharingMode(Enum):
    """Channel 共享模式"""
    EXCLUSIVE = 'exclusive'          # 每个策略独立 Channel
    SHARED_READONLY = 'shared_ro'    # 共享只读 Channel
    SHARED_ISOLATED = 'shared_isolated'  # 共享数据，隔离状态
    SHARED_FULL = 'shared_full'      # 完全共享（含状态）

class DataChannel:
    """增强的 Channel 基类"""

    def __init__(self, symbol, sharing_mode=ChannelSharingMode.SHARED_READONLY, **kwargs):
        self.symbol = symbol
        self.sharing_mode = sharing_mode
        self._buffer = deque(maxlen=kwargs.get('maxlen', 10000))
        self._event_count = 0

# 策略隔离状态
        self._strategy_states = {}  # {strategy_id: state_dict}

    def get_state(self, strategy_id):
        """获取策略专属状态"""
        if self.sharing_mode == ChannelSharingMode.SHARED_ISOLATED:
            if strategy_id not in self._strategy_states:
                self._strategy_states[strategy_id] = {}
            return self._strategy_states[strategy_id]
        else:
            return {}

    def push(self, event):
        """推送事件 - 只读模式检查"""
        if self.sharing_mode == ChannelSharingMode.SHARED_READONLY:

# 只读模式：只能读取，不能修改
            raise RuntimeError("Cannot push to read-only shared channel")

# ... 验证和添加逻辑 ...

```

- *文件**: `backtrader/cerebro.py`

```python
class Cerebro:
    """优化的 Channel 初始化"""

    def add_channel(self, channel_cls, symbol=None,
                   sharing_mode=ChannelSharingMode.SHARED_READONLY, **kwargs):
        """注册数据通道 - 支持共享模式"""
        self._channels.append((channel_cls, symbol, kwargs, sharing_mode))
        return self

    def _init_channels(self, runstrats):
        """根据共享模式初始化 Channel"""
        for ch_cls, symbol, kwargs, mode in self._channels:
            if symbol is None and self.datas:
                symbol = getattr(self.datas[0], '_name', 'default')

            if mode == ChannelSharingMode.EXCLUSIVE:

# 每个策略独立实例
                for strat in runstrats:
                    ch = ch_cls(symbol=symbol, sharing_mode=mode, **kwargs)
                    self._register_channel_to_strategy(strat, ch)

            elif mode in (ChannelSharingMode.SHARED_READONLY,
                         ChannelSharingMode.SHARED_ISOLATED):

# 共享数据，隔离状态
                ch = ch_cls(symbol=symbol, sharing_mode=mode, **kwargs)
                for strat in runstrats:
                    self._register_channel_to_strategy(strat, ch)

            elif mode == ChannelSharingMode.SHARED_FULL:

# 完全共享（含状态）
                ch = ch_cls(symbol=symbol, sharing_mode=mode, **kwargs)
                for strat in runstrats:
                    self._register_channel_to_strategy(strat, ch)

    def _register_channel_to_strategy(self, strat, channel):
        """注册 Channel 到策略"""
        if not hasattr(strat, '_channels'):
            strat._channels = {}
        strat._channels[(channel.channel_type, channel.symbol)] = channel

```

- *测试**: `tests/phase1/test_channel_sharing.py`

```python
def test_exclusive_mode():
    """测试独占模式"""
    cerebro = bt.Cerebro()
    cerebro.add_channel(
        TickChannel,
        symbol='BTC/USDT',
        sharing_mode=ChannelSharingMode.EXCLUSIVE,
        dataname='...'
    )

    cerebro.addstrategy(Strategy1)
    cerebro.addstrategy(Strategy2)

    results = cerebro.run()

# 验证每个策略有独立的 Channel 实例
    ch1 = results[0]._channels[('tick', 'BTC/USDT')]
    ch2 = results[1]._channels[('tick', 'BTC/USDT')]
    assert ch1 is not ch2

def test_shared_isolated_mode():
    """测试共享隔离模式"""

# ... 验证共享数据但状态隔离 ...

```

---
### 2.6 Cerebro 集成（5 天）

- *文件**: `backtrader/cerebro.py`

```python
class Cerebro:
    """完整的 Cerebro 集成"""

    def __init__(self, **kwargs):

# ... 现有初始化 ...
        self._channels = []           # [(cls, symbol, kwargs, sharing_mode)]
        self._channel_instances = {}  # {(type, symbol): channel}
        self._event_queue = None
        self._run_mode = None

    def add_channel(self, channel_cls, symbol=None,
                   sharing_mode=ChannelSharingMode.SHARED_READONLY, **kwargs):
        """注册数据通道"""
        self._channels.append((channel_cls, symbol, kwargs, sharing_mode))
        return self

    def run(self, mode=None, **kwargs):
        """运行回测 - 支持模式选择"""

# ... 现有逻辑 ...

# 模式推断
        if mode is None:
            self._run_mode = self._infer_run_mode()
        else:
            self._run_mode = mode

# 初始化 Channels
        self._init_channels(runstrats)

# 根据模式运行
        if self._run_mode == RunMode.BAR:
            return self._run_bar_mode(runstrats)
        elif self._run_mode == RunMode.TICK:
            return self._run_tick_mode(runstrats)
        elif self._run_mode == RunMode.MIXED:
            return self._run_mixed_mode(runstrats)

    def _infer_run_mode(self):
        """推断运行模式"""
        if not self._channels:
            return RunMode.BAR

# 如果有 Channel 但也有 datas，默认 MIXED
        if self.datas:
            return RunMode.MIXED

# 只有 Channel，无 datas，使用 TICK
        return RunMode.TICK

    def _init_event_queue(self, runstrats):
        """初始化事件队列"""

# 收集所有 Channel 实例
        all_channels = []
        for strat in runstrats:
            if hasattr(strat, '_channels'):
                all_channels.extend(strat._channels.values())

# 去重
        unique_channels = list(set(all_channels))

        self._event_queue = StreamingEventQueue(
            channels=unique_channels,
            bars=self.datas,
            preload_window=self.p.get('preload_window', 300.0),
            max_memory_mb=self.p.get('max_memory_mb', 200),
            adaptive=self.p.get('adaptive_window', True)
        )

# bar 名称映射
        self._bar_by_name = {
            getattr(d, '_name', f'data{i}'): d
            for i, d in enumerate(self.datas)
        }
        for strat in runstrats:
            strat._bar_by_name = self._bar_by_name

```

---
## 3. 交付物

### 3.1 代码

- [ ] `backtrader/channels/orderbook.py` - OrderBookChannel
- [ ] `backtrader/channels/funding.py` - FundingRateChannel
- [ ] `backtrader/strategy.py` - Strategy 回调扩展
- [ ] `backtrader/cerebro.py` - 优先级通知 + Channel 集成
- [ ] `backtrader/channel.py` - Channel 共享模式

### 3.2 测试

- [ ] `tests/phase1/test_orderbook_channel.py`
- [ ] `tests/phase1/test_funding_channel.py`
- [ ] `tests/phase1/test_strategy_callbacks.py`
- [ ] `tests/phase1/test_notification_priority.py`
- [ ] `tests/phase1/test_channel_sharing.py`
- [ ] `tests/phase1/test_cerebro_integration.py`

### 3.3 文档

- [ ] Phase 1 完成报告
- [ ] API 文档更新
- [ ] 使用示例

---
## 4. 验收标准

### 4.1 功能验收

- [ ] OrderBookChannel 正确加载和验证数据
- [ ] FundingRateChannel 正确加载和验证数据
- [ ] Strategy 回调正确触发
- [ ] 通知按优先级排序
- [ ] 4 种共享模式正常工作

### 4.2 集成验收

- [ ] 多 Channel 协作正常
- [ ] 事件顺序正确
- [ ] 通知机制无遗漏

### 4.3 回归验收

- [ ] 1020 个现有测试全部通过
- [ ] 向后兼容性 100%

---
## 5. 时间表

| 任务 | 工作量 | 开始 | 结束 |

|------|--------|------|------|

| OrderBookChannel | 3 天 | Day 1 | Day 3 |

| FundingRateChannel | 2 天 | Day 4 | Day 5 |

| Strategy 回调机制 | 4 天 | Day 6 | Day 9 |

| 优先级通知队列 | 3 天 | Day 10 | Day 12 |

| Channel 共享模式 | 4 天 | Day 13 | Day 16 |

| Cerebro 集成 | 5 天 | Day 17 | Day 21 |

---
## 6. 风险与应对

| 风险 | 概率 | 影响 | 应对措施 |

|------|------|------|---------|

| 回调机制复杂 | 中 | 中 | 详细设计+单元测试 |

| 共享模式 bug | 中 | 中 | 完善测试用例 |

| 回归问题 | 低 | 高 | 持续回归测试 |

---
## 7. 下一步

Phase 1 完成后，进入 Phase 2：回测引擎与 Broker 实现。
