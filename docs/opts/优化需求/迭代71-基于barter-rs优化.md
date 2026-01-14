### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/barter-rs
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### barter-rs项目简介
barter-rs是一个Rust实现的量化交易框架，具有以下核心特点：
- **Rust实现**: 高性能、内存安全的Rust语言
- **异步架构**: 基于tokio的异步架构
- **模块化**: 高度模块化的设计
- **实时交易**: 支持实时交易和回测
- **WebSocket**: 原生WebSocket支持
- **类型安全**: 强类型系统保证安全

### 重点借鉴方向
1. **高性能**: Rust带来的性能优势
2. **异步模式**: 异步事件处理模式
3. **类型系统**: 强类型的数据结构设计
4. **模块解耦**: 模块间的松耦合设计
5. **执行引擎**: ExecutionEngine设计
6. **数据规范**: 数据格式规范化

---

## 架构对比分析

### Backtrader 核心特点

**优势:**
1. **成熟的Line系统**: 基于循环缓冲区的高效时间序列数据管理
2. **完整的回测引擎**: Cerebro统一管理策略、数据、经纪商、分析器
3. **丰富的技术指标**: 60+内置技术指标
4. **性能优化**: 支持向量化(once模式)和事件驱动(next模式)双执行模式
5. **Cython加速**: 关键路径使用Cython优化
6. **多市场支持**: 支持股票、期货、加密货币等多种市场
7. **Python优先**: 纯Python实现，易于扩展和定制

**局限:**
1. **动态类型**: Python动态类型系统导致运行时错误
2. **状态管理**: 缺少系统化的状态管理机制
3. **审计追踪**: 缺少完整的审计日志系统
4. **模块耦合**: 各模块间耦合度较高
5. **性能瓶颈**: Python解释器带来的性能限制
6. **并发支持**: 多线程/异步支持有限

### Barter-rs 核心特点

**优势:**
1. **类型安全**: Rust强类型系统编译期检查
2. **高性能**: 零成本抽象、无GC
3. **异步架构**: 基于Tokio的真正异步
4. **状态管理**: 索引化O(1)状态查询
5. **审计系统**: 完整的审计流和状态复制
6. **模块化**: Crate级别的模块解耦
7. **trait系统**: 灵活的策略trait定义
8. **多交易所**: 统一的交易所抽象

**局限:**
1. **学习曲线**: Rust语言学习曲线陡峭
2. **生态较小**: 相比Python生态不够成熟
3. **开发效率**: 编译时间长，开发速度较慢
4. **动态性差**: 缺少Python的动态灵活性

---

## 需求规格文档

### 1. 索引化状态管理 (优先级: 高)

**需求描述:**
实现基于索引的状态管理系统，支持O(1)时间复杂度的状态查询。

**功能需求:**
1. **ExchangeIndex**: 交易所索引系统
2. **InstrumentIndex**: 交易品种索引系统
3. **AssetIndex**: 资产索引系统
4. **层次化状态**: 全局/资产/品种/订单状态层次
5. **快照支持**: 状态快照和回放

**非功能需求:**
1. O(1)查询时间复杂度
2. 支持状态复制和监控
3. 线程安全

### 2. 审计流系统 (优先级: 高)

**需求描述:**
引入完整的审计日志系统，支持状态复制和外部监控。

**功能需求:**
1. **事件审计**: 记录所有引擎事件
2. **状态复制**: 支持状态副本同步
3. **序列号**: 事件序列化和顺序保证
4. **外部监控**: 支持UI连接监听
5. **审计流查询**: 历史审计数据查询

**非功能需求:**
1. 不影响主流程性能
2. 支持持久化存储

### 3. 策略Trait系统 (优先级: 中)

**需求描述:**
实现灵活的策略trait系统，支持多种策略类型的组合。

**功能需求:**
1. **AlgoStrategy**: 算法订单生成
2. **ClosePositionsStrategy**: 平仓策略
3. **OnDisconnectStrategy**: 断线处理
4. **OnTradingDisabled**: 交易禁用处理
5. **策略组合**: 多trait组合实现

**非功能需求:**
1. 保持现有Strategy API兼容
2. 支持渐进式迁移

