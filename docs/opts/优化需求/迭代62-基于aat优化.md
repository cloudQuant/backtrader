### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/aat
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### aat项目简介
aat (Asynchronous Algorithmic Trading) 是一个异步算法交易框架，具有以下核心特点：
- **异步架构**: 基于asyncio的异步设计
- **C++核心**: 性能关键部分使用C++实现
- **多交易所**: 支持多个交易所和市场
- **WebSocket**: 原生WebSocket支持
- **策略类型**: 支持多种策略类型
- **风险管理**: 内置风险管理模块

### 重点借鉴方向
1. **异步设计**: asyncio异步架构模式
2. **C++加速**: 性能关键模块的C++实现
3. **Exchange抽象**: 交易所统一抽象
4. **OrderBook**: 订单簿管理
5. **StrategyManager**: 策略管理器设计
6. **RiskManager**: 风险管理模块

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
1. **同步架构**: 主要是同步设计，异步支持有限
2. **事件驱动简单**: 基于定时器的bar-by-bar处理
3. **实时交易支持弱**: 虽支持live模式，但设计主要面向回测
4. **订单簿简陋**: 缺少完整的订单簿模拟
5. **交易所抽象不统一**: 各交易所实现差异大
6. **风险管理简单**: 缺少系统化的风险管理引擎
7. **策略模式分离**: 回测和实盘策略需要不同代码

### AAT 核心特点

**优势:**
1. **完全异步架构**: 基于asyncio的真正异步设计
2. **事件驱动**: 完整的事件系统，支持多种事件类型
3. **统一策略接口**: 同一策略代码可用于回测和实盘
4. **四引擎架构**: Trading/Risk/Execution/Backtest分离
5. **完整订单簿**: 支持复杂订单类型和订单标志
6. **交易所抽象**: 统一的_MarketData和_OrderEntry接口
7. **WebSocket原生支持**: 内置WebSocket实时数据流
8. **管理器模式**: StrategyManager/OrderManager/PortfolioManager/RiskManager
9. **uvloop优化**: 使用uvloop加速事件循环

**局限:**
1. **生态较小**: 相比backtrader社区规模小
2. **学习曲线**: 异步编程和事件驱动模式需要学习
3. **文档较少**: 英文文档为主，示例有限
4. **指标库少**: 技术指标不如backtrader丰富

---

## 需求规格文档

### 1. 异步事件驱动架构 (优先级: 高)

**需求描述:**
引入基于asyncio的异步事件驱动架构，支持并发处理多个数据源和策略。

**功能需求:**
1. **异步事件循环**: 基于asyncio的事件循环
2. **事件类型定义**: TRADE/OPEN/CANCEL/CHANGE/FILL/DATA等事件
3. **异步策略回调**: onTrade/onOrder/onFill等异步方法
4. **事件多路复用**: 合并多个数据源的事件流
5. **uvloop支持**: 可选使用uvloop加速

**非功能需求:**
1. 保持与现有同步API兼容
2. 支持混合模式（部分策略异步，部分同步）
3. 性能不低于现有实现

### 2. 统一交易所抽象 (优先级: 高)

**需求描述:**
定义统一的交易所抽象接口，分离行情数据接口和交易接口。

**功能需求:**
1. **_MarketData接口**: 行情订阅、tick数据、订单簿查询
2. **_OrderEntry接口**: 账户查询、下单、撤单
3. **Exchange基类**: 组合上述两个接口
4. **多交易所支持**: 统一接口支持多个交易所
5. **WebSocket集成**: 原生支持WebSocket连接

**非功能需求:**
1. 接口设计简洁易用
2. 支持交易所特定功能扩展

### 3. 完整订单簿系统 (优先级: 中)

**需求描述:**
实现完整的订单簿模拟，支持复杂订单类型和订单标志。

**功能需求:**
1. **订单类型**: 市价单、限价单、止损市价单、止损限价单
2. **订单标志**: FOK (Fill-or-Kill)、AON (All-or-None)、IOC (Immediate-or-Cancel)
3. **价格水平**: 按价格组织订单队列
4. **订单撮合**: 价格优先、时间优先原则
5. **部分成交**: 支持订单部分成交
6. **订单修改**: 支持订单修改和取消

**非功能需求:**
1. O(1)价格水平访问
2. 高效的订单插入和删除
3. 可选C++加速

### 4. 统一策略接口 (优先级: 中)

**需求描述:**
实现统一的策略接口，同一策略代码可用于回测和实盘。

