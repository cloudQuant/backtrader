# 迭代94 - CCXT实盘交易优化完整开发文档

## 版本信息
- **文档版本**: v1.0
- **创建日期**: 2026-01-20
- **更新日期**: 2026-01-20
- **作者**: Backtrader开发团队

---

## 1. 背景与目标

### 1.1 背景

Backtrader已经具备基础的CCXT集成功能，包括：
- `CCXTStore`: 交易所连接和API封装
- `CCXTBroker`: 订单执行和持仓管理
- `CCXTFeed`: 历史和实时数据获取

经过对比分析`backtrader-crypto`项目和`ccxt-store`项目，发现当前实现存在以下可优化点：

1. **无WebSocket支持**: 仅使用REST API轮询，延迟较高
2. **单线程架构**: 所有操作同步阻塞，影响性能
3. **缺少Bracket订单**: 不支持OCO订单（止损止盈组合）
4. **限流机制简单**: 缺乏智能限流和自动重连
5. **交易所配置不灵活**: 缺少交易所特定的参数映射

### 1.2 目标

将Backtrader打造成功能完整的加密货币实盘交易平台，实现：

1. **实时数据流**: 通过WebSocket实现毫秒级数据更新
2. **高性能架构**: 多线程处理数据、订单和账户
3. **完整订单支持**: 支持Bracket订单和OCO订单
4. **智能限流**: 自动适应交易所API限制
5. **灵活配置**: 支持不同交易所的特定配置

---

## 2. 现状分析

### 2.1 当前Backtrader CCXT实现

#### CCXTStore (`backtrader/stores/ccxtstore.py`)
```
功能完整度: ★★★★☆
- ✅ CCXT交易所连接
- ✅ 余额查询
- ✅ 订单创建/取消
- ✅ OHLCV数据获取
- ✅ 重试机制
- ❌ WebSocket支持
- ❌ 多线程架构
```

#### CCXTBroker (`backtrader/brokers/ccxtbroker.py`)
```
功能完整度: ★★★☆☆
- ✅ 订单创建和管理
- ✅ 持仓跟踪
- ✅ 成交处理（两种模式）
- ✅ 订单状态映射
- ❌ Bracket订单
- ❌ 多线程订单检查
- ❌ 智能余额缓存
```

#### CCXTFeed (`backtrader/feeds/ccxtfeed.py`)
```
功能完整度: ★★★☆☆
- ✅ 历史数据加载
- ✅ 实时数据轮询
- ✅ 状态机管理
- ❌ WebSocket数据流
- ❌ 智能回填
- ❌ 多线程更新
```

### 2.2 backtrader-crypto参考实现对比

| 功能模块 | Backtrader当前 | backtrader-crypto | 差异说明 |
|---------|---------------|-------------------|---------|
| Store单例模式 | Mixin实现 | MetaClass实现 | 功能等效 |
| 重试机制 | 装饰器 | 装饰器 | 功能等效 |
| 余额缓存 | 有 | 有 | 功能等效 |
| 订单类型映射 | 有 | 有 | 功能等效 |
| 成交检测 | 双模式 | 双模式 | 功能等效 |
| 限速处理 | rateLimit等待 | rateLimit等待 | 功能等效 |
| WebSocket | 无 | 无 | 均需增强 |
| 多线程 | 无 | 无 | 均需增强 |
| Bracket订单 | 无 | 无 | 均需增强 |

### 2.3 结论

当前Backtrader的CCXT实现**已经是可用的**，与backtrader-crypto基本等效。
主要优化方向应聚焦于**新功能增强**而非重构现有代码。

---

## 3. 需求规格

### 3.1 功能需求矩阵

| 需求ID | 功能描述 | 优先级 | 复杂度 | 预估工时 |
|--------|----------|--------|--------|----------|
| CCXT-001 | WebSocket数据流支持 | P0 | 高 | 5天 |
| CCXT-002 | 多线程数据更新架构 | P0 | 高 | 3天 |
| CCXT-003 | 多线程订单状态检查 | P1 | 中 | 2天 |
| CCXT-004 | Bracket订单支持 | P1 | 中 | 3天 |
| CCXT-005 | 智能限流管理器 | P1 | 中 | 2天 |
| CCXT-006 | 自动重连机制 | P1 | 中 | 2天 |
| CCXT-007 | 交易所配置系统 | P2 | 低 | 1天 |
| CCXT-008 | 余额智能缓存 | P2 | 低 | 1天 |
| CCXT-009 | 性能监控指标 | P2 | 低 | 1天 |

### 3.2 详细需求规格

#### CCXT-001: WebSocket数据流支持

**描述**: 使用CCXT Pro的WebSocket功能实现实时数据流

**功能要求**:
- 支持watchTicker实时行情
- 支持watchOHLCV实时K线
- 支持watchOrderBook实时订单簿
- 支持watchMyTrades实时成交

**接口设计**:
```python
class CCXTWebSocketManager:
    def __init__(self, exchange_id: str, config: dict)
    async def connect(self) -> bool
    async def subscribe_ticker(self, symbol: str, callback: Callable)
    async def subscribe_ohlcv(self, symbol: str, timeframe: str, callback: Callable)
    async def subscribe_trades(self, symbol: str, callback: Callable)
    async def unsubscribe(self, channel: str)
    async def disconnect(self)
    def is_connected(self) -> bool
```