### 4. 多层风险管理 (优先级: 中)

**需求描述:**
实现独立的风险管理层，支持订单前风险检查。

**功能需求:**
1. **RiskManager trait**: 风险管理器接口
2. **订单检查**: 订单前风险验证
3. **风险批准/拒绝**: 类型化的风险决策
4. **风险原因**: 拒绝原因记录
5. **风险工具**: 常用风险计算工具

**非功能需求:**
1. 不影响正常订单执行速度
2. 灵活的风险规则配置

### 5. 订单状态追踪 (优先级: 中)

**需求描述:**
实现完整的订单状态追踪系统。

**功能需求:**
1. **订单状态**: OpenInFlight/Open/Cancelled等
2. **状态转换**: 明确的状态转换规则
3. **在途请求**: 记录已发送未响应的请求
4. **订单快照**: 交易所订单快照更新
5. **取消响应**: 取消订单响应处理

### 6. 执行管理器 (优先级: 低)

**需求描述:**
实现独立的执行管理器，处理订单路由和响应。

**功能需求:**
1. **请求路由**: 索引到交易所名称的转换
2. **超时处理**: 请求超时管理
3. **响应处理**: 统一的响应处理
4. **连接管理**: 交易所连接管理
5. **事件索引**: 账户事件索引

---

## 设计文档

### 1. 索引化状态管理设计

#### 1.1 索引系统

```python
# backtrader/index/base.py
from typing import NewType, Dict, Set
from dataclasses import dataclass

# 类型安全的索引定义
ExchangeIndex = NewType('ExchangeIndex', int)
InstrumentIndex = NewType('InstrumentIndex', int)
AssetIndex = NewType('AssetIndex', int)
OrderIndex = NewType('OrderIndex', int)

@dataclass
class ExchangeKey:
    """交易所键"""
    index: ExchangeIndex
    name: str

@dataclass
class InstrumentKey:
    """品种键"""
    exchange_index: ExchangeIndex
    asset_index: AssetIndex
    instrument_index: InstrumentIndex
    name: str

@dataclass
class AssetKey:
    """资产键"""
    exchange_index: ExchangeIndex
    asset_index: AssetIndex
    symbol: str


class Indexer:
    """
    索引器

    管理交易所、品种、资产的索引映射
    """

    def __init__(self):
        self._exchanges: Dict[str, ExchangeIndex] = {}
        self._exchange_names: Dict[ExchangeIndex, str] = {}
        self._next_exchange_idx: ExchangeIndex = ExchangeIndex(0)

        self._assets: Dict[ExchangeIndex, Dict[str, AssetIndex]] = {}
        self._asset_names: Dict[AssetIndex, str] = {}
        self._next_asset_idx: AssetIndex = AssetIndex(0)

        self._instruments: Dict[InstrumentKey, InstrumentIndex] = {}
        self._instrument_keys: Dict[InstrumentIndex, InstrumentKey] = {}
        self._next_instrument_idx: InstrumentIndex = InstrumentIndex(0)

    def get_or_create_exchange(self, name: str) -> ExchangeIndex:
        """获取或创建交易所索引"""
        if name not in self._exchanges:
            idx = self._next_exchange_idx
            self._exchanges[name] = idx
            self._exchange_names[idx] = name
            self._next_exchange_idx = ExchangeIndex(idx + 1)
        return self._exchanges[name]

    def get_exchange_index(self, name: str) -> ExchangeIndex:
        """获取交易所索引"""
        return self._exchanges.get(name)

    def get_exchange_name(self, index: ExchangeIndex) -> str:
        """获取交易所名称"""
        return self._exchange_names.get(index, "")

    def get_or_create_asset(self, exchange_idx: ExchangeIndex, symbol: str) -> AssetIndex:
        """获取或创建资产索引"""
        if exchange_idx not in self._assets:
            self._assets[exchange_idx] = {}

        assets = self._assets[exchange_idx]
        if symbol not in assets:
            idx = self._next_asset_idx
            assets[symbol] = idx
            self._asset_names[idx] = f"{self.get_exchange_name(exchange_idx)}/{symbol}"
            self._next_asset_idx = AssetIndex(idx + 1)
        return assets[symbol]

    def get_or_create_instrument(self, exchange_idx: ExchangeIndex,
                                  asset_idx: AssetIndex, name: str) -> InstrumentIndex:
        """获取或创建品种索引"""
        key = InstrumentKey(exchange_idx, asset_idx, 0, name)
        if key not in self._instruments:
            idx = self._next_instrument_idx
            key.instrument_index = idx
            self._instruments[key] = idx
            self._instrument_keys[idx] = key
            self._next_instrument_idx = InstrumentIndex(idx + 1)
        return self._instruments[key]

    def get_instrument_key(self, index: InstrumentIndex) -> InstrumentKey:
        """获取品种键"""
        return self._instrument_keys.get(index)
```