**功能需求:**
1. **统一Strategy基类**: 回测和实盘共用
2. **异步事件处理**: onTrade/onOrder/onFill回调
3. **事件订阅**: 订阅特定类型事件
4. **订单管理**: 统一的订单提交和管理接口
5. **投资组合查询**: 实时查询持仓和P&L

**非功能需求:**
1. 零代码修改切换模式
2. 行为一致性

### 5. 风险管理引擎 (优先级: 中)

**需求描述:**
引入独立的风险管理引擎，在订单执行前进行风险检查。

**功能需求:**
1. **预交易检查**: 订单提交前验证
2. **持仓限制**: 单品种/总持仓限制
3. **资金限制**: 单笔/总资金使用限制
4. **风险规则**: 可配置的风险规则
5. **实时监控**: 持续监控风险指标
6. **订单拦截**: 可修改或拒绝风险订单

**非功能需求:**
1. 不影响正常订单执行速度
2. 规则配置灵活

### 6. 管理器模式重构 (优先级: 低)

**需求描述:**
引入管理器模式，分离关注点。

**功能需求:**
1. **StrategyManager**: 策略与引擎之间的协调器
2. **OrderManager**: 订单生命周期管理
3. **PortfolioManager**: 持仓和P&L跟踪
4. **RiskManager**: 风险检查和监控
5. **EventManager**: 事件分发和订阅

**非功能需求:**
1. 保持API兼容性
2. 渐进式重构

---

## 设计文档

### 1. 异步事件驱动架构设计

#### 1.1 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                      EventLoop (asyncio)                     │
├─────────────────────────────────────────────────────────────┤
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │ Strategy 1 │  │ Strategy 2 │  │ Strategy N │            │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘            │
│        │               │               │                    │
│        ▼               ▼               ▼                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              StrategyManager                        │   │
│  │  - Event Multiplexing                               │   │
│  │  - Strategy Coordination                            │   │
│  └───────────────────┬─────────────────────────────────┘   │
│                      │                                     │
│  ┌───────────────────┼─────────────────────────────────┐   │
│  │                   ▼                                 │   │
│  │  ┌───────────────────────────────────────────────┐  │   │
│  │  │          TradingEngine                        │  │   │
│  │  ├─────────────┬─────────────┬─────────────────┤  │   │
│  │  │ RiskEngine  │ExecEngine  │ BacktestEngine  │  │   │
│  │  └─────────────┴─────────────┴─────────────────┘  │   │
│  └─────────────────────────────────────────────────────┘   │
│                      │                                     │
│  ┌───────────────────┼─────────────────────────────────┐   │
│  │                   ▼                                 │   │
│  │  ┌───────────────────────────────────────────────┐  │   │
│  │  │           Exchange (抽象层)                   │  │   │
│  │  ├───────────────────┬───────────────────────────┤  │   │
│  │  │   _MarketData     │    _OrderEntry            │  │   │
│  │  │ - subscribe()     │ - newOrder()              │  │   │
│  │  │ - tick()          │ - cancelOrder()           │  │   │
│  │  │ - book()          │ - accounts()              │  │   │
│  │  └───────────────────┴───────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

#### 1.2 事件系统设计

```python
# backtrader/async_engine/event.py
from enum import Enum
from dataclasses import dataclass
from typing import Any, Optional
from datetime import datetime

class EventType(Enum):
    """事件类型枚举"""
    HEARTBEAT = "heartbeat"
    TRADE = "trade"           # 交易事件
    OPEN = "open"             # 订单开启事件
    CANCEL = "cancel"         # 订单取消事件
    CHANGE = "change"         # 订单修改事件
    FILL = "fill"             # 订单成交事件
    DATA = "data"             # 市场数据事件
    HALT = "halt"             # 暂停事件
    CONTINUE = "continue"     # 继续事件
    ERROR = "error"           # 错误事件
    START = "start"           # 启动事件
    EXIT = "exit"             # 退出事件

@dataclass
class Event:
    """事件基类"""
    type: EventType
    timestamp: datetime
    data: Any = None
    target: Optional[str] = None  # 目标策略ID
    exchange: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

# 事件处理器类型
from typing import Callable, Awaitable
EventHandler = Callable[[Event], Awaitable[None]]
```

#### 1.3 异步策略基类设计