**验收标准**:
- [ ] 能够建立WebSocket连接
- [ ] 能够订阅和接收实时数据
- [ ] 断线后能自动重连
- [ ] 重连后能恢复订阅

---

#### CCXT-002: 多线程数据更新架构

**描述**: 将数据更新操作移到独立线程，避免阻塞主策略循环

**功能要求**:
- 独立的数据获取线程
- 线程安全的数据队列
- 优雅的线程启停控制

**接口设计**:
```python
class ThreadedDataManager:
    def __init__(self, store: CCXTStore)
    def start(self)
    def stop(self)
    def get_data(self, timeout: float = None) -> Optional[dict]
    def is_running(self) -> bool
```

**验收标准**:
- [ ] 数据更新不阻塞主线程
- [ ] 数据队列线程安全
- [ ] 能够优雅关闭线程

---

#### CCXT-003: 多线程订单状态检查

**描述**: 将订单状态检查移到独立线程

**功能要求**:
- 独立的订单检查线程
- 可配置的检查间隔
- 订单状态变化通知

**接口设计**:
```python
class ThreadedOrderManager:
    def __init__(self, store: CCXTStore, check_interval: float = 3.0)
    def start(self)
    def stop(self)
    def add_order(self, order: CCXTOrder)
    def remove_order(self, order_id: str)
    def get_updates(self) -> List[OrderUpdate]
```

**验收标准**:
- [ ] 订单检查不阻塞主线程
- [ ] 订单状态变化能及时通知
- [ ] 能够优雅关闭线程

---

#### CCXT-004: Bracket订单支持

**描述**: 实现OCO（One-Cancels-Other）订单组合

**功能要求**:
- 创建入场+止损+止盈组合订单
- 入场成交后激活保护订单
- 任一保护订单成交后取消另一个
- 支持修改止损止盈价格

**接口设计**:
```python
class BracketOrderManager:
    def __init__(self, broker: CCXTBroker)
    def create_bracket(
        self,
        data,
        size: float,
        entry_price: float,
        stop_price: float,
        limit_price: float,
        entry_type: int = bt.Order.Limit
    ) -> BracketOrder
    def modify_bracket(
        self,
        bracket_id: str,
        stop_price: float = None,
        limit_price: float = None
    )
    def cancel_bracket(self, bracket_id: str)
    def on_order_update(self, order: CCXTOrder)
```

**验收标准**:
- [ ] 能够创建Bracket订单
- [ ] 入场成交后正确激活保护订单
- [ ] OCO逻辑正确执行
- [ ] 能够修改和取消Bracket订单

---

#### CCXT-005: 智能限流管理器

**描述**: 实现智能API调用频率控制

**功能要求**:
- 跟踪API调用频率
- 自动等待避免触及限制
- 指数退避重试机制
- 批量请求优化

**接口设计**:
```python
class RateLimiter:
    def __init__(self, requests_per_minute: int = 1200)
    def acquire(self) -> None  # 阻塞直到可以调用
    def get_wait_time(self) -> float  # 获取建议等待时间
    def reset(self) -> None

def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0
) -> Callable  # 装饰器
```

**验收标准**:
- [ ] 不触及交易所API限制
- [ ] 重试机制正确工作
- [ ] 性能开销可接受

---

#### CCXT-006: 自动重连机制

**描述**: 实现网络断开后的自动重连和状态恢复

**功能要求**:
- 检测连接断开
- 自动尝试重连
- 重连后恢复订阅
- 回填缺失数据

**接口设计**:
```python
class ConnectionManager:
    def __init__(self, store: CCXTStore)
    def on_disconnect(self, callback: Callable)
    def on_reconnect(self, callback: Callable)
    def is_connected(self) -> bool
    def reconnect(self) -> bool
    def get_missed_data(self, symbol: str, since: int) -> List
```

**验收标准**:
- [ ] 能够检测连接断开
- [ ] 能够自动重连
- [ ] 重连后能恢复状态
- [ ] 能够回填缺失数据

---

#### CCXT-007: 交易所配置系统

**描述**: 统一管理不同交易所的特定配置

**功能要求**:
- 订单类型映射配置
- 时间框架映射配置
- 交易所特定参数
- 费率配置

**接口设计**:
```python
class ExchangeConfig:
    ORDER_TYPES: Dict[str, Dict]
    TIMEFRAMES: Dict[str, Dict]
    EXCHANGE_PARAMS: Dict[str, Dict]
    
    @classmethod
    def get_order_type(cls, exchange: str, bt_type: int) -> str
    
    @classmethod
    def get_timeframe(cls, exchange: str, bt_tf: tuple) -> str
    
    @classmethod
    def get_params(cls, exchange: str) -> dict
```

**验收标准**:
- [ ] 支持主流交易所配置
- [ ] 配置可扩展
- [ ] 默认配置合理

---

## 4. 架构设计

### 4.1 目录结构

```
backtrader/
├── stores/
│   └── ccxtstore.py          # CCXTStore (现有，需增强)
│
├── brokers/
│   └── ccxtbroker.py         # CCXTBroker (现有，需增强)
│
├── feeds/
│   └── ccxtfeed.py           # CCXTFeed (现有，需增强)
│
└── ccxt/                     # 新增CCXT增强模块
    ├── __init__.py
    ├── websocket.py          # WebSocket管理
    ├── threading.py          # 多线程工具
    ├── ratelimit.py          # 限流管理
    ├── connection.py         # 连接管理
    ├── config.py             # 交易所配置
    └── orders/
        ├── __init__.py
        └── bracket.py        # Bracket订单
```