#### 1.2 层次化状态管理

```python
# backtrader/state/engine_state.py
from typing import Dict, Optional, List
from datetime import datetime
from decimal import Decimal
from dataclasses import dataclass, field

@dataclass
class InstrumentState:
    """品种状态"""
    instrument_index: InstrumentIndex
    last_update: datetime = None
    last_price: Decimal = Decimal(0)
    bid_price: Decimal = Decimal(0)
    ask_price: Decimal = Decimal(0)
    volume_24h: Decimal = Decimal(0)

@dataclass
class AssetState:
    """资产状态"""
    asset_index: AssetIndex
    balance_available: Decimal = Decimal(0)
    balance_total: Decimal = Decimal(0)
    equity: Decimal = Decimal(0)

@dataclass
class PositionState:
    """持仓状态"""
    instrument_index: InstrumentIndex
    side: str  # "long" or "short"
    size: Decimal = Decimal(0)
    entry_price: Decimal = Decimal(0)
    unrealized_pnl: Decimal = Decimal(0)
    realized_pnl: Decimal = Decimal(0)

@dataclass
class OrderState:
    """订单状态"""
    order_index: OrderIndex
    instrument_index: InstrumentIndex
    client_order_id: str
    side: str
    price: Decimal
    quantity: Decimal
    filled_quantity: Decimal = Decimal(0)
    status: str = "pending"  # pending, open, partial_filled, filled, cancelled, rejected
    created_at: datetime = None
    updated_at: datetime = None

@dataclass
class EngineState:
    """
    引擎状态

    使用索引实现O(1)查询
    """

    # 全局状态
    sequence: int = 0
    trading_enabled: bool = True
    last_update: datetime = None

    # 索引引用
    indexer: 'Indexer' = field(default_factory=Indexer)

    # 状态存储 (使用字典实现O(1)查找)
    instrument_states: Dict[InstrumentIndex, InstrumentState] = field(default_factory=dict)
    asset_states: Dict[AssetIndex, AssetState] = field(default_factory=dict)
    position_states: Dict[InstrumentIndex, PositionState] = field(default_factory=dict)
    order_states: Dict[OrderIndex, OrderState] = field(default_factory=dict)

    # 反向索引 (按交易所/资产查找)
    exchange_instruments: Dict[ExchangeIndex, Set[InstrumentIndex]] = field(default_factory=lambda: {})
    exchange_assets: Dict[ExchangeIndex, Set[AssetIndex]] = field(default_factory=lambda: {})

    def get_instrument_state(self, index: InstrumentIndex) -> Optional[InstrumentState]:
        """O(1)获取品种状态"""
        return self.instrument_states.get(index)

    def get_asset_state(self, index: AssetIndex) -> Optional[AssetState]:
        """O(1)获取资产状态"""
        return self.asset_states.get(index)

    def get_position_state(self, index: InstrumentIndex) -> Optional[PositionState]:
        """O(1)获取持仓状态"""
        return self.position_states.get(index)

    def get_order_state(self, index: OrderIndex) -> Optional[OrderState]:
        """O(1)获取订单状态"""
        return self.order_states.get(index)

    def update_instrument_state(self, index: InstrumentIndex,
                                price: Decimal = None,
                                bid: Decimal = None,
                                ask: Decimal = None) -> 'EngineState':
        """不可变更新，返回新状态"""
        new_state = self._copy()
        state = new_state.instrument_states.get(index)

        if state is None:
            state = InstrumentState(instrument_index=index)
            new_state.instrument_states[index] = state

        if price is not None:
            state.last_price = price
        if bid is not None:
            state.bid_price = bid
        if ask is not None:
            state.ask_price = ask

        state.last_update = datetime.now()
        new_state.sequence += 1
        return new_state

    def snapshot(self) -> dict:
        """创建状态快照"""
        return {
            'sequence': self.sequence,
            'trading_enabled': self.trading_enabled,
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'instruments': {
                idx.__str__(): {
                    'last_price': str(state.last_price),
                    'bid_price': str(state.bid_price),
                    'ask_price': str(state.ask_price),
                }
                for idx, state in self.instrument_states.items()
            },
            'assets': {
                idx.__str__(): {
                    'balance_available': str(state.balance_available),
                    'balance_total': str(state.balance_total),
                }
                for idx, state in self.asset_states.items()
            },
            'positions': {
                idx.__str__(): {
                    'side': state.side,
                    'size': str(state.size),
                    'entry_price': str(state.entry_price),
                    'unrealized_pnl': str(state.unrealized_pnl),
                }
                for idx, state in self.position_states.items()
            }
        }

    def _copy(self) -> 'EngineState':
        """创建状态的浅拷贝"""
        import copy
        new_state = copy.copy(self)
        new_state.instrument_states = self.instrument_states.copy()
        new_state.asset_states = self.asset_states.copy()
        new_state.position_states = self.position_states.copy()
        new_state.order_states = self.order_states.copy()
        return new_state
```