```python
# backtrader/async_strategy/async_base.py
import asyncio
from abc import ABC, abstractmethod
from typing import Optional

class AsyncStrategy(ABC):
    """
    异步策略基类

    特点:
    1. 同一代码可用于回测和实盘
    2. 完全异步的事件处理
    3. 统一的订单管理接口
    """

    def __init__(self):
        self._engine = None
        self._context = None
        self._event_queue = asyncio.Queue()

    @property
    def engine(self):
        """获取交易引擎引用"""
        return self._engine

    @property
    def portfolio(self):
        """获取投资组合"""
        return self._context.portfolio if self._context else None

    # ========== 必须实现的方法 ==========

    @abstractmethod
    async def on_trade(self, event: Event) -> None:
        """
        处理交易事件

        Args:
            event: 包含交易数据的事件
        """
        raise NotImplementedError

    # ========== 可选实现的方法 ==========

    async def on_order(self, event: Event) -> None:
        """处理订单事件（OPEN/CANCEL/CHANGE/FILL）"""
        pass

    async def on_fill(self, event: Event) -> None:
        """处理成交事件"""
        pass

    async def on_data(self, event: Event) -> None:
        """处理市场数据事件"""
        pass

    async def on_error(self, event: Event) -> None:
        """处理错误事件"""
        pass

    async def on_start(self) -> None:
        """策略启动时的初始化"""
        pass

    async def on_stop(self) -> None:
        """策略停止时的清理"""
        pass

    # ========== 订单管理方法 ==========

    async def buy(self, instrument: str, volume: float,
                  price: Optional[float] = None,
                  order_type: OrderType = OrderType.MARKET,
                  flags: OrderFlag = OrderFlag.NONE) -> Optional[Order]:
        """
        发送买入订单

        Args:
            instrument: 交易品种
            volume: 交易数量
            price: 限价单价格（市价单可不传）
            order_type: 订单类型
            flags: 订单标志

        Returns:
            创建的订单对象
        """
        order = Order(
            instrument=instrument,
            side=OrderSide.BUY,
            volume=volume,
            price=price,
            order_type=order_type,
            flags=flags
        )
        return await self._engine.submit_order(order, self)

    async def sell(self, instrument: str, volume: float,
                   price: Optional[float] = None,
                   order_type: OrderType = OrderType.MARKET,
                   flags: OrderFlag = OrderFlag.NONE) -> Optional[Order]:
        """发送卖出订单"""
        order = Order(
            instrument=instrument,
            side=OrderSide.SELL,
            volume=volume,
            price=price,
            order_type=order_type,
            flags=flags
        )
        return await self._engine.submit_order(order, self)

    async def cancel_order(self, order: Order) -> bool:
        """取消订单"""
        return await self._engine.cancel_order(order)

    async def cancel_all(self, instrument: Optional[str] = None) -> int:
        """取消所有订单"""
        return await self._engine.cancel_all_orders(self, instrument)

    # ========== 查询方法 ==========

    def get_position(self, instrument: str) -> Optional[Position]:
        """获取持仓"""
        if self.portfolio:
            return self.portfolio.get_position(instrument)
        return None

    def get_cash(self) -> float:
        """获取可用资金"""
        if self.portfolio:
            return self.portfolio.cash
        return 0.0

    def get_value(self) -> float:
        """获取总资产"""
        if self.portfolio:
            return self.portfolio.total_value
        return 0.0
```

### 2. 统一交易所抽象设计

#### 2.1 接口定义

```python
# backtrader/exchange/base.py
from abc import ABC, abstractmethod
from typing import List, AsyncIterator, Optional

class _MarketData(ABC):
    """
    行情数据接口

    定义获取市场数据的抽象接口
    """

    @abstractmethod
    async def connect(self) -> None:
        """建立连接"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        pass

    @abstractmethod
    def instruments(self) -> List[str]:
        """获取支持的交易品种列表"""
        pass

    @abstractmethod
    async def subscribe(self, instrument: str) -> None:
        """订阅特定品种的数据"""
        pass

    @abstractmethod
    async def unsubscribe(self, instrument: str) -> None:
        """取消订阅"""
        pass

    @abstractmethod
    async def tick(self) -> AsyncIterator[Event]:
        """
        获取实时数据流

        Yields:
            市场数据事件
        """
        pass

    @abstractmethod
    async def book(self, instrument: str) -> Optional[OrderBook]:
        """获取订单簿快照"""
        pass


class _OrderEntry(ABC):
    """
    订单接口

    定义订单操作的抽象接口
    """

    @abstractmethod
    async def accounts(self) -> List[str]:
        """获取账户列表"""
        pass

    @abstractmethod
    async def balance(self, account: str) -> dict:
        """获取账户余额"""
        pass

    @abstractmethod
    async def new_order(self, order: Order) -> bool:
        """
        提交新订单

        Returns:
            是否成功提交
        """
        pass

    @abstractmethod
    async def cancel_order(self, order: Order) -> bool:
        """取消订单"""
        pass

    @abstractmethod
    async def cancel_all(self, instrument: Optional[str] = None) -> int:
        """取消所有订单"""
        pass

    @abstractmethod
    async def get_orders(self, instrument: Optional[str] = None) -> List[Order]:
        """获取活动订单列表"""
        pass


class Exchange(_MarketData, _OrderEntry):
    """
    交易所基类

    组合行情数据和订单接口
    """

    def __init__(self, name: str, config: dict = None):
        self.name = name
        self.config = config or {}
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """建立连接"""
        await super().connect()
        self._connected = True

    async def disconnect(self) -> None:
        """断开连接"""
        self._connected = False
        await super().disconnect()
```