### 4.2 模块依赖图

```
┌─────────────────────────────────────────────────────────────────┐
│                         Strategy                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  CCXTFeed   │  │ CCXTBroker  │  │  Analyzers  │             │
│  │ (Enhanced)  │  │ (Enhanced)  │  │             │             │
│  └──────┬──────┘  └──────┬──────┘  └─────────────┘             │
│         │                │                                       │
│         │                │                                       │
│  ┌──────▼────────────────▼──────┐                               │
│  │        CCXTStore             │                               │
│  │       (Enhanced)             │                               │
│  └──────────────┬───────────────┘                               │
│                 │                                                │
│  ┌──────────────┼───────────────┐                               │
│  │              │               │                               │
│  ▼              ▼               ▼                               │
│ ┌────────┐ ┌─────────┐ ┌──────────────┐ ┌────────────┐        │
│ │WebSocket│ │Threading│ │ RateLimiter │ │ExchangeCfg │        │
│ │Manager │ │ Manager │ │             │ │            │        │
│ └────────┘ └─────────┘ └──────────────┘ └────────────┘        │
│                                                                  │
│              ┌──────────────┐                                   │
│              │ BracketOrder │                                   │
│              │   Manager    │                                   │
│              └──────────────┘                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 数据流设计

#### 4.3.1 REST模式数据流（当前）
```
Exchange API ──REST──> CCXTStore ──Queue──> CCXTFeed ──> Strategy
     ▲                                                      │
     └──────────────────Order─────────────────────────────-─┘
```

#### 4.3.2 WebSocket模式数据流（增强后）
```
                    ┌──WebSocket──> WebSocketManager ─┐
Exchange API ──────┤                                  ├──> CCXTFeed ──> Strategy
                    └──REST──> CCXTStore ────────────-┘        │
     ▲                                                          │
     └──────────────────────Order───────────────────────────────┘
```

### 4.4 线程模型

```
Main Thread (Strategy Loop)
     │
     ├── Data Thread (CCXTFeed)
     │   └── WebSocket Event Loop (if enabled)
     │
     ├── Order Thread (CCXTBroker)
     │   └── Order Status Polling
     │
     └── Balance Thread (CCXTBroker)
         └── Balance Update Polling
```

---

## 5. 详细设计

### 5.1 WebSocket模块设计

```python
# ccxt/websocket.py
import asyncio
import threading
from typing import Callable, Dict, Optional
import ccxt.pro as ccxtpro

class CCXTWebSocketManager:
    """CCXT WebSocket连接管理器
    
    使用CCXT Pro实现WebSocket实时数据流
    """
    
    def __init__(self, exchange_id: str, config: dict):
        self.exchange_id = exchange_id
        self.config = config
        self.exchange = None
        self._loop = None
        self._thread = None
        self._running = False
        self._subscriptions: Dict[str, Callable] = {}
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        
    def start(self):
        """启动WebSocket线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        
    def stop(self):
        """停止WebSocket线程"""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5.0)
            
    def _run_loop(self):
        """运行asyncio事件循环"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        try:
            self._loop.run_until_complete(self._connect())
            self._loop.run_forever()
        finally:
            self._loop.close()
            
    async def _connect(self):
        """建立WebSocket连接"""
        exchange_class = getattr(ccxtpro, self.exchange_id)
        self.exchange = exchange_class(self.config)
        await self.exchange.load_markets()
        
    async def subscribe_ohlcv(self, symbol: str, timeframe: str, callback: Callable):
        """订阅K线数据"""
        key = f"ohlcv:{symbol}:{timeframe}"
        self._subscriptions[key] = callback
        
        asyncio.create_task(self._watch_ohlcv(symbol, timeframe, callback))
        
    async def _watch_ohlcv(self, symbol: str, timeframe: str, callback: Callable):
        """监听K线更新"""
        while self._running:
            try:
                ohlcv = await self.exchange.watch_ohlcv(symbol, timeframe)
                callback(ohlcv)
            except Exception as e:
                print(f"WebSocket OHLCV error: {e}")
                await self._handle_reconnect()
                
    async def _handle_reconnect(self):
        """处理重连"""
        delay = self._reconnect_delay
        while self._running:
            try:
                await asyncio.sleep(delay)
                await self._connect()
                # 恢复订阅
                for key, callback in self._subscriptions.items():
                    parts = key.split(":")
                    if parts[0] == "ohlcv":
                        asyncio.create_task(
                            self._watch_ohlcv(parts[1], parts[2], callback)
                        )
                break
            except Exception as e:
                print(f"Reconnect failed: {e}")
                delay = min(delay * 2, self._max_reconnect_delay)
```

### 5.2 多线程管理模块设计

```python
# ccxt/threading.py
import threading
import queue
from typing import Optional, Any
from dataclasses import dataclass
from datetime import datetime

@dataclass
class DataUpdate:
    """数据更新消息"""
    symbol: str
    timestamp: int
    data: Any
    data_type: str  # 'ohlcv', 'ticker', 'trade'