### 2. 审计流系统设计

```python
# backtrader/audit/audit_stream.py
from typing import Callable, Optional, AsyncIterator
from datetime import datetime
from enum import Enum
import asyncio

class AuditEventType(Enum):
    """审计事件类型"""
    MARKET_EVENT = "market_event"
    ACCOUNT_EVENT = "account_event"
    ORDER_REQUESTED = "order_requested"
    ORDER_APPROVED = "order_approved"
    ORDER_REFUSED = "order_refused"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    TRADING_STATE_CHANGED = "trading_state_changed"
    ERROR = "error"
    SHUTDOWN = "shutdown"

@dataclass
class AuditEvent:
    """审计事件"""
    sequence: int
    event_type: AuditEventType
    timestamp: datetime
    data: dict = None
    exchange: Optional[str] = None
    instrument: Optional[str] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'sequence': self.sequence,
            'type': self.event_type.value,
            'timestamp': self.timestamp.isoformat(),
            'exchange': self.exchange,
            'instrument': self.instrument,
            'data': self.data
        }

class AuditStream:
    """
    审计流

    记录所有引擎事件，支持外部监听和状态复制
    """

    def __init__(self):
        self._sequence = 0
        self._subscribers: List[Callable[[AuditEvent], None]] = []
        self._async_subscribers: List[Callable[[AuditEvent], asyncio.Task]] = []
        self._history: List[AuditEvent] = []
        self._max_history = 10000

    def subscribe(self, callback: Callable[[AuditEvent], None]) -> None:
        """订阅审计事件"""
        self._subscribers.append(callback)

    def subscribe_async(self, callback: Callable[[AuditEvent], asyncio.Task]) -> None:
        """订阅异步审计事件"""
        self._async_subscribers.append(callback)

    def emit(self, event_type: AuditEventType, data: dict = None,
             exchange: str = None, instrument: str = None) -> AuditEvent:
        """发送审计事件"""
        event = AuditEvent(
            sequence=self._sequence,
            event_type=event_type,
            timestamp=datetime.now(),
            data=data,
            exchange=exchange,
            instrument=instrument
        )

        # 保存历史
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        # 通知同步订阅者
        for callback in self._subscribers:
            try:
                callback(event)
            except Exception:
                pass  # 订阅者错误不影响主流程

        # 通知异步订阅者
        for callback in self._async_subscribers:
            try:
                asyncio.create_task(callback(event))
            except Exception:
                pass

        self._sequence += 1
        return event

    def get_history(self, since_sequence: int = 0,
                    event_type: AuditEventType = None) -> List[AuditEvent]:
        """获取历史事件"""
        events = [e for e in self._history if e.sequence >= since_sequence]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events

    def get_iterator(self) -> AsyncIterator[AuditEvent]:
        """获取异步迭代器"""
        async def iterator():
            last_seq = self._sequence
            while True:
                events = self.get_history(last_seq)
                for event in events:
                    yield event
                    last_seq = event.sequence + 1
                await asyncio.sleep(0.1)
        return iterator()

    def clear(self) -> None:
        """清空历史"""
        self._history.clear()
```