#### 2.2 具体交易所实现示例

```python
# backtrader/exchange/exchanges/ccxt_exchange.py
import ccxt.async_support as ccxt

class CCXTExchange(Exchange):
    """
    基于CCXT的交易所实现

    支持所有CCXT支持的交易所
    """

    def __init__(self, exchange_id: str, config: dict = None):
        super().__init__(exchange_id, config)
        self._exchange_class = getattr(ccxt, exchange_id)
        self._exchange: ccxt.Exchange = None

    async def connect(self) -> None:
        """建立连接"""
        self._exchange = self._exchange_class(self.config)
        await self._exchange.load_markets()
        await super().connect()

    async def disconnect(self) -> None:
        """断开连接"""
        if self._exchange:
            await self._exchange.close()
        await super().disconnect()

    def instruments(self) -> List[str]:
        """获取支持的交易品种"""
        if self._exchange:
            return list(self._exchange.markets.keys())
        return []

    async def subscribe(self, instrument: str) -> None:
        """订阅特定品种"""
        # CCXT使用polling方式，不需要显式订阅
        pass

    async def tick(self) -> AsyncIterator[Event]:
        """获取实时数据流"""
        while self._connected:
            for instrument in self.instruments():
                try:
                    ticker = await self._exchange.fetch_ticker(instrument)
                    yield Event(
                        type=EventType.DATA,
                        data={'ticker': ticker, 'instrument': instrument}
                    )
                except Exception as e:
                    yield Event(
                        type=EventType.ERROR,
                        data={'error': str(e)}
                    )
            await asyncio.sleep(1)  # 轮询间隔

    async def book(self, instrument: str) -> Optional[OrderBook]:
        """获取订单簿"""
        if self._exchange:
            orderbook = await self._exchange.fetch_order_book(instrument)
            return OrderBook.from_ccxt(orderbook)
        return None

    async def accounts(self) -> List[str]:
        """获取账户列表"""
        # CCXT通常只有一个账户
        return ['default']

    async def balance(self, account: str) -> dict:
        """获取账户余额"""
        if self._exchange:
            balance = await self._exchange.fetch_balance()
            return balance
        return {}

    async def new_order(self, order: Order) -> bool:
        """提交新订单"""
        if self._exchange:
            try:
                await self._exchange.create_order(
                    order.instrument,
                    order.order_type.value.lower(),
                    order.side.value.lower(),
                    order.volume,
                    order.price
                )
                return True
            except Exception:
                return False
        return False

    async def cancel_order(self, order: Order) -> bool:
        """取消订单"""
        if self._exchange and order.exchange_id:
            try:
                await self._exchange.cancel_order(order.exchange_id)
                return True
            except Exception:
                return False
        return False

    async def cancel_all(self, instrument: Optional[str] = None) -> int:
        """取消所有订单"""
        if self._exchange:
            try:
                await self._exchange.cancel_all_orders(symbol=instrument)
                return 0  # CCXT不返回取消数量
            except Exception:
                return -1
        return 0
```

### 3. 订单簿系统设计

#### 3.1 订单类型和标志