class ThreadedDataManager:
    """多线程数据管理器"""
    
    def __init__(self, store, update_interval: float = 1.0):
        self.store = store
        self.update_interval = update_interval
        self._queue = queue.Queue(maxsize=1000)
        self._thread = None
        self._running = False
        self._symbols = []
        self._timeframes = {}
        
    def add_symbol(self, symbol: str, timeframe: str):
        """添加要监控的交易对"""
        self._symbols.append(symbol)
        self._timeframes[symbol] = timeframe
        
    def start(self):
        """启动数据线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()
        
    def stop(self):
        """停止数据线程"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            
    def get_update(self, timeout: float = None) -> Optional[DataUpdate]:
        """获取数据更新"""
        try:
            return self._queue.get(block=True, timeout=timeout)
        except queue.Empty:
            return None
            
    def _update_loop(self):
        """数据更新循环"""
        import time
        while self._running:
            try:
                for symbol in self._symbols:
                    timeframe = self._timeframes.get(symbol, '1h')
                    granularity = self.store.get_granularity(
                        self._parse_timeframe(timeframe)
                    )
                    
                    ohlcv = self.store.fetch_ohlcv(
                        symbol, 
                        timeframe=granularity,
                        since=None,
                        limit=1
                    )
                    
                    if ohlcv:
                        update = DataUpdate(
                            symbol=symbol,
                            timestamp=ohlcv[-1][0],
                            data=ohlcv[-1],
                            data_type='ohlcv'
                        )
                        
                        try:
                            self._queue.put_nowait(update)
                        except queue.Full:
                            # 队列满，丢弃旧数据
                            try:
                                self._queue.get_nowait()
                                self._queue.put_nowait(update)
                            except:
                                pass
                                
                time.sleep(self.update_interval)
                
            except Exception as e:
                print(f"Data update error: {e}")
                time.sleep(self.update_interval)
```

### 5.3 限流管理模块设计

```python
# ccxt/ratelimit.py
import time
import threading
from functools import wraps
from typing import Callable