### 3. 策略Trait系统设计

```python
# backtrader/strategy/traits.py
from abc import ABC, abstractmethod
from typing import Tuple, Iterable, List
from dataclasses import dataclass

@dataclass
class OrderRequestCancel:
    """取消订单请求"""
    instrument_index: InstrumentIndex
    client_order_id: str
    order_id: str = None

@dataclass
class OrderRequestOpen:
    """开仓订单请求"""
    instrument_index: InstrumentIndex
    side: str  # "buy" or "sell"
    price: Decimal
    quantity: Decimal
    order_type: str = "limit"  # market, limit
    time_in_force: str = "GTC"  # GTC, IOC, FOK

class AlgoStrategy(ABC):
    """
    算法策略trait

    定义生成算法订单的接口
    """

    @abstractmethod
    def generate_algo_orders(self, state: EngineState) -> Tuple[
        Iterable[OrderRequestCancel],
        Iterable[OrderRequestOpen]
    ]:
        """
        生成算法订单

        Args:
            state: 当前引擎状态

        Returns:
            (取消订单列表, 开仓订单列表)
        """
        pass

class ClosePositionsStrategy(ABC):
    """
    平仓策略trait

    定义平仓逻辑
    """

    @abstractmethod
    def close_positions_requests(self, state: EngineState,
                                  instruments: List[InstrumentIndex]) -> Tuple[
        Iterable[OrderRequestCancel],
        Iterable[OrderRequestOpen]
    ]:
        """
        生成平仓订单

        Args:
            state: 当前引擎状态
            instruments: 需要平仓的品种列表

        Returns:
            (取消订单列表, 平仓订单列表)
        """
        pass

class OnDisconnectStrategy(ABC):
    """
    断线处理trait

    定义交易所断线时的处理逻辑
    """

    @abstractmethod
    def on_disconnect(self, engine: 'Engine', exchange_index: ExchangeIndex):
        """
        处理交易所断线

        Args:
            engine: 引擎引用
            exchange_index: 断线的交易所索引
        """
        pass

class OnTradingDisabledStrategy(ABC):
    """
    交易禁用处理trait

    定义交易被禁用时的处理逻辑
    """

    @abstractmethod
    def on_trading_disabled(self, engine: 'Engine'):
        """
        处理交易禁用

        Args:
            engine: 引擎引用
        """
        pass

# 组合策略示例
class MyStrategy(AlgoStrategy, ClosePositionsStrategy, OnDisconnectStrategy):
    """
    组合多个trait的策略
    """

    def generate_algo_orders(self, state: EngineState):
        cancels = []
        opens = []

        # 策略逻辑...
        # 生成订单

        return cancels, opens

    def close_positions_requests(self, state: EngineState, instruments):
        cancels = []
        opens = []

        for inst_idx in instruments:
            pos = state.get_position_state(inst_idx)
            if pos and pos.size != 0:
                # 生成平仓订单
                opens.append(OrderRequestOpen(
                    instrument_index=inst_idx,
                    side="sell" if pos.side == "long" else "buy",
                    price=state.get_instrument_state(inst_idx).last_price,
                    quantity=abs(pos.size)
                ))

        return cancels, opens

    def on_disconnect(self, engine, exchange_index):
        # 取消该交易所的所有订单
        for order in list(engine.state.order_states.values()):
            if order.instrument_index in engine.state.exchange_instruments[exchange_index]:
                engine.cancel_order(order.order_index)
```

### 4. 风险管理系统设计