```python
# backtrader/order/order.py
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"

class OrderFlag(Enum):
    NONE = "none"
    FILL_OR_KILL = "fok"        # 全部成交或立即取消
    ALL_OR_NONE = "aon"         # 全部成交（可等待）
    IMMEDIATE_OR_CANCEL = "ioc" # 立即成交可部分

class OrderStatus(Enum):
    PENDING = "pending"     # 待提交
    OPEN = "open"           # 已提交
    FILLED = "filled"       # 已成交
    PARTIALLY_FILLED = "partially_filled"  # 部分成交
    CANCELLED = "cancelled" # 已取消
    REJECTED = "rejected"   # 被拒绝

@dataclass
class Order:
    """订单对象"""
    id: str                    # 订单ID
    instrument: str            # 交易品种
    side: OrderSide            # 买卖方向
    volume: float              # 数量
    price: Optional[float]     # 价格（限价单）
    stop_price: Optional[float] = None  # 止损价
    order_type: OrderType = OrderType.MARKET
    flags: OrderFlag = OrderFlag.NONE
    status: OrderStatus = OrderStatus.PENDING
    filled_volume: float = 0   # 已成交数量
    exchange_id: Optional[str] = None  # 交易所订单ID
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()

    @property
    def remaining_volume(self) -> float:
        """剩余数量"""
        return self.volume - self.filled_volume

    @property
    def is_filled(self) -> bool:
        """是否已完全成交"""
        return self.filled_volume >= self.volume

    @property
    def is_active(self) -> bool:
        """是否活动"""
        return self.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)

    def fill(self, volume: float, price: float) -> None:
        """成交"""
        fill_volume = min(volume, self.remaining_volume)
        self.filled_volume += fill_volume
        self.updated_at = datetime.now()

        if self.filled_volume >= self.volume:
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED
```

#### 3.2 订单簿实现

```python
# backtrader/order/order_book.py
from collections import defaultdict, deque
from typing import Optional, List
from sortedcontainers import SortedDict

class PriceLevel:
    """
    价格水平

    同一价格的所有订单按时间顺序排队
    """

    def __init__(self, price: float):
        self.price = price
        self.orders = deque()  # FIFO队列
        self.total_volume = 0.0

    def add(self, order: Order) -> None:
        """添加订单"""
        self.orders.append(order)
        self.total_volume += order.volume

    def remove(self, order: Order) -> None:
        """移除订单"""
        if order in self.orders:
            self.orders.remove(order)
            self.total_volume -= order.volume

    def match(self, volume: float) -> tuple[List[Order], float]:
        """
        撮合订单

        Returns:
            (成交订单列表, 剩余数量)
        """
        filled_orders = []
        remaining = volume

        while remaining > 0 and self.orders:
            order = self.orders[0]

            if order.remaining_volume <= remaining:
                # 完全成交
                filled_orders.append(order)
                remaining -= order.remaining_volume
                self.orders.popleft()
            else:
                # 部分成交
                order.fill(remaining, self.price)
                filled_orders.append(order)
                remaining = 0

        self.total_volume = sum(o.remaining_volume for o in self.orders)
        return filled_orders, remaining

    def __len__(self):
        return len(self.orders)

    def __bool__(self):
        return len(self.orders) > 0


class OrderBook:
    """
    订单簿

    支持市价单、限价单、止损单
    """

    def __init__(self, instrument: str):
        self.instrument = instrument
        # 买单: 价格从高到低排序 (使用负数作为key实现降序)
        self._buy_levels: SortedDict = SortedDict()
        # 卖单: 价格从低到高排序
        self._sell_levels: SortedDict = SortedDict()
        # 止损买单
        self._stop_buy_levels: SortedDict = SortedDict()
        # 止损卖单
        self._stop_sell_levels: SortedDict = SortedDict()
        # 价格到价格水平的映射
        self._price_levels: dict = {}

    def add_order(self, order: Order) -> bool:
        """添加订单到订单簿"""
        if order.order_type == OrderType.MARKET:
            # 市价单不加入订单簿，立即撮合
            return self._match_market(order)
        elif order.order_type == OrderType.LIMIT:
            return self._add_limit_order(order)
        elif order.order_type == OrderType.STOP_MARKET:
            return self._add_stop_order(order)
        elif order.order_type == OrderType.STOP_LIMIT:
            return self._add_stop_limit_order(order)
        return False

    def _add_limit_order(self, order: Order) -> bool:
        """添加限价单"""
        levels = self._buy_levels if order.side == OrderSide.BUY else self._sell_levels

        # 创建或获取价格水平
        if order.price not in levels:
            price_level = PriceLevel(order.price)
            levels[order.price] = price_level
            self._price_levels[order.price] = price_level

        price_level = levels[order.price]
        price_level.add(order)

        # 尝试撮合
        self._try_match(order)
        return True

    def _match_market(self, order: Order) -> bool:
        """撮合市价单"""
        if order.side == OrderSide.BUY:
            levels = self._sell_levels
        else:
            levels = self._buy_levels

        remaining = order.volume
        filled_orders = []
        prices_to_remove = []

        # 遍历价格水平
        for price in list(levels.keys()):
            if remaining <= 0:
                break

            price_level = levels[price]
            orders, remaining = price_level.match(remaining)
            filled_orders.extend(orders)

            if not price_level:
                prices_to_remove.append(price)

        # 清理空价格水平
        for price in prices_to_remove:
            del levels[price]
            del self._price_levels[price]

        return len(filled_orders) > 0 or remaining == order.volume

    def _try_match(self, order: Order) -> None:
        """尝试撮合限价单"""
        if order.side == OrderSide.BUY:
            # 买单与卖单撮合
            while order.remaining_volume > 0 and self._sell_levels:
                best_ask = next(iter(self._sell_levels))  # 最低卖价
                if best_ask > order.price:
                    break  # 价格不匹配
                price_level = self._sell_levels[best_ask]
                orders, remaining = price_level.match(order.remaining_volume)
                for o in orders:
                    o.fill(min(o.remaining_volume, order.remaining_volume), best_ask)
                    order.fill(o.filled_volume, best_ask)
                if not price_level:
                    del self._sell_levels[best_ask]
        else:
            # 卖单与买单撮合
            while order.remaining_volume > 0 and self._buy_levels:
                best_bid = next(iter(self._buy_levels))  # 最高买价
                if best_bid < order.price:
                    break  # 价格不匹配
                price_level = self._buy_levels[best_bid]
                orders, remaining = price_level.match(order.remaining_volume)
                for o in orders:
                    o.fill(min(o.remaining_volume, order.remaining_volume), best_bid)
                    order.fill(o.filled_volume, best_bid)
                if not price_level:
                    del self._buy_levels[best_bid]

    def cancel_order(self, order: Order) -> bool:
        """取消订单"""
        # 找到订单所在的价格水平
        if order.price and order.price in self._price_levels:
            price_level = self._price_levels[order.price]
            price_level.remove(order)
            if not price_level:
                # 清理空价格水平
                if order.side == OrderSide.BUY:
                    del self._buy_levels[order.price]
                else:
                    del self._sell_levels[order.price]
                del self._price_levels[order.price]
            return True
        return False

    @property
    def best_bid(self) -> Optional[float]:
        """最优买价"""
        if self._buy_levels:
            return next(iter(self._buy_levels))
        return None

    @property
    def best_ask(self) -> Optional[float]:
        """最优卖价"""
        if self._sell_levels:
            return next(iter(self._sell_levels))
        return None

    @property
    def spread(self) -> Optional[float]:
        """买卖价差"""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    def get_depth(self, levels: int = 5) -> dict:
        """
        获取订单簿深度

        Returns:
            {'bids': [(price, volume), ...], 'asks': [(price, volume), ...]}
        """
        bids = []
        asks = []

        for i, (price, level) in enumerate(self._buy_levels.items()):
            if i >= levels:
                break
            bids.append((price, level.total_volume))

        for i, (price, level) in enumerate(self._sell_levels.items()):
            if i >= levels:
                break
            asks.append((price, level.total_volume))

        return {'bids': bids, 'asks': asks}
```