class RateLimiter:
    """API限流管理器"""
    
    def __init__(self, requests_per_minute: int = 1200):
        self.rpm = requests_per_minute
        self.request_times = []
        self._lock = threading.Lock()
        
    def acquire(self):
        """获取调用许可，如果需要则等待"""
        with self._lock:
            now = time.time()
            
            # 清除1分钟前的记录
            cutoff = now - 60
            self.request_times = [t for t in self.request_times if t > cutoff]
            
            # 检查是否需要等待
            if len(self.request_times) >= self.rpm:
                wait_time = 60 - (now - self.request_times[0])
                if wait_time > 0:
                    time.sleep(wait_time)
                    now = time.time()
                    self.request_times = []
                    
            # 记录本次请求
            self.request_times.append(now)
            
    def get_wait_time(self) -> float:
        """获取建议等待时间(秒)"""
        with self._lock:
            now = time.time()
            cutoff = now - 60
            self.request_times = [t for t in self.request_times if t > cutoff]
            
            if len(self.request_times) >= self.rpm:
                return 60 - (now - self.request_times[0])
            return 0


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,)
):
    """带指数退避的重试装饰器
    
    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟时间(秒)
        max_delay: 最大延迟时间(秒)
        exceptions: 需要重试的异常类型
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries - 1:
                        raise
                        
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    print(f"Retry {attempt + 1}/{max_retries} after {delay:.2f}s: {e}")
                    time.sleep(delay)
                    
            raise last_exception
            
        return wrapper
    return decorator
```

### 5.4 Bracket订单模块设计

```python
# ccxt/orders/bracket.py
import backtrader as bt
from typing import Dict, Optional
from dataclasses import dataclass, field
from enum import Enum

class BracketState(Enum):
    PENDING = "pending"      # 等待入场成交
    ACTIVE = "active"        # 入场成交，保护订单激活
    STOPPED = "stopped"      # 止损成交
    TARGETED = "targeted"    # 止盈成交
    CANCELLED = "cancelled"  # 已取消

@dataclass
class BracketOrder:
    """Bracket订单组合"""
    bracket_id: str
    entry_order: object
    stop_order: object
    limit_order: object
    state: BracketState = BracketState.PENDING
    entry_fill_price: float = 0.0
    
class BracketOrderManager:
    """Bracket订单管理器"""
    
    def __init__(self, broker):
        self.broker = broker
        self.brackets: Dict[str, BracketOrder] = {}
        self._order_to_bracket: Dict[str, str] = {}  # order_id -> bracket_id
        self._next_bracket_id = 0
        
    def create_bracket(
        self,
        data,
        size: float,
        entry_price: float,
        stop_price: float,
        limit_price: float,
        entry_type: int = bt.Order.Limit
    ) -> BracketOrder:
        """创建Bracket订单
        
        Args:
            data: 数据源
            size: 数量
            entry_price: 入场价格
            stop_price: 止损价格
            limit_price: 止盈价格
            entry_type: 入场订单类型
            
        Returns:
            BracketOrder: Bracket订单对象
        """
        bracket_id = f"bracket_{self._next_bracket_id}"
        self._next_bracket_id += 1
        
        # 创建入场订单
        entry_order = self.broker.buy(
            owner=None,
            data=data,
            size=size,
            price=entry_price,
            exectype=entry_type
        )
        
        # 创建止损订单（暂不提交，等入场成交后提交）
        stop_order = None
        limit_order = None
        
        bracket = BracketOrder(
            bracket_id=bracket_id,
            entry_order=entry_order,
            stop_order=stop_order,
            limit_order=limit_order,
            state=BracketState.PENDING
        )
        
        # 保存映射关系
        self.brackets[bracket_id] = bracket
        self._order_to_bracket[entry_order.ccxt_order['id']] = bracket_id
        
        # 保存止损止盈参数
        bracket._stop_price = stop_price
        bracket._limit_price = limit_price
        bracket._size = size
        bracket._data = data
        
        return bracket
        
    def on_order_update(self, order):
        """处理订单更新
        
        Args:
            order: 更新的订单
        """
        order_id = order.ccxt_order.get('id')
        if order_id not in self._order_to_bracket:
            return
            
        bracket_id = self._order_to_bracket[order_id]
        bracket = self.brackets.get(bracket_id)
        if not bracket:
            return
            
        # 检查入场订单是否成交
        if order == bracket.entry_order and order.status == order.Completed:
            self._activate_protection(bracket, order)
            
        # 检查保护订单是否成交
        elif bracket.state == BracketState.ACTIVE:
            if order == bracket.stop_order and order.status == order.Completed:
                self._handle_stop_fill(bracket)
            elif order == bracket.limit_order and order.status == order.Completed:
                self._handle_limit_fill(bracket)
                
    def _activate_protection(self, bracket: BracketOrder, entry_order):
        """激活保护订单"""
        bracket.entry_fill_price = entry_order.executed.price
        bracket.state = BracketState.ACTIVE
        
        # 创建止损订单
        bracket.stop_order = self.broker.sell(
            owner=None,
            data=bracket._data,
            size=bracket._size,
            price=bracket._stop_price,
            exectype=bt.Order.Stop
        )
        self._order_to_bracket[bracket.stop_order.ccxt_order['id']] = bracket.bracket_id
        
        # 创建止盈订单
        bracket.limit_order = self.broker.sell(
            owner=None,
            data=bracket._data,
            size=bracket._size,
            price=bracket._limit_price,
            exectype=bt.Order.Limit
        )
        self._order_to_bracket[bracket.limit_order.ccxt_order['id']] = bracket.bracket_id
        
    def _handle_stop_fill(self, bracket: BracketOrder):
        """处理止损成交"""
        bracket.state = BracketState.STOPPED
        
        # 取消止盈订单
        if bracket.limit_order:
            self.broker.cancel(bracket.limit_order)
            
    def _handle_limit_fill(self, bracket: BracketOrder):
        """处理止盈成交"""
        bracket.state = BracketState.TARGETED
        
        # 取消止损订单
        if bracket.stop_order:
            self.broker.cancel(bracket.stop_order)
            
    def cancel_bracket(self, bracket_id: str):
        """取消Bracket订单"""
        bracket = self.brackets.get(bracket_id)
        if not bracket:
            return
            
        bracket.state = BracketState.CANCELLED
        
        # 取消所有订单
        if bracket.entry_order:
            self.broker.cancel(bracket.entry_order)
        if bracket.stop_order:
            self.broker.cancel(bracket.stop_order)
        if bracket.limit_order:
            self.broker.cancel(bracket.limit_order)
```

---

## 6. 实施计划

### 6.1 阶段划分

#### 第一阶段: 基础增强 (P0) - 预计2周

| 任务 | 描述 | 工时 | 依赖 |
|-----|------|-----|------|
| T1.1 | 实现RateLimiter模块 | 1天 | 无 |
| T1.2 | 实现retry_with_backoff装饰器 | 0.5天 | 无 |
| T1.3 | 实现ThreadedDataManager | 2天 | T1.1 |
| T1.4 | 集成ThreadedDataManager到CCXTFeed | 1天 | T1.3 |
| T1.5 | 实现WebSocketManager基础版 | 3天 | 无 |
| T1.6 | 集成WebSocket到CCXTFeed | 2天 | T1.5 |
| T1.7 | 单元测试 | 1天 | T1.1-T1.6 |

#### 第二阶段: 订单增强 (P1) - 预计2周

| 任务 | 描述 | 工时 | 依赖 |
|-----|------|-----|------|
| T2.1 | 实现ThreadedOrderManager | 2天 | T1.1 |
| T2.2 | 集成ThreadedOrderManager到CCXTBroker | 1天 | T2.1 |
| T2.3 | 实现BracketOrderManager | 2天 | 无 |
| T2.4 | 集成Bracket订单到CCXTBroker | 1天 | T2.3 |
| T2.5 | 实现ConnectionManager | 2天 | T1.5 |
| T2.6 | 实现自动重连和回填 | 1天 | T2.5 |
| T2.7 | 集成测试 | 1天 | T2.1-T2.6 |

#### 第三阶段: 配置与监控 (P2) - 预计1周

| 任务 | 描述 | 工时 | 依赖 |
|-----|------|-----|------|
| T3.1 | 实现ExchangeConfig模块 | 1天 | 无 |
| T3.2 | 添加主流交易所配置 | 1天 | T3.1 |
| T3.3 | 实现性能监控指标 | 1天 | 无 |
| T3.4 | 文档更新 | 1天 | T3.1-T3.3 |
| T3.5 | 端到端测试 | 1天 | 全部 |

### 6.2 里程碑

| 里程碑 | 日期 | 交付物 |
|-------|------|--------|
| M1 | 第2周末 | 基础增强完成，多线程数据更新可用 |
| M2 | 第4周末 | 订单增强完成，Bracket订单可用 |
| M3 | 第5周末 | 全部功能完成，文档完善 |

---

## 7. 测试计划

### 7.1 单元测试

```python
# tests/test_ccxt_ratelimit.py
import pytest
from backtrader.ccxt.ratelimit import RateLimiter, retry_with_backoff

class TestRateLimiter:
    def test_acquire_under_limit(self):
        limiter = RateLimiter(requests_per_minute=100)
        # 应该立即返回
        start = time.time()
        limiter.acquire()
        elapsed = time.time() - start
        assert elapsed < 0.1
        
    def test_acquire_at_limit(self):
        limiter = RateLimiter(requests_per_minute=2)
        limiter.acquire()
        limiter.acquire()
        # 第三次应该等待
        start = time.time()
        limiter.acquire()
        elapsed = time.time() - start
        assert elapsed >= 55  # 接近60秒

class TestRetryWithBackoff:
    def test_success_no_retry(self):
        call_count = 0
        
        @retry_with_backoff(max_retries=3)
        def success_func():
            nonlocal call_count
            call_count += 1
            return "success"
            
        result = success_func()
        assert result == "success"
        assert call_count == 1
        
    def test_retry_then_success(self):
        call_count = 0
        
        @retry_with_backoff(max_retries=3, base_delay=0.1)
        def fail_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("fail")
            return "success"
            
        result = fail_then_success()
        assert result == "success"
        assert call_count == 3
```

### 7.2 集成测试

```python
# tests/test_ccxt_integration.py
import pytest
import backtrader as bt

class TestCCXTIntegration:
    @pytest.fixture
    def cerebro(self):
        cerebro = bt.Cerebro()
        return cerebro
        
    def test_ccxt_feed_historical(self, cerebro):
        """测试历史数据加载"""
        data = bt.feeds.CCXTFeed(
            exchange='binance',
            currency='USDT',
            config={},
            retries=3,
            dataname='BTC/USDT',
            fromdate=datetime(2024, 1, 1),
            todate=datetime(2024, 1, 7),
            historical=True
        )
        cerebro.adddata(data)
        cerebro.run()
        # 验证数据加载
        assert len(data) > 0
        
    def test_ccxt_broker_order(self, cerebro):
        """测试订单执行"""
        # 需要沙盒环境测试
        pass
```

### 7.3 端到端测试

```python
# tests/test_ccxt_e2e.py
class TestCCXTEndToEnd:
    def test_live_trading_simulation(self):
        """模拟实盘交易流程"""
        cerebro = bt.Cerebro()
        
        # 配置CCXT
        store = CCXTStore(
            exchange='binance',
            currency='USDT',
            config={'sandbox': True},
            retries=3
        )
        
        # 添加数据
        data = store.getdata(
            dataname='BTC/USDT',
            timeframe=bt.TimeFrame.Minutes,
            compression=5
        )
        cerebro.adddata(data)
        
        # 设置Broker
        cerebro.setbroker(store.getbroker())
        
        # 添加策略
        cerebro.addstrategy(SimpleTestStrategy)
        
        # 运行
        cerebro.run()
```

---

## 8. 使用示例

### 8.1 基础回测

```python
import backtrader as bt
from datetime import datetime

class SMAStrategy(bt.Strategy):
    params = (('period', 20),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(period=self.p.period)
        
    def next(self):
        if not self.position:
            if self.data.close[0] > self.sma[0]:
                self.buy(size=0.01)
        else:
            if self.data.close[0] < self.sma[0]:
                self.close()

# 创建Cerebro
cerebro = bt.Cerebro()

# 添加CCXT数据
data = bt.feeds.CCXTFeed(
    exchange='binance',
    currency='USDT',
    config={},
    retries=3,
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=60,
    fromdate=datetime(2024, 1, 1),
    todate=datetime(2024, 6, 30),
    historical=True
)
cerebro.adddata(data)

# 添加策略
cerebro.addstrategy(SMAStrategy)

# 运行回测
result = cerebro.run()
cerebro.plot()
```

### 8.2 实盘交易

```python
import backtrader as bt

class LiveStrategy(bt.Strategy):
    def __init__(self):
        self.order = None
        
    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                print(f'买入成交: {order.executed.price}')
            else:
                print(f'卖出成交: {order.executed.price}')
        self.order = None
        
    def next(self):
        if self.order:
            return
            
        # 实盘交易逻辑
        if not self.position:
            if self.should_buy():
                self.order = self.buy(size=0.01)
        else:
            if self.should_sell():
                self.order = self.close()

# 创建Cerebro
cerebro = bt.Cerebro()

# 创建Store
store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'your_api_key',
        'secret': 'your_secret',
        'enableRateLimit': True,
    },
    retries=5,
    sandbox=True  # 先在沙盒测试
)

# 设置Broker
cerebro.setbroker(store.getbroker())

# 添加实时数据
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=5,
    historical=False
)
cerebro.adddata(data)

# 添加策略
cerebro.addstrategy(LiveStrategy)

# 运行实盘
cerebro.run()
```

### 8.3 Bracket订单使用

```python
import backtrader as bt
from backtrader.ccxt.orders.bracket import BracketOrderManager

class BracketStrategy(bt.Strategy):
    def __init__(self):
        self.bracket_mgr = BracketOrderManager(self.broker)
        self.sma = bt.indicators.SMA(period=20)
        
    def notify_order(self, order):
        # 传递订单更新给Bracket管理器
        self.bracket_mgr.on_order_update(order)
        
    def next(self):
        if not self.position:
            if self.data.close[0] > self.sma[0]:
                # 创建Bracket订单
                entry = self.data.close[0]
                stop = entry * 0.97   # 3%止损
                limit = entry * 1.05  # 5%止盈
                
                bracket = self.bracket_mgr.create_bracket(
                    data=self.data,
                    size=0.01,
                    entry_price=entry,
                    stop_price=stop,
                    limit_price=limit
                )
                print(f'创建Bracket订单: {bracket.bracket_id}')
```

---

## 9. 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|-----|------|-----|---------|
| CCXT Pro许可问题 | WebSocket功能无法使用 | 中 | 提供REST轮询降级方案 |
| 交易所API变更 | 功能异常 | 中 | 配置化适配，快速响应 |
| 多线程竞态条件 | 数据不一致 | 中 | 充分测试，使用线程安全结构 |
| 网络不稳定 | 订单丢失 | 低 | 订单持久化，状态恢复机制 |

---

## 10. 附录

### 10.1 交易所支持矩阵

| 交易所 | REST API | WebSocket | Bracket订单 | 测试状态 |
|-------|----------|-----------|-------------|---------|
| Binance | ✅ | ✅ | ✅ | 待测试 |
| OKX | ✅ | ✅ | ✅ | 待测试 |
| Bybit | ✅ | ✅ | ✅ | 待测试 |
| Coinbase | ✅ | ✅ | ❌ | 待测试 |
| Kraken | ✅ | ✅ | ❌ | 待测试 |

### 10.2 参考资料

- [CCXT文档](https://docs.ccxt.com/)
- [CCXT Pro文档](https://github.com/ccxt/ccxt/wiki/ccxt.pro)
- [Backtrader文档](https://www.backtrader.com/docu/)
- [作者博客](https://yunjinqi.blog.csdn.net/)

### 10.3 术语表

| 术语 | 定义 |
|-----|------|
| OCO | One-Cancels-Other，一个成交取消另一个 |
| Bracket Order | 包含入场、止损、止盈的订单组合 |
| Rate Limit | API调用频率限制 |
| Backfill | 回填缺失的历史数据 |
| WebSocket | 双向实时通信协议 |

---

---

## 11. 已完成的整合工作

### 11.1 整合概述

已成功将backtrader-crypto项目中的实盘交易代码整合到backtrader中，包括：

| 平台 | Store | Broker | Data Feed | 状态 |
|------|-------|--------|-----------|------|
| CCXT | `ccxtstore.py` | `ccxtbroker.py` | `ccxtfeed.py` | ✅ 已集成 |
| CTP | `ctpstore.py` | `ctpbroker.py` | `ctpdata.py` | ✅ 已集成 |
| Futu | `futustore.py` | `futubroker.py` | `futufeed.py` | ✅ 新增 |

### 11.2 新增文件

#### Futu相关文件（新建）
- `backtrader/stores/futustore.py` - Futu OpenD Store
- `backtrader/brokers/futubroker.py` - Futu Broker
- `backtrader/feeds/futufeed.py` - Futu Data Feed

### 11.3 更新的文件

#### __init__.py 更新
- `backtrader/stores/__init__.py` - 添加CCXTStore、CTPStore、FutuStore导入
- `backtrader/brokers/__init__.py` - 添加CCXTBroker、CTPBroker、FutuBroker导入
- `backtrader/feeds/__init__.py` - 添加CCXTFeed、CTPData、FutuFeed导入

### 11.4 依赖要求

```bash
# CCXT - 加密货币交易所
pip install ccxt

# CTP - 中国期货
pip install ctpbee

# Futu - 港美A股
pip install futu-api
```

### 11.5 使用示例

#### CCXT 加密货币交易
```python
import backtrader as bt

# 创建Store
store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={'apiKey': 'xxx', 'secret': 'xxx'},
    retries=5,
    sandbox=True
)

# 获取Broker和Data
broker = store.getbroker()
data = store.getdata(dataname='BTC/USDT')

cerebro = bt.Cerebro()
cerebro.setbroker(broker)
cerebro.adddata(data)
cerebro.run()
```

#### CTP 中国期货交易
```python
import backtrader as bt

ctp_setting = {
    'CONNECT_INFO': {
        'userid': 'xxx',
        'password': 'xxx',
        'brokerid': 'xxx',
        'md_address': 'xxx',
        'td_address': 'xxx',
    }
}

store = bt.stores.CTPStore(ctp_setting=ctp_setting)
broker = store.getbroker()
data = store.getdata(dataname='rb2501.SHFE')

cerebro = bt.Cerebro()
cerebro.setbroker(broker)
cerebro.adddata(data)
cerebro.run()
```

#### Futu 港美A股交易
```python
import backtrader as bt

store = bt.stores.FutuStore(
    host='127.0.0.1',
    port=11111,
    trd_env=TrdEnv.SIMULATE,
    market=TrdMarket.HK
)

broker = store.getbroker()
data = bt.feeds.FutuFeed(
    dataname='HK.00700',
    store=store,
    timeframe=bt.TimeFrame.Minutes,
    compression=5
)

cerebro = bt.Cerebro()
cerebro.setbroker(broker)
cerebro.adddata(data)
cerebro.run()
```

---

## 12. CCXT增强模块实现

### 12.1 新增模块目录结构

```
backtrader/ccxt/
├── __init__.py           # 模块导出
├── ratelimit.py          # 限流管理器 (CCXT-005)
├── threading.py          # 多线程工具 (CCXT-002, CCXT-003)
├── websocket.py          # WebSocket管理 (CCXT-001)
├── connection.py         # 连接管理 (CCXT-006)
├── config.py             # 交易所配置 (CCXT-007)
└── orders/
    ├── __init__.py
    └── bracket.py        # Bracket订单 (CCXT-004)
```

### 12.2 模块功能说明

| 模块 | 对应需求 | 功能描述 | 状态 |
|------|----------|----------|------|
| `ratelimit.py` | CCXT-005 | RateLimiter限流器、retry_with_backoff重试装饰器 | ✅ 完成 |
| `threading.py` | CCXT-002/003 | ThreadedDataManager、ThreadedOrderManager | ✅ 完成 |
| `websocket.py` | CCXT-001 | CCXTWebSocketManager (需ccxt.pro) | ✅ 完成 |
| `connection.py` | CCXT-006 | ConnectionManager自动重连 | ✅ 完成 |
| `config.py` | CCXT-007 | ExchangeConfig交易所配置 | ✅ 完成 |
| `orders/bracket.py` | CCXT-004 | BracketOrderManager OCO订单 | ✅ 完成 |

### 12.3 使用示例

#### 限流管理器
```python
from backtrader.ccxt import RateLimiter, retry_with_backoff

# 创建限流器
limiter = RateLimiter(requests_per_minute=1200)
limiter.acquire()  # 阻塞直到可以调用

# 重试装饰器
@retry_with_backoff(max_retries=3, base_delay=1.0)
def fetch_data():
    return exchange.fetch_ohlcv(symbol)
```

#### 多线程数据管理
```python
from backtrader.ccxt import ThreadedDataManager

manager = ThreadedDataManager(store, update_interval=1.0)
manager.add_symbol('BTC/USDT', '1h')
manager.start()

# 非阻塞获取更新
update = manager.get_update(timeout=1.0)
if update:
    print(f"Got {update.data_type} for {update.symbol}")
```

#### Bracket订单
```python
from backtrader.ccxt import BracketOrderManager

bracket_mgr = BracketOrderManager(broker)

# 创建Bracket订单 (入场 + 止损 + 止盈)
bracket = bracket_mgr.create_bracket(
    data=data,
    size=0.01,
    entry_price=50000,
    stop_price=49000,   # 止损
    limit_price=52000,  # 止盈
    side="buy"
)

# 在notify_order中处理OCO逻辑
def notify_order(self, order):
    bracket_mgr.on_order_update(order)
```

#### 交易所配置
```python
from backtrader.ccxt import ExchangeConfig

# 获取交易所特定的订单类型
order_type = ExchangeConfig.get_order_type('binance', bt.Order.StopLimit)

# 获取时间框架映射
timeframe = ExchangeConfig.get_timeframe('binance', (bt.TimeFrame.Minutes, 60))

# 获取交易所默认参数
params = ExchangeConfig.get_params('binance')
```

---

## 13. 模块集成完成

### 13.1 CCXTStore 集成

增强模块已集成到 `ccxtstore.py`：
- **RateLimiter**: 自动限流，避免触发交易所API限制
- **AdaptiveRateLimiter**: 根据API响应自适应调整请求频率
- **ConnectionManager**: 连接健康监控和自动重连
- **ExchangeConfig**: 自动应用交易所默认配置

新增参数：
```python
store = CCXTStore(
    exchange='binance',
    currency='USDT',
    config={...},
    retries=5,
    use_rate_limiter=True,        # 启用智能限流
    use_connection_manager=False   # 启用连接管理
)
```

### 13.2 CCXTBroker 集成

增强模块已集成到 `ccxtbroker.py`：
- **ThreadedOrderManager**: 后台线程检查订单状态
- **BracketOrderManager**: OCO订单支持

新增功能：
```python
broker = store.getbroker(use_threaded_order_manager=True)

# 创建Bracket订单
bracket = broker.create_bracket_order(
    data=data,
    size=0.01,
    entry_price=50000,
    stop_price=49000,
    limit_price=52000,
    side="buy"
)
```

### 13.3 CCXTFeed 集成

增强模块已集成到 `ccxtfeed.py`：
- **ThreadedDataManager**: 后台线程获取数据
- **CCXTWebSocketManager**: WebSocket实时数据流

新增参数：
```python
data = CCXTFeed(
    dataname='BTC/USDT',
    use_websocket=False,      # 启用WebSocket
    use_threaded_data=False,  # 启用后台数据线程
    ...
)
```

### 13.4 单元测试

测试文件: `tests/test_ccxt_enhancements.py`

覆盖测试类:
- `TestRateLimiter`
- `TestRetryWithBackoff`
- `TestExchangeConfig`
- `TestThreadedDataManager`
- `TestThreadedOrderManager`
- `TestConnectionManager`
- `TestBracketOrder`
- `TestBracketOrderManager`

---

## 文档历史

| 版本 | 日期 | 作者 | 变更说明 |
|-----|------|------|---------|
| v1.0 | 2026-01-20 | 开发团队 | 初始版本 |
| v1.1 | 2026-01-20 | 开发团队 | 添加Futu整合，更新已完成工作 |
| v1.2 | 2026-01-20 | 开发团队 | 完成CCXT增强模块实现 |
| v1.3 | 2026-01-20 | 开发团队 | 完成模块集成和单元测试 |