```python
# backtrader/risk/risk_manager.py
from dataclasses import dataclass
from typing import Tuple, Iterable
from decimal import Decimal

@dataclass
class RiskApproved:
    """风险批准的订单"""
    request: OrderRequestOpen

@dataclass
class RiskRefused:
    """风险拒绝的订单"""
    request: OrderRequestOpen
    reason: str

class RiskManager(ABC):
    """
    风险管理器trait

    定义订单风险检查接口
    """

    @abstractmethod
    def check(self, state: EngineState,
              cancels: Iterable[OrderRequestCancel],
              opens: Iterable[OrderRequestOpen]) -> Tuple[
        Iterable[RiskApproved],
        Iterable[RiskApproved],
        Iterable[RiskRefused],
        Iterable[RiskRefused]
    ]:
        """
        风险检查

        Args:
            state: 当前引擎状态
            cancels: 取消订单列表
            opens: 开仓订单列表

        Returns:
            (批准的取消, 批准的开仓, 拒绝的取消, 拒绝的开仓)
        """
        pass

# 示例风险管理器
class DefaultRiskManager(RiskManager):
    """默认风险管理器"""

    def __init__(self,
                 max_position_value: Decimal = Decimal(10000),
                 max_order_value: Decimal = Decimal(1000),
                 max_orders_per_instrument: int = 10):
        self.max_position_value = max_position_value
        self.max_order_value = max_order_value
        self.max_orders_per_instrument = max_orders_per_instrument

    def check(self, state: EngineState,
              cancels: Iterable[OrderRequestCancel],
              opens: Iterable[OrderRequestOpen]) -> Tuple:
        approved_cancels = [RiskApproved(c) for c in cancels]
        approved_opens = []
        refused_opens = []

        # 统计每个品种的活动订单数
        order_counts = {}
        for order_state in state.order_states.values():
            if order_state.status in ('pending', 'open', 'partial_filled'):
                inst = order_state.instrument_index
                order_counts[inst] = order_counts.get(inst, 0) + 1

        for open_req in opens:
            inst_state = state.get_instrument_state(open_req.instrument_index)
            if not inst_state:
                refused_opens.append(RiskRefused(open_req, "品种不存在"))
                continue

            # 检查订单价值
            order_value = open_req.price * open_req.quantity
            if order_value > self.max_order_value:
                refused_opens.append(RiskRefused(
                    open_req,
                    f"订单价值超限: {order_value} > {self.max_order_value}"
                ))
                continue

            # 检查持仓价值
            pos_state = state.get_position_state(open_req.instrument_index)
            current_value = Decimal(0)
            if pos_state:
                current_value = abs(pos_state.size) * inst_state.last_price

            new_value = current_value + order_value
            if new_value > self.max_position_value:
                refused_opens.append(RiskRefused(
                    open_req,
                    f"持仓价值超限: {new_value} > {self.max_position_value}"
                ))
                continue

            # 检查订单数量
            count = order_counts.get(open_req.instrument_index, 0)
            if count >= self.max_orders_per_instrument:
                refused_opens.append(RiskRefused(
                    open_req,
                    f"订单数量超限: {count} >= {self.max_orders_per_instrument}"
                ))
                continue

            approved_opens.append(RiskApproved(open_req))

        return approved_cancels, approved_opens, [], refused_opens

# 风险计算工具
class RiskCalculators:
    """风险计算工具类"""

    @staticmethod
    def calculate_notional(quantity: Decimal, price: Decimal) -> Decimal:
        """计算名义价值"""
        return quantity * price

    @staticmethod
    def calculate_percent_diff(value1: Decimal, value2: Decimal) -> Decimal:
        """计算百分比差异"""
        if value2 == 0:
            return Decimal(0)
        return abs((value1 - value2) / value2)

    @staticmethod
    def calculate_position_delta(current_pos: Decimal, order_qty: Decimal) -> Decimal:
        """计算持仓变化"""
        return current_pos + order_qty
```

### 5. 订单状态追踪设计