### 4. 风险管理引擎设计

```python
# backtrader/risk/risk_manager.py
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class RiskRule:
    """风险规则"""
    name: str
    max_position_size: Optional[float] = None     # 单品种最大持仓
    max_total_position: Optional[float] = None    # 总持仓限制
    max_order_size: Optional[float] = None        # 单笔最大订单
    max_daily_loss: Optional[float] = None        # 日最大亏损
    max_drawdown: Optional[float] = None          # 最大回撤

class RiskManager:
    """
    风险管理引擎

    在订单执行前进行风险检查
    """

    def __init__(self, portfolio=None):
        self.portfolio = portfolio
        self.rules: dict = {}  # {strategy_id: RiskRule}
        self._daily_pnl: float = 0
        self._peak_value: float = 0

    def set_rule(self, strategy_id: str, rule: RiskRule) -> None:
        """设置策略的风险规则"""
        self.rules[strategy_id] = rule

    def get_rule(self, strategy_id: str) -> RiskRule:
        """获取策略的风险规则"""
        return self.rules.get(strategy_id, RiskRule(name="default"))

    async def check_order(self, order: Order, strategy_id: str) -> tuple[bool, str]:
        """
        检查订单是否符合风险规则

        Returns:
            (是否通过, 拒绝原因)
        """
        rule = self.get_rule(strategy_id)

        # 检查单笔订单大小
        if rule.max_order_size and order.volume > rule.max_order_size:
            return False, f"订单超过最大限制: {order.volume} > {rule.max_order_size}"

        # 检查持仓限制
        if rule.max_position_size and self.portfolio:
            current_position = self.portfolio.get_position(order.instrument)
            new_size = abs(current_position.size + order.volume) if current_position else order.volume
            if new_size > rule.max_position_size:
                return False, f"持仓超过限制: {new_size} > {rule.max_position_size}"

        # 检查总持仓
        if rule.max_total_position and self.portfolio:
            total_position = sum(abs(p.size) for p in self.portfolio.positions.values())
            if total_position + order.volume > rule.max_total_position:
                return False, f"总持仓超过限制: {total_position + order.volume} > {rule.max_total_position}"

        # 检查日内亏损
        if rule.max_daily_loss and self._daily_pnl < -rule.max_daily_loss:
            return False, f"日内亏损超限: {self._daily_pnl} < -{rule.max_daily_loss}"

        # 检查最大回撤
        if rule.max_drawdown and self.portfolio:
            current_value = self.portfolio.total_value
            if current_value > self._peak_value:
                self._peak_value = current_value

            drawdown = (self._peak_value - current_value) / self._peak_value
            if drawdown > rule.max_drawdown:
                return False, f"回撤超限: {drawdown:.2%} > {rule.max_drawdown:.2%}"

        return True, ""

    async def modify_order(self, order: Order, strategy_id: str) -> Order:
        """
        修改订单以符合风险规则

        Returns:
            修改后的订单
        """
        rule = self.get_rule(strategy_id)
        modified = Order(**order.__dict__)

        # 调整订单大小
        if rule.max_order_size and modified.volume > rule.max_order_size:
            modified.volume = rule.max_order_size

        # 调整持仓
        if rule.max_position_size and self.portfolio:
            current = self.portfolio.get_position(modified.instrument)
            if current:
                max_add = rule.max_position_size - abs(current.size)
                if modified.volume > max_add:
                    modified.volume = max_add

        return modified

    def update_pnl(self, pnl: float) -> None:
        """更新盈亏"""
        self._daily_pnl += pnl

    def reset_daily(self) -> None:
        """重置日内统计"""
        self._daily_pnl = 0
```

### 5. 交易引擎设计

```python
# backtrader/async_engine/engine.py
import asyncio
from typing import List, Optional, AsyncIterator
from aiostream import stream

class TradingEngine:
    """
    交易引擎

    协调策略、风险管理、执行和交易所
    """

    def __init__(self):
        self.strategies: List[AsyncStrategy] = []
        self.exchanges: List[Exchange] = []
        self.risk_manager: RiskManager = RiskManager()
        self.portfolio_manager = PortfolioManager()
        self._running = False

    def add_strategy(self, strategy: AsyncStrategy) -> None:
        """添加策略"""
        strategy._engine = self
        strategy._context = StrategyContext(
            portfolio=self.portfolio_manager.create_portfolio(strategy)
        )
        self.strategies.append(strategy)

    def add_exchange(self, exchange: Exchange) -> None:
        """添加交易所"""
        self.exchanges.append(exchange)

    async def run(self) -> None:
        """启动交易引擎"""
        self._running = True

        # 启动所有策略
        for strategy in self.strategies:
            await strategy.on_start()

        # 连接所有交易所
        for exchange in self.exchanges:
            await exchange.connect()

        # 创建事件流
        exchange_streams = [exchange.tick() for exchange in self.exchanges]

        # 主事件循环
        async with stream.merge(*exchange_streams).stream() as stream:
            async for event in stream:
                if not self._running:
                    break

                # 分发事件到所有策略
                await self._dispatch_event(event)

        # 清理
        for exchange in self.exchanges:
            await exchange.disconnect()

        for strategy in self.strategies:
            await strategy.on_stop()

    async def _dispatch_event(self, event: Event) -> None:
        """分发事件到策略"""
        for strategy in self.strategies:
            # 如果事件有指定目标，只发送给目标策略
            if event.target and strategy.id != event.target:
                continue

            # 根据事件类型调用相应方法
            if event.type == EventType.TRADE:
                await strategy.on_trade(event)
            elif event.type == EventType.FILL:
                await strategy.on_fill(event)
                self.portfolio_manager.update_position(event.data)
            elif event.type in (EventType.OPEN, EventType.CANCEL, EventType.CHANGE):
                await strategy.on_order(event)
            elif event.type == EventType.DATA:
                await strategy.on_data(event)
            elif event.type == EventType.ERROR:
                await strategy.on_error(event)

    async def submit_order(self, order: Order, strategy: AsyncStrategy) -> Optional[Order]:
        """提交订单"""
        # 风险检查
        passed, reason = await self.risk_manager.check_order(order, strategy.id)
        if not passed:
            # 发送拒绝事件
            await strategy.on_order(Event(
                type=EventType.ERROR,
                data={'reason': reason, 'order': order}
            ))
            return None

        # 可能的订单修改
        order = await self.risk_manager.modify_order(order, strategy.id)

        # 提交到交易所
        for exchange in self.exchanges:
            if await exchange.new_order(order):
                return order

        return None

    async def cancel_order(self, order: Order) -> bool:
        """取消订单"""
        for exchange in self.exchanges:
            if await exchange.cancel_order(order):
                return True
        return False

    def stop(self) -> None:
        """停止引擎"""
        self._running = False
```