```python
# backtrader/order/order_tracker.py
from enum import Enum
from typing import Dict, Optional, Set
from dataclasses import dataclass

class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"           # 待发送
    OPEN_IN_FLIGHT = "open_in_flight"  # 已发送待确认
    OPEN = "open"                 # 已确认
    PARTIALLY_FILLED = "partially_filled"  # 部分成交
    FILLED = "filled"             # 完全成交
    CANCEL_IN_FLIGHT = "cancel_in_flight"  # 取消中
    CANCELLED = "cancelled"       # 已取消
    EXPIRED = "expired"           # 已过期
    REJECTED = "rejected"         # 已拒绝
    FAILED = "failed"             # 失败

@dataclass
class TrackedOrder:
    """被追踪的订单"""
    order_index: OrderIndex
    instrument_index: InstrumentIndex
    client_order_id: str
    exchange_order_id: Optional[str] = None
    side: str = "buy"
    price: Decimal = Decimal(0)
    quantity: Decimal = Decimal(0)
    filled_quantity: Decimal = Decimal(0)
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = None
    updated_at: datetime = None

    @property
    def is_active(self) -> bool:
        """是否活动"""
        return self.status in (
            OrderStatus.OPEN_IN_FLIGHT,
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED
        )

    @property
    def is_terminal(self) -> bool:
        """是否终态"""
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED
        )

    @property
    def remaining_quantity(self) -> Decimal:
        """剩余数量"""
        return self.quantity - self.filled_quantity

class OrderTracker:
    """
    订单追踪器

    管理订单生命周期和在途请求
    """

    def __init__(self):
        self._orders: Dict[OrderIndex, TrackedOrder] = {}
        self._client_order_ids: Dict[str, OrderIndex] = {}
        self._exchange_order_ids: Dict[str, OrderIndex] = {}
        self._in_flight_opens: Set[OrderIndex] = set()
        self._in_flight_cancels: Set[OrderIndex] = set()

    def add_order(self, order: TrackedOrder) -> None:
        """添加订单"""
        self._orders[order.order_index] = order
        self._client_order_ids[order.client_order_id] = order.order_index

    def get_order(self, order_index: OrderIndex) -> Optional[TrackedOrder]:
        """获取订单"""
        return self._orders.get(order_index)

    def get_by_client_id(self, client_order_id: str) -> Optional[TrackedOrder]:
        """通过客户端订单ID获取"""
        idx = self._client_order_ids.get(client_order_id)
        return self._orders.get(idx) if idx else None

    def record_open_in_flight(self, order_index: OrderIndex) -> None:
        """记录在途开仓请求"""
        order = self._orders.get(order_index)
        if order:
            order.status = OrderStatus.OPEN_IN_FLIGHT
            order.updated_at = datetime.now()
            self._in_flight_opens.add(order_index)

    def confirm_open(self, order_index: OrderIndex,
                     exchange_order_id: str = None) -> None:
        """确认订单已开"""
        order = self._orders.get(order_index)
        if order:
            order.status = OrderStatus.OPEN
            order.updated_at = datetime.now()
            if exchange_order_id:
                order.exchange_order_id = exchange_order_id
                self._exchange_order_ids[exchange_order_id] = order_index
            self._in_flight_opens.discard(order_index)

    def record_cancel_in_flight(self, order_index: OrderIndex) -> None:
        """记录在途取消请求"""
        self._in_flight_cancels.add(order_index)

    def confirm_cancelled(self, order_index: OrderIndex) -> None:
        """确认订单已取消"""
        order = self._orders.get(order_index)
        if order:
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.now()
            self._in_flight_cancels.discard(order_index)

    def update_fill(self, order_index: OrderIndex,
                    filled_qty: Decimal,
                    fill_price: Decimal = None) -> None:
        """更新成交"""
        order = self._orders.get(order_index)
        if order:
            order.filled_quantity += filled_qty
            if order.filled_quantity >= order.quantity:
                order.status = OrderStatus.FILLED
            else:
                order.status = OrderStatus.PARTIALLY_FILLED
            order.updated_at = datetime.now()

    def update_from_snapshot(self, snapshot: dict) -> None:
        """从交易所快照更新"""
        exchange_order_id = snapshot.get('order_id')
        if exchange_order_id:
            order_index = self._exchange_order_ids.get(exchange_order_id)
            if order_index:
                order = self._orders.get(order_index)
                if order:
                    # 更新状态
                    status_map = {
                        'open': OrderStatus.OPEN,
                        'filled': OrderStatus.FILLED,
                        'partially_filled': OrderStatus.PARTIALLY_FILLED,
                        'cancelled': OrderStatus.CANCELLED,
                        'expired': OrderStatus.EXPIRED,
                        'rejected': OrderStatus.REJECTED
                    }
                    new_status = status_map.get(snapshot.get('status'))
                    if new_status:
                        order.status = new_status
                    order.filled_quantity = Decimal(str(snapshot.get('filled_qty', 0)))
                    order.updated_at = datetime.now()

    def get_active_orders(self) -> list:
        """获取所有活动订单"""
        return [o for o in self._orders.values() if o.is_active]

    def get_in_flight_requests(self) -> tuple:
        """获取在途请求"""
        opens = list(self._in_flight_opens)
        cancels = list(self._in_flight_cancels)
        return opens, cancels
```