### 6. 使用示例

#### 6.1 定义异步策略

```python
import backtrader as bt

class MyAsyncStrategy(bt.AsyncStrategy):
    """简单的移动平均异步策略"""

    async def on_start(self):
        """初始化"""
        self.fast_prices = []
        self.slow_prices = []
        print(f"策略 {self.id} 启动")

    async def on_trade(self, event):
        """处理交易事件"""
        data = event.data
        price = data.get('price')

        # 更新价格缓存
        self.fast_prices.append(price)
        self.slow_prices.append(price)

        if len(self.fast_prices) > 10:
            self.fast_prices.pop(0)
        if len(self.slow_prices) > 30:
            self.slow_prices.pop(0)

        # 计算移动平均
        if len(self.fast_prices) >= 10 and len(self.slow_prices) >= 30:
            fast_ma = sum(self.fast_prices) / len(self.fast_prices)
            slow_ma = sum(self.slow_prices) / len(self.slow_prices)

            position = self.get_position(event.instrument)

            # 金叉买入
            if fast_ma > slow_ma and (not position or position.size <= 0):
                await self.buy(
                    instrument=event.instrument,
                    volume=1.0
                )

            # 死叉卖出
            elif fast_ma < slow_ma and position and position.size > 0:
                await self.sell(
                    instrument=event.instrument,
                    volume=position.size
                )

    async def on_fill(self, event):
        """处理成交事件"""
        print(f"订单成交: {event.data}")

    async def on_error(self, event):
        """处理错误"""
        print(f"错误: {event.data.get('reason')}")
```

#### 6.2 运行回测

```python
# 创建引擎
engine = TradingEngine()

# 添加策略
strategy = MyAsyncStrategy()
engine.add_strategy(strategy)

# 添加回测交易所
backtest_exchange = BacktestExchange(
    datafeed=bt.feeds.PandasData(dataname=df)
)
engine.add_exchange(backtest_exchange)

# 设置风险规则
engine.risk_manager.set_rule(strategy.id, RiskRule(
    name="my_rule",
    max_position_size=100,
    max_order_size=10,
    max_daily_loss=1000
))

# 运行
await engine.run()
```

#### 6.3 运行实盘

```python
# 创建引擎
engine = TradingEngine()

# 添加策略 (使用相同的策略类!)
strategy = MyAsyncStrategy()
engine.add_strategy(strategy)

# 添加实盘交易所
exchange = CCXTExchange(
    exchange_id='binance',
    config={'apiKey': 'xxx', 'secret': 'yyy'}
)
engine.add_exchange(exchange)

# 运行 (其余代码相同)
await engine.run()
```

### 7. 实施路线图

#### 阶段1: 基础异步框架 (2-3周)
- [ ] 实现事件系统
- [ ] 实现异步策略基类
- [ ] 实现基础交易引擎
- [ ] 添加回测支持

#### 阶段2: 交易所抽象 (2周)
- [ ] 实现交易所接口
- [ ] 实现CCXT集成
- [ ] 实现WebSocket支持
- [ ] 添加回测交易所

#### 阶段3: 订单簿系统 (2周)
- [ ] 实现订单类型和标志
- [ ] 实现价格水平管理
- [ ] 实现订单撮合逻辑
- [ ] 添加订单簿查询

#### 阶段4: 风险管理 (1周)
- [ ] 实现风险规则
- [ ] 实现风险检查
- [ ] 实现订单修改

#### 阶段5: 测试和文档 (2周)
- [ ] 单元测试
- [ ] 集成测试
- [ ] 文档编写
- [ ] 示例代码

---

## 附录: 关键文件路径

### Backtrader关键文件
- `cerebro.py`: 核心引擎
- `strategy.py`: Strategy基类
- `linebuffer.py`: Line缓冲区
- `indicator.py`: Indicator基类
- `broker.py`: Broker基类

### AAT关键文件
- `aat/strategy/strategy.py`: 策略基类
- `aat/exchange/exchange.py`: 交易所抽象
- `aat/core/order_book/order_book/order_book.py`: 订单簿
- `aat/engine/core/trading_engine.py`: 交易引擎
- `aat/engine/dispatch/risk/risk.py`: 风险管理
- `aat/config/enums.py`: 枚举定义