### 6. 使用示例

```python
import backtrader as bt

# 1. 创建索引器
indexer = bt.Indexer()
exchange_idx = indexer.get_or_create_exchange("binance")
asset_idx = indexer.get_or_create_asset(exchange_idx, "BTC")
instrument_idx = indexer.get_or_create_instrument(exchange_idx, asset_idx, "BTCUSDT")

# 2. 创建初始状态
state = bt.EngineState()
state.indexer = indexer

# 3. 创建审计流
audit = bt.AuditStream()
audit.subscribe(lambda event: print(f"Audit: {event.to_dict()}"))

# 4. 创建策略
class MyStrategy(bt.AlgoStrategy):
    def generate_algo_orders(self, state):
        cancels = []
        opens = []

        # 简单示例: 价格低于30000买入
        for inst_idx, inst_state in state.instrument_states.items():
            if inst_state.last_price < Decimal(30000):
                opens.append(bt.OrderRequestOpen(
                    instrument_index=inst_idx,
                    side="buy",
                    price=inst_state.last_price * Decimal(0.99),
                    quantity=Decimal(0.001)
                ))

        return cancels, opens

strategy = MyStrategy()

# 5. 创建风险管理器
risk_mgr = bt.DefaultRiskManager(
    max_position_value=Decimal(10000),
    max_order_value=Decimal(1000)
)

# 6. 创建引擎
engine = bt.Engine(
    state=state,
    strategy=strategy,
    risk_manager=risk_mgr,
    audit=audit
)

# 运行
engine.run()
```

### 7. 实施路线图

#### 阶段1: 索引和状态管理 (2周)
- [ ] 实现Indexer
- [ ] 实现EngineState
- [ ] 实现状态快照
- [ ] 单元测试

#### 阶段2: 审计流系统 (1周)
- [ ] 实现AuditEvent和AuditStream
- [ ] 实现订阅机制
- [ ] 实现历史查询

#### 阶段3: 策略Trait系统 (2周)
- [ ] 定义策略trait接口
- [ ] 实现策略组合
- [ ] 迁移现有策略

#### 阶段4: 风险管理 (1周)
- [ ] 实现RiskManager trait
- [ ] 实现DefaultRiskManager
- [ ] 实现风险计算工具

#### 阶段5: 订单追踪 (1周)
- [ ] 实现OrderTracker
- [ ] 实现状态转换
- [ ] 实现快照更新

#### 阶段6: 集成和测试 (1周)
- [ ] 引擎集成
- [ ] 端到端测试
- [ ] 文档和示例

---

## 附录: 关键文件路径

### Backtrader关键文件
- `cerebro.py`: 核心引擎
- `strategy.py`: Strategy基类
- `linebuffer.py`: Line缓冲区
- `orders.py`: 订单管理
- `broker.py`: Broker基类

### Barter-rs关键文件
- `barter-engine/src/engine.rs`: 核心引擎
- `barter-engine/src/state/`: 状态管理
- `barter-engine/src/strategy/trait.rs`: 策略trait
- `barter-engine/src/risk/mod.rs`: 风险管理
- `barter-engine/src/orders.rs`: 订单管理
- `barter-execution/src/manager.rs`: 执行管理器
