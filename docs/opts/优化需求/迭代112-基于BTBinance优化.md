### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/BTBinance
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### BTBinance项目简介
BTBinance是Binance与backtrader的另一个集成项目，具有以下核心特点：
- **Binance集成**: Binance API集成
- **实时交易**: 实时交易支持
- **WebSocket**: WebSocket数据流
- **现货合约**: 现货和合约支持
- **账户管理**: 账户信息管理
- **订单同步**: 订单状态同步

### 重点借鉴方向
1. **API封装**: API封装设计
2. **WebSocket**: WebSocket实现
3. **数据同步**: 数据同步机制
4. **订单管理**: 订单管理实现
5. **错误处理**: 错误处理机制
6. **重连机制**: 断线重连机制

---

## 项目对比分析

### Backtrader vs BTBinance

| 维度 | Backtrader原生 | BTBinance |
|------|---------------|-----------|
| **数据源** | 本地数据/CSV | Binance API + WebSocket |
| **实时交易** | 无原生支持 | 完整实时交易 |
| **API封装** | 无 | 统一API封装层 |
| **WebSocket** | 无 | 完整WebSocket支持 |
| **订单同步** | 无 | 实时订单状态同步 |
| **错误处理** | 基础 | 完善重试和重连机制 |
| **账户管理** | 模拟账户 | 实时账户信息 |
| **订单类型** | 基础类型 | 市价/限价/止损/止盈/OCO |
| **数据回填** | 不支持 | 历史数据自动回填 |
| **多交易所** | 需自行实现 | 需自行扩展 |

### Backtrader可借鉴的优势

1. **统一API封装层**：标准化的交易所接口设计
2. **WebSocket数据流**：实时数据推送机制
3. **订单生命周期管理**：完整的状态同步
4. **错误恢复机制**：重试、重连、降级策略
5. **数据同步策略**：历史回填+实时推送
6. **心跳保持机制**：连接状态监控

---

## 功能需求文档

### FR-01 交易所API抽象层 [高优先级]

**描述**: 建立统一的交易所API抽象接口

**需求**:
- FR-01.1 定义交易所抽象基类 `ExchangeAPI`
- FR-01.2 统一的方法命名规范（fetch_/create_/cancel_）
- FR-01.3 标准化的订单类型映射
- FR-01.4 标准化的数据格式转换
- FR-01.5 多交易所支持架构

**验收标准**:
- 定义至少10个标准API方法
- 支持3+家交易所实现
- 数据格式统一

### FR-02 WebSocket数据源 [高优先级]

**描述**: 实现基于WebSocket的实时数据源

**需求**:
- FR-02.1 WebSocket连接管理
- FR-02.2 K线数据订阅
- FR-02.3 实时数据推送
- FR-02.4 历史数据回填
- FR-02.5 多数据源并行订阅

**验收标准**:
- 支持5+种K线周期
- 支持多交易对订阅
- 数据延迟<100ms

### FR-03 实时交易经纪人 [高优先级]

**描述**: 实现支持实时交易的经纪人

**需求**:
- FR-03.1 实时下单接口
- FR-03.2 订单状态查询
- FR-03.3 订单取消接口
- FR-03.4 账户信息查询
- FR-03.5 持仓信息查询

**验收标准**:
- 订单延迟<500ms
- 支持市价/限价订单
- 状态更新实时

### FR-04 订单同步系统 [高优先级]

**描述**: 实现订单状态实时同步机制

**需求**:
- FR-04.1 客户端订单ID映射
- FR-04.2 订单状态实时推送
- FR-04.3 订单确认机制
- FR-04.4 成交推送处理
- FR-04.5 订单过期处理

**验收标准**:
- 状态同步延迟<1s
- 支持订单状态查询
- 异常状态告警

### FR-05 错误处理框架 [高优先级]

**描述**: 建立完善的错误处理和恢复机制

**需求**:
- FR-05.1 API限速处理
- FR-05.2 网络异常重试
- FR-05.3 WebSocket断线重连
- FR-05.4 数据获取降级
- FR-05.5 错误日志记录

**验收标准**:
- 自动重试3次
- 重连成功率>95%
- 降级策略有效

### FR-06 心跳保持机制 [中优先级]

**描述**: 实现连接心跳检测和保持

**需求**:
- FR-06.1 心跳检测机制
- FR-06.2 服务器时间同步
- FR-06.3 连接状态监控
- FR-06.4 心跳丢失处理
- FR-06.5 自动重连触发

**验收标准**:
- 心跳间隔30s
- 超时自动重连
- 状态可查询

### FR-07 复杂订单类型 [中优先级]

**描述**: 支持止损、止盈、OCO等复杂订单

**需求**:
- FR-07.1 止损订单
- FR-07.2 止盈订单
- FR-07.3 冰山订单
- FR-07.4 OCO订单
- FR-07.5 括号订单

**验收标准**:
- 支持5种复杂订单
- 自动关联处理
- 条件触发准确

### FR-08 账户数据管理 [中优先级]

**描述**: 实时账户数据管理

**需求**:
- FR-08.1 余额查询
- FR-08.2 持仓查询
- FR-08.3 资产查询
- FR-08.4 账户变动推送
- FR-08.5 历史订单查询

**验收标准**:
- 数据实时更新
- 支持多币种查询
- 历史记录可追溯

---

## 设计文档

### 1. 交易所API抽象层设计

```python
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import asyncio

class OrderType(Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    OCO = "oco"

class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"

class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"

@dataclass
class OrderInfo:
    """订单信息"""
    order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    avg_price: float = 0.0
    fee: float = 0.0
    timestamp: Optional[int] = None
    info: Dict[str, Any] = None

class ExchangeAPI(ABC):
    """交易所API抽象基类"""

    def __init__(self, api_key: str = None, api_secret: str = None,
                 sandbox: bool = False, enable_rate_limit: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox
        self.enable_rate_limit = enable_rate_limit
        self.session = None

    @abstractmethod
    def fetch_balance(self) -> Dict[str, Dict[str, float]]:
        """
        获取账户余额

        Returns:
            {
                'BTC': {'free': 1.5, 'used': 0.5, 'total': 2.0},
                'USDT': {'free': 1000, 'used': 0, 'total': 1000}
            }
        """
        pass

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """获取行情数据"""
        pass

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str,
                     since: Optional[int] = None, limit: int = 1000) -> List[List]:
        """
        获取K线数据

        Args:
            symbol: 交易对
            timeframe: 时间周期
            since: 起始时间戳
            limit: 数量限制

        Returns:
            [[timestamp, open, high, low, close, volume], ...]
        """
        pass

    @abstractmethod
    def create_order(self, symbol: str, order_type: OrderType,
                    side: OrderSide, quantity: float,
                    price: Optional[float] = None,
                    stop_price: Optional[float] = None,
                    client_order_id: Optional[str] = None,
                    **kwargs) -> OrderInfo:
        """创建订单"""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """取消订单"""
        pass

    @abstractmethod
    def cancel_all_orders(self, symbol: str) -> Dict[str, Any]:
        """取消所有订单"""
        pass

    @abstractmethod
    def fetch_order(self, order_id: str, symbol: str) -> OrderInfo:
        """查询订单"""
        pass

    @abstractmethod
    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[OrderInfo]:
        """查询未成交订单"""
        pass

    @abstractmethod
    def fetch_positions(self) -> Dict[str, Dict[str, float]]:
        """获取持仓信息"""
        pass

    async def subscribe_ticker(self, symbols: List[str],
                              callback: callable) -> None:
        """订阅行情推送"""
        pass

    async def subscribe_kline(self, symbols: List[str],
                             timeframe: str,
                             callback: callable) -> None:
        """订阅K线推送"""
        pass

    async def subscribe_account(self, callback: callable) -> None:
        """订阅账户推送"""
        pass

    async def subscribe_order(self, callback: callable) -> None:
        """订阅订单推送"""
        pass
```

### 2. WebSocket连接管理器设计

```python
import asyncio
import websockets
import json
from typing import Callable, Optional, Dict, Any, Set
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class ConnectionState(Enum):
    """连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"

class WebSocketManager:
    """WebSocket连接管理器"""

    def __init__(self,
                 url: str,
                 ping_interval: int = 30,
                 ping_timeout: int = 10,
                 max_reconnect_attempts: int = 5):
        """
        Args:
            url: WebSocket URL
            ping_interval: 心跳间隔（秒）
            ping_timeout: 心跳超时（秒）
            max_reconnect_attempts: 最大重连次数
        """
        self.url = url
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.max_reconnect_attempts = max_reconnect_attempts

        self.state = ConnectionState.DISCONNECTED
        self.websocket = None
        self.reconnect_count = 0

        # 消息处理器
        self.message_handlers: Dict[str, Callable] = {}
        self.subscriptions: Set[str] = set()

        # 心跳任务
        self._ping_task = None
        self._heartbeat_task = None

    async def connect(self) -> None:
        """建立连接"""
        if self.state in [ConnectionState.CONNECTED, ConnectionState.RECONNECTING]:
            return

        self.state = ConnectionState.CONNECTING
        logger.info(f"Connecting to {self.url}")

        try:
            self.websocket = await websockets.connect(
                self.url,
                ping_interval=self.ping_interval,
                ping_timeout=self.ping_timeout
            )
            self.state = ConnectionState.CONNECTED
            self.reconnect_count = 0

            # 启动消息接收循环
            asyncio.create_task(self._receive_loop())

            logger.info(f"Connected to {self.url}")

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            await self._handle_disconnect()

    async def _receive_loop(self) -> None:
        """消息接收循环"""
        try:
            async for message in self.websocket:
                await self._process_message(message)

        except websockets.exceptions.ConnectionClosed:
            logger.warning("Connection closed")
            await self._handle_disconnect()

        except Exception as e:
            logger.error(f"Receive error: {e}")
            await self._handle_disconnect()

    async def _process_message(self, message: str) -> None:
        """处理接收到的消息"""
        try:
            data = json.loads(message)
            event_type = data.get('e', data.get('event', None))

            if event_type and event_type in self.message_handlers:
                await self.message_handlers[event_type](data)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message: {e}")

    async def _handle_disconnect(self) -> None:
        """处理断线"""
        self.state = ConnectionState.DISCONNECTED

        if self.reconnect_count < self.max_reconnect_attempts:
            self.state = ConnectionState.RECONNECTING
            self.reconnect_count += 1

            # 指数退避重连
            wait_time = min(2 ** self.reconnect_count, 60)
            logger.info(f"Reconnecting in {wait_time}s... (attempt {self.reconnect_count})")
            await asyncio.sleep(wait_time)

            await self.connect()
        else:
            logger.error("Max reconnect attempts reached")
            self.state = ConnectionState.STOPPED

    def register_handler(self, event_type: str,
                         handler: Callable) -> None:
        """注册消息处理器"""
        self.message_handlers[event_type] = handler

    async def subscribe(self, streams: List[str]) -> None:
        """订阅数据流"""
        if self.state != ConnectionState.CONNECTED:
            raise ConnectionError("Not connected")

        for stream in streams:
            if stream not in self.subscriptions:
                subscription_msg = {
                    "method": "SUBSCRIBE",
                    "params": [stream],
                    "id": stream
                }
                await self.websocket.send(json.dumps(subscription_msg))
                self.subscriptions.add(stream)
                logger.info(f"Subscribed to {stream}")

    async def unsubscribe(self, streams: List[str]) -> None:
        """取消订阅"""
        for stream in streams:
            if stream in self.subscriptions:
                subscription_msg = {
                    "method": "UNSUBSCRIBE",
                    "params": [stream],
                    "id": stream
                }
                await self.websocket.send(json.dumps(subscription_msg))
                self.subscriptions.discard(stream)
                logger.info(f"Unsubscribed from {stream}")

    async def send(self, data: Dict[str, Any]) -> None:
        """发送消息"""
        if self.state != ConnectionState.CONNECTED:
            raise ConnectionError("Not connected")

        await self.websocket.send(json.dumps(data))

    async def close(self) -> None:
        """关闭连接"""
        self.state = ConnectionState.STOPPED
        if self.websocket:
            await self.websocket.close()
        logger.info("WebSocket connection closed")
```

### 3. 实时数据源设计

```python
import backtrader as bt
from typing import Dict, List, Optional, Any
from datetime import datetime
import asyncio
import pandas as pd
import numpy as np
from collections import deque

class LiveDataSource(bt.feed.DataBase):
    """实时数据源基类"""

    params = (
        ('symbol', None),  # 交易对
        ('timeframe', '1m'),  # K线周期
        ('compression', 1),  # 数据压缩
        ('history_bars', 100),  # 历史数据数量
        ('backfill', True),  # 是否回填历史数据
    )

    def __init__(self):
        super().__init__()
        self.api = None  # 交易所API实例
        self.ws_manager = None  # WebSocket管理器
        self._store = deque()  # 数据存储

        # 状态
        self._live = False
        self._last_timestamp = None

    def start(self) -> None:
        """启动数据源"""
        self._live = True

        # 获取历史数据
        if self.p.backfill:
            asyncio.create_task(self._fetch_history())

        # 启动WebSocket连接
        asyncio.create_task(self._start_websocket())

    def stop(self) -> None:
        """停止数据源"""
        self._live = False
        if self.ws_manager:
            asyncio.create_task(self.ws_manager.close())

    async def _fetch_history(self) -> None:
        """获取历史数据"""
        symbol = self.p.symbol
        timeframe = self.p.timeframe
        limit = self.p.history_bars

        try:
            ohlcv = await self.api.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit
            )

            # 转换为backtrader格式
            for bar in ohlcv:
                timestamp, open_, high, low, close, volume = bar
                dt = datetime.fromtimestamp(timestamp / 1000)
                self._store.append((dt, open_, high, low, close, volume))

            logger.info(f"Fetched {len(ohlcv)} history bars for {symbol}")

        except Exception as e:
            logger.error(f"Failed to fetch history: {e}")

    async def _start_websocket(self) -> None:
        """启动WebSocket连接"""
        if not self.ws_manager:
            return

        # 注册K线数据处理器
        self.ws_manager.register_handler('kline', self._handle_kline)

        await self.ws_manager.connect()

        # 订阅K线数据
        await self.ws_manager.subscribe([
            f"{self.p.symbol}@kline_{self.p.timeframe}"
        ])

    async def _handle_kline(self, data: Dict[str, Any]) -> None:
        """处理K线推送"""
        if not self._live:
            return

        kline = data.get('k', {})
        if not kline:
            return

        # 解析K线数据
        timestamp = kline.get('t', 0)
        open_ = kline.get('o', 0)
        high = kline.get('h', 0)
        low = kline.get('l', 0)
        close = kline.get('c', 0)
        volume = kline.get('v', 0)

        # 更新最后一个bar或创建新bar
        await self._update_bar(timestamp, open_, high, low, close, volume)

    async def _update_bar(self, timestamp: int, open_: float,
                         high: float, low: float, close: float,
                         volume: float) -> None:
        """更新bar数据"""
        dt = datetime.fromtimestamp(timestamp / 1000)

        # 如果是新时间周期，添加新bar
        if self._last_timestamp != dt:
            self.lines.datetime[0] = bt.date2num(dt)
            self.lines.open[0] = open_
            self.lines.high[0] = high
            self.lines.low[0] = low
            self.lines.close[0] = close
            self.lines.volume[0] = volume

            self._last_timestamp = dt

            # 通知backtrader有新数据
            self.put_notification()

        else:
            # 更新当前bar（同一分钟内的数据更新）
            self.lines.high[0] = max(self.lines.high[0], high)
            self.lines.low[0] = min(self.lines.low[0], low)
            self.lines.close[0] = close
            self.lines.volume[0] += volume

    def hasnext(self) -> bool:
        """检查是否有数据"""
        return len(self._store) > 0 or self._live

    def next(self) -> None:
        """获取下一个数据点"""
        # 从存储中获取数据
        if self._store:
            dt, open_, high, low, close, volume = self._store.popleft()

            self.lines.datetime[0] = bt.date2num(dt)
            self.lines.open[0] = open_
            self.lines.high[0] = high
            self.lines.low[0] = low
            self.lines.close[0] = close
            self.lines.volume[0] = volume
```

### 4. 实时交易经纪人设计

```python
import backtrader as bt
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import asyncio
import uuid

@dataclass
class OrderMapping:
    """订单映射"""
    bt_order: bt.Order
    exchange_order_id: str
    client_order_id: str
    symbol: str
    status: OrderStatus

class LiveBroker(bt.Broker):
    """实时交易经纪人"""

    params = (
        ('cash', 10000.0),
        ('commission', 0.001),
        ('slippage', 0.0005),
    )

    def __init__(self):
        super().__init__()

        self.api = None  # 交易所API实例
        self.ws_manager = None  # WebSocket管理器

        # 订单管理
        self._order_mapping: Dict[str, OrderMapping] = {}
        self._pending_orders: Dict[str, bt.Order] = {}
        self._open_orders: Dict[str, OrderMapping] = {}

        # 账户信息
        self._balance = {}
        self._positions = {}

    async def start(self) -> None:
        """启动经纪人"""
        # 启动WebSocket连接
        if self.ws_manager:
            await self.ws_manager.connect()

            # 注册账户推送处理器
            self.ws_manager.register_handler('outboundAccountInfo', self._handle_account_update)
            self.ws_manager.register_handler('executionReport', self._handle_execution_report)

            # 订阅账户和订单推送
            await self.ws_manager.subscribe(['account', 'order'])

            # 获取初始账户信息
            await self._sync_account()

    async def _sync_account(self) -> None:
        """同步账户信息"""
        balance = await self.api.fetch_balance()
        positions = await self.api.fetch_positions()

        self._balance = balance
        self._positions = positions

        # 更新backtrader账户状态
        cash = balance.get(self._get_quote_currency(), {}).get('free', 0)
        self.set_cash(cash)

    async def _handle_account_update(self, data: Dict[str, Any]) -> None:
        """处理账户更新推送"""
        balance_data = data.get('a', {})
        if balance_data:
            # 更新余额
            for asset, info in balance_data.items():
                self._balance[asset] = {
                    'free': float(info.get('f', 0)),
                    'used': float(info.get('l', 0))
                }

            # 通知策略
            self._notify_account_update()

    async def _handle_execution_report(self, data: Dict[str, Any]) -> None:
        """处理订单执行报告"""
        order_data = data.get('o', {})
        if not order_data:
            return

        client_order_id = order_data.get('c')
        exchange_order_id = order_data.get('orderId')
        order_status = self._map_order_status(order_data.get('X'))

        # 更新订单状态
        if client_order_id in self._open_orders:
            mapping = self._open_orders[client_order_id]
            mapping.status = order_status
            mapping.exchange_order_id = exchange_order_id

            # 更新成交信息
            if order_status == OrderStatus.CLOSED:
                mapping.bt_order.executed_size = order_data.get('z', 0)
                mapping.bt_order.executed_price = order_data.get('L', 0)

            # 通知策略
            self._notify_order_update(mapping)

    def submit_order(self, order: bt.Order) -> None:
        """提交订单"""
        # 生成客户端订单ID
        client_order_id = self._generate_client_id(order)

        # 构建订单参数
        order_params = {
            'symbol': order.data._name,
            'type': self._map_order_type(order.exectype),
            'side': 'buy' if order.isbuy() else 'sell',
            'quantity': order.size,
            'client_order_id': client_order_id,
        }

        if order.exectype == bt.Order.Limit:
            order_params['price'] = order.created.price
        elif order.exectype == bt.Order.Stop:
            order_params['stopPrice'] = order.created.pricelimit

        # 存储待处理订单
        self._pending_orders[client_order_id] = order

        # 异步提交
        asyncio.create_task(self._execute_order(order, order_params))

    async def _execute_order(self, order: bt.Order,
                           order_params: Dict[str, Any]) -> None:
        """执行订单"""
        client_order_id = order_params['client_order_id']

        try:
            order_info = await self.api.create_order(**order_params)

            # 创建订单映射
            mapping = OrderMapping(
                bt_order=order,
                exchange_order_id=order_info.order_id,
                client_order_id=client_order_id,
                symbol=order_params['symbol'],
                status=OrderStatus.OPEN
            )

            self._open_orders[client_order_id] = mapping

            # 移除待处理订单
            if client_order_id in self._pending_orders:
                del self._pending_orders[client_order_id]

        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            # 通知订单失败
            if client_order_id in self._pending_orders:
                order = self._pending_orders[client_order_id]
                order.reject()

    def cancel_order(self, order: bt.Order) -> None:
        """取消订单"""
        if order.ref in self._open_orders:
            mapping = self._open_orders[order.ref]

            # 异步取消
            asyncio.create_task(self._execute_cancel(mapping))

        else:
            # 待处理订单直接取消
            for client_order_id, pending_order in self._pending_orders.items():
                if pending_order == order:
                    pending_order.cancel()
                    del self._pending_orders[client_order_id]

    async def _execute_cancel(self, mapping: OrderMapping) -> None:
        """执行取消"""
        try:
            await self.api.cancel_order(
                order_id=mapping.exchange_order_id,
                symbol=mapping.symbol
            )

            mapping.status = OrderStatus.CANCELED

            # 从开放订单中移除
            del self._open_orders[mapping.client_order_id]

        except Exception as e:
            logger.error(f"Cancel order failed: {e}")

    def _generate_client_id(self, order: bt.Order) -> str:
        """生成客户端订单ID"""
        # 编入策略信息和订单引用
        strategy_name = getattr(order.owner, '__class__.__name__', 'unknown')
        return f"bt-{strategy_name}-{order.ref}-{uuid.uuid4().hex[:8]}"

    def _map_order_type(self, exectype: bt.Order.OrderType) -> str:
        """映射订单类型"""
        mapping = {
            bt.Order.Market: 'market',
            bt.Order.Limit: 'limit',
            bt.Order.Stop: 'stop_market',
            bt.Order.StopLimit: 'stop',
        }
        return mapping.get(exectype, 'market')

    def _map_order_status(self, exchange_status: str) -> OrderStatus:
        """映射订单状态"""
        status_map = {
            'NEW': OrderStatus.OPEN,
            'PARTIALLY_FILLED': OrderStatus.OPEN,
            'FILLED': OrderStatus.CLOSED,
            'CANCELED': OrderStatus.CANCELED,
            'EXPIRED': OrderStatus.EXPIRED,
            'REJECTED': OrderStatus.REJECTED,
        }
        return status_map.get(exchange_status, OrderStatus.PENDING)

    def _notify_account_update(self) -> None:
        """通知账户更新"""
        # 触发策略的账户更新通知
        pass

    def _notify_order_update(self, mapping: OrderMapping) -> None:
        """通知订单更新"""
        # 更新backtrader订单状态
        if mapping.status == OrderStatus.CLOSED:
            mapping.bt_order.completed()
        elif mapping.status == OrderStatus.CANCELED:
            mapping.bt_order.cancel()
```

### 5. 错误处理和重试机制设计

```python
import asyncio
import random
from typing import Callable, TypeVar, Optional
from functools import wraps
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')

class RetryConfig:
    """重试配置"""
    def __init__(self,
                 max_attempts: int = 3,
                 base_delay: float = 1.0,
                 max_delay: float = 60.0,
                 exponential_base: float = 2.0):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base

class APIError(Exception):
    """API错误"""
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data

def retry_on_failure(config: RetryConfig = None,
                    retry_on: tuple = (Exception,),
                    fallback: Callable = None):
    """错误重试装饰器"""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            cfg = config or RetryConfig()

            for attempt in range(cfg.max_attempts):
                try:
                    return await func(*args, **kwargs)

                except retry_on as e:
                    if attempt == cfg.max_attempts - 1:
                        if fallback:
                            return await fallback(*args, **kwargs)
                        raise

                    # 计算退避时间
                    delay = min(
                        cfg.base_delay * (cfg.exponential_base ** attempt),
                        cfg.max_delay
                    )
                    # 添加随机抖动
                    delay *= (0.5 + random.random())

                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt + 1}/{cfg.max_attempts}): {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    await asyncio.sleep(delay)

        return wrapper
    return decorator

class CircuitBreaker:
    """熔断器"""

    def __init__(self,
                 failure_threshold: int = 5,
                 timeout: int = 60,
                 half_open_attempts: int = 3):
        """
        Args:
            failure_threshold: 失败次数阈值
            timeout: 熔断超时时间（秒）
            half_open_attempts: 半开状态的尝试次数
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.half_open_attempts = half_open_attempts

        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
        self.half_open_success_count = 0

    def record_success(self):
        """记录成功"""
        self.failure_count = 0

        if self.state == 'HALF_OPEN':
            self.half_open_success_count += 1
            if self.half_open_success_count >= self.half_open_attempts:
                self.state = 'OPEN'
                self.half_open_success_count = 0
                logger.info("Circuit breaker recovered to OPEN")

    def record_failure(self):
        """记录失败"""
        self.failure_count += 1
        self.last_failure_time = asyncio.get_event_loop().time()

        if self.failure_count >= self.failure_threshold:
            self.state = 'OPEN'
            logger.warning(f"Circuit breaker OPEN due to {self.failure_count} failures")

    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """通过熔断器调用函数"""
        if self.state == 'OPEN':
            # 检查是否超时
            if (self.last_failure_time and
                asyncio.get_event_loop().time() - self.last_failure_time > self.timeout):
                self.state = 'HALF_OPEN'
                logger.info("Circuit breaker entering HALF_OPEN state")
            else:
                raise APIError(503, "Service unavailable (circuit breaker)")

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result

        except Exception as e:
            self.record_failure()
            raise

class RateLimiter:
    """速率限制器"""

    def __init__(self, calls: int, period: float):
        """
        Args:
            calls: 时间周期内的最大调用次数
            period: 时间周期（秒）
        """
        self.calls = calls
        self.period = period
        self.tokens = calls
        self.last_update = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> None:
        """获取令牌"""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self.last_update

            # 补充令牌
            new_tokens = int(elapsed / self.period * self.calls)
            self.tokens = min(self.calls, self.tokens + new_tokens)
            self.last_update = now

            # 等待可用令牌
            while self.tokens < tokens:
                wait_time = (self.calls - self.tokens) / self.calls * self.period
                await asyncio.sleep(wait_time)

                now = asyncio.get_event_loop().time()
                elapsed = now - self.last_update
                new_tokens = int(elapsed / self.period * self.calls)
                self.tokens = min(self.calls, self.tokens + new_tokens)
                self.last_update = now

            self.tokens -= tokens

class APIClient:
    """API客户端，集成重试、熔断、限流"""

    def __init__(self, exchange_api: ExchangeAPI):
        self.api = exchange_api
        self.circuit_breaker = CircuitBreaker()
        self.rate_limiter = RateLimiter(calls=1200, period=60)  # Binance限制

    @retry_on_failure(
        config=RetryConfig(max_attempts=3, base_delay=1.0),
        retry_on=(APIError, ConnectionError)
    )
    async def fetch_balance(self) -> Dict[str, Dict[str, float]]:
        """获取账户余额（带重试和熔断）"""
        await self.rate_limiter.acquire()
        return await self.circuit_breaker.call(self.api.fetch_balance)

    @retry_on_failure(
        config=RetryConfig(max_attempts=3, base_delay=1.0),
        retry_on=(APIError, ConnectionError)
    )
    async def create_order(self, **kwargs) -> OrderInfo:
        """创建订单（带重试和熔断）"""
        await self.rate_limiter.acquire()
        return await self.circuit_breaker.call(
            self.api.create_order, **kwargs
        )

    # ... 其他方法类似实现
```

### 6. 心跳保持机制设计

```python
import asyncio
import logging
from typing import Optional, Callable
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class HeartbeatMonitor:
    """心跳监控器"""

    def __init__(self,
                 ping_interval: int = 30,
                 pong_timeout: int = 10,
                 server_url: str = None):
        """
        Args:
            ping_interval: ping间隔（秒）
            pong_timeout: pong超时（秒）
            server_url: 服务器URL（用于时间同步）
        """
        self.ping_interval = ping_interval
        self.pong_timeout = pong_timeout
        self.server_url = server_url

        self._running = False
        self._ping_task = None
        self._pong_task = None
        self._time_sync_task = None

        # 回调函数
        self.on_disconnect: Optional[Callable] = None
        self.on_server_time: Optional[Callable] = None

        # 服务器时间偏移
        self.server_time_offset = 0

    async def start(self, ws_manager: WebSocketManager) -> None:
        """启动心跳监控"""
        self._running = True
        self.ws_manager = ws_manager

        # 启动ping任务
        self._ping_task = asyncio.create_task(self._ping_loop())

        # 启动pong监控任务
        self._pong_task = asyncio.create_task(self._pong_loop())

        # 启动时间同步任务
        if self.server_url:
            self._time_sync_task = asyncio.create_task(self._time_sync_loop())

        logger.info("Heartbeat monitor started")

    async def stop(self) -> None:
        """停止心跳监控"""
        self._running = False

        if self._ping_task:
            self._ping_task.cancel()
        if self._pong_task:
            self._pong_task.cancel()
        if self._time_sync_task:
            self._time_sync_task.cancel()

        logger.info("Heartbeat monitor stopped")

    async def _ping_loop(self) -> None:
        """发送ping循环"""
        while self._running:
            try:
                await self.ws_manager.send({'method': 'ping'})
                logger.debug("Ping sent")

                await asyncio.sleep(self.ping_interval)

            except Exception as e:
                logger.error(f"Ping failed: {e}")
                if self.on_disconnect:
                    await self.on_disconnect()
                break

    async def _pong_loop(self) -> None:
        """监控pong响应"""
        while self._running:
            try:
                # 等待pong消息（通过WebSocket消息处理器触发）
                await asyncio.sleep(self.pong_timeout)

                # 如果没收到pong，认为连接断开
                logger.warning("Pong timeout, connection lost")
                if self.on_disconnect:
                    await self.on_disconnect()
                break

            except Exception as e:
                logger.error(f"Pong check failed: {e}")
                break

    def register_pong(self) -> None:
        """注册收到pong"""
        # 重置pong超时计时器
        if self._pong_task:
            self._pong_task.cancel()
            self._pong_task = asyncio.create_task(self._pong_loop())

    async def _time_sync_loop(self) -> None:
        """服务器时间同步循环"""
        while self._running:
            try:
                server_time = await self._get_server_time()
                if server_time:
                    local_time = datetime.now(timezone.utc).timestamp()
                    self.server_time_offset = server_time - local_time

                    if self.on_server_time:
                        await self.on_server_time(server_time)

                await asyncio.sleep(60)  # 每分钟同步一次

            except Exception as e:
                logger.error(f"Time sync failed: {e}")

    async def _get_server_time(self) -> Optional[int]:
        """获取服务器时间"""
        try:
            # 通过API获取服务器时间
            if hasattr(self, 'api'):
                result = await self.api.fetch_server_time()
                return result.get('serverTime')

        except Exception as e:
            logger.error(f"Failed to get server time: {e}")

        return None

    def get_server_time(self) -> int:
        """获取当前服务器时间"""
        return int(datetime.now(timezone.utc).timestamp() + self.server_time_offset)
```

### 7. 复杂订单类型设计

```python
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum
import asyncio

class OrderRelation(Enum):
    """订单关联类型"""
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    PARENT = "parent"
    OCO = "oco"

@dataclass
class ComplexOrder:
    """复杂订单"""
    primary_order: Dict[str, Any]
    secondary_orders: List[Dict[str, Any]]
    relation: OrderRelation

    client_order_ids: List[str] = None

class OrderBuilder:
    """订单构建器"""

    def __init__(self, api: ExchangeAPI):
        self.api = api
        self._order_counter = 0

    def build_stop_loss_order(self, base_order: Dict[str, Any],
                            stop_price: float,
                            quantity: Optional[float] = None,
                            stop_type: str = "STOP_MARKET") -> Dict[str, Any]:
        """构建止损订单"""
        return {
            'symbol': base_order['symbol'],
            'type': stop_type,
            'side': 'SELL' if base_order['side'] == 'BUY' else 'BUY',
            'quantity': quantity or base_order['quantity'],
            'stopPrice': stop_price,
            'clientOrderId': f"sl-{self._order_counter}-{uuid.uuid4().hex[:8]}",
        }

    def build_take_profit_order(self, base_order: Dict[str, Any],
                               price: float,
                               quantity: Optional[float] = None) -> Dict[str, Any]:
        """构建止盈订单"""
        return {
            'symbol': base_order['symbol'],
            'type': 'LIMIT',
            'side': 'SELL' if base_order['side'] == 'BUY' else 'BUY',
            'quantity': quantity or base_order['quantity'],
            'price': price,
            'clientOrderId': f"tp-{self._order_counter}-{uuid.uuid4().hex[:8]}",
        }

    def build_oco_order(self, symbol: str,
                        side: OrderSide,
                        quantity: float,
                        price: float,
                        stop_price: float,
                        stop_limit_price: Optional[float] = None) -> ComplexOrder:
        """构建OCO订单"""
        self._order_counter += 1

        # 主订单（限价单）
        primary_order = {
            'symbol': symbol,
            'type': 'LIMIT',
            'side': side.value,
            'quantity': quantity,
            'price': price,
            'newClientOrderId': f"oco-{self._order_counter}-primary",
        }

        # 止损订单
        stop_order = {
            'symbol': symbol,
            'type': 'STOP_LIMIT' if stop_limit_price else 'STOP_MARKET',
            'side': side.value,
            'quantity': quantity,
            'stopPrice': stop_price,
            'price': stop_limit_price,
            'newClientOrderId': f"oco-{self._order_counter}-stop",
        }

        return ComplexOrder(
            primary_order=primary_order,
            secondary_orders=[stop_order],
            relation=OrderRelation.OCO
        )

    async def execute_complex_order(self, complex_order: ComplexOrder) -> List[OrderInfo]:
        """执行复杂订单"""
        results = []

        # 创建主订单
        primary_result = await self.api.create_order(**complex_order.primary_order)
        results.append(primary_result)

        # 创建关联订单
        for secondary in complex_order.secondary_orders:
            # 设置主订单ID
            secondary['newOrderId'] = primary_result.order_id
            secondary_result = await self.api.create_order(**secondary)
            results.append(secondary_result)

        return results

    async def create_bracket_order(self,
                                  symbol: str,
                                  side: OrderSide,
                                  quantity: float,
                                  entry_price: Optional[float] = None,
                                  stop_loss_percent: float = 0.02,
                                  take_profit_percent: float = 0.03) -> ComplexOrder:
        """创建括号订单（同时设置止损和止盈）"""
        # 如果没有指定入场价，使用当前市价
        if entry_price is None:
            ticker = await self.api.fetch_ticker(symbol)
            entry_price = float(ticker['lastPrice'])

        # 计算止损和止盈价格
        stop_price = entry_price * (1 - stop_loss_percent) if side == OrderSide.BUY else entry_price * (1 + stop_loss_percent)
        take_profit_price = entry_price * (1 + take_profit_percent) if side == OrderSide.BUY else entry_price * (1 - take_profit_percent)

        # 构建OCO订单
        return self.build_oco_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=entry_price,
            stop_price=stop_price,
            stop_limit_price=stop_price
        )
```

### 8. 整合到Backtrader

```python
import backtrader as bt
from typing import Dict, List, Optional, Any

class LiveTradingEngine(bt.Cerebro):
    """实时交易引擎"""

    def __init__(self, exchange_api: ExchangeAPI,
                 symbol: str = 'BTCUSDT',
                 timeframe: str = '1m'):
        super().__init__()

        self.exchange_api = exchange_api
        self.symbol = symbol
        self.timeframe = timeframe

        # WebSocket管理器
        self.ws_manager = None

        # 心跳监控器
        self.heartbeat = None

        # 数据源和经纪人
        self._setup_live_components()

    def _setup_live_components(self):
        """设置实时组件"""
        # 替换数据源为实时数据源
        self.datas = [LiveDataSource(
            api=self.exchange_api,
            ws_manager=self.ws_manager,
            symbol=self.symbol,
            timeframe=self.timeframe
        )]

        # 替换经纪人为实时经纪人
        self.broker = LiveBroker(
            api=self.exchange_api,
            ws_manager=self.ws_manager
        )

    async def start(self) -> None:
        """启动实时交易"""
        # 初始化WebSocket
        self.ws_manager = WebSocketManager(
            url=self._get_ws_url(),
            ping_interval=30,
            ping_timeout=10
        )

        # 初始化心跳监控
        self.heartbeat = HeartbeatMonitor(
            server_url=self._get_api_url()
        )

        # 启动数据源
        for data in self.datas:
            if hasattr(data, 'start'):
                await data.start()

        # 启动经纪人
        if hasattr(self.broker, 'start'):
            await self.broker.start()

        # 启动心跳
        await self.heartbeat.start(self.ws_manager)

        logger.info("Live trading engine started")

    async def stop(self) -> None:
        """停止实时交易"""
        # 停止心跳
        if self.heartbeat:
            await self.heartbeat.stop()

        # 停止数据源
        for data in self.datas:
            if hasattr(data, 'stop'):
                await data.stop()

        # 停止经纪人
        if hasattr(self.broker, 'stop'):
            await self.broker.stop()

        # 关闭WebSocket
        if self.ws_manager:
            await self.ws_manager.close()

        logger.info("Live trading engine stopped")

    def _get_ws_url(self) -> str:
        """获取WebSocket URL"""
        return "wss://stream.binance.com:9443/ws"

    def _get_api_url(self) -> str:
        """获取API URL"""
        return "https://api.binance.com"

async def run_live(strategy_class: type,
                    strategy_params: Dict = None,
                    duration: Optional[int] = None):
    """运行实时交易"""
    engine = LiveTradingEngine(
        exchange_api=BinanceAPI(),
        symbol='BTCUSDT',
        timeframe='1m'
    )

    # 添加策略
    engine.addstrategy(strategy_class, **(strategy_params or {}))

    # 启动
    await engine.start()

    # 运行指定时长或持续运行
    if duration:
        await asyncio.sleep(duration)
        await engine.stop()

# 使用示例
async def main():
    cerebro = LiveTradingEngine(
        exchange_api=BinanceAPI(),
        symbol='BTCUSDT',
        timeframe='1m'
    )

    cerebro.addstrategy(MyStrategy, param1=10, param2=20)

    await cerebro.start()
```

---

## 实施计划

### 第一阶段：API抽象层（1周）

1. 实现ExchangeAPI抽象基类
2. 实现Binance API具体实现
3. 实现标准数据格式转换
4. 单元测试

### 第二阶段：WebSocket管理（1周）

1. 实现WebSocketManager
2. 实现消息处理机制
3. 实现订阅/取消订阅
4. 单元测试

### 第三阶段：实时数据源（1周）

1. 实现LiveDataSource
2. 实现历史数据回填
3. 实现实时数据推送
4. 集成测试

### 第四阶段：实时经纪人（2周）

1. 实现LiveBroker
2. 实现订单管理
3. 实现账户同步
4. 集成测试

### 第五阶段：错误处理（1周）

1. 实现重试机制
2. 实现熔断器
3. 实现限流器
4. 单元测试

### 第六阶段：心跳保持（1周）

1. 实现HeartbeatMonitor
2. 实现时间同步
3. 实现连接监控
4. 集成测试

### 第七阶段：复杂订单（1周）

1. 实现OrderBuilder
2. 实现OCO订单
3. 实现括号订单
4. 单元测试

### 第八阶段：整合与文档（1周）

1. 实现实时交易引擎
2. 编写用户文档
3. 编写示例代码
4. 端到端测试

---

## API兼容性保证

1. **新增独立模块**：所有实时交易功能作为独立模块
2. **保持原有API**：不影响现有回测功能
3. **可选集成**：用户选择是否使用实时交易
4. **渐进式迁移**：可以逐步添加实时功能

---

## 使用示例

### 示例1：实时数据源

```python
from backtrader.live import LiveDataSource

# 创建实时数据源
data = LiveDataSource(
    symbol='BTCUSDT',
    timeframe='1m',
    history_bars=100,
    backfill=True
)

# 添加到Cerebro
cerebro = bt.Cerebro()
cerebro.adddata(data)

# 添加策略
cerebro.addstrategy(MyStrategy)

# 运行
cerebro.run()
```

### 示例2：实时交易

```python
from backtrader.live import LiveTradingEngine
import asyncio

async def main():
    # 创建实时交易引擎
    engine = LiveTradingEngine(
        exchange_api=BinanceAPI(
            api_key='your_api_key',
            api_secret='your_api_secret'
        ),
        symbol='BTCUSDT',
        timeframe='1m'
    )

    # 添加策略
    engine.addstrategy(MyStrategy, param1=10)

    # 启动
    await engine.start()

    # 运行1小时
    await asyncio.sleep(3600)

    # 停止
    await engine.stop()

asyncio.run(main())
```

### 示例3：复杂订单

```python
from backtrader.live import OrderBuilder, OrderSide

async def place_bracket_order():
    builder = OrderBuilder(api=exchange_api)

    # 创建括号订单
    bracket_order = await builder.create_bracket_order(
        symbol='BTCUSDT',
        side=OrderSide.BUY,
        quantity=0.1,
        entry_price=None,  # 使用市价
        stop_loss_percent=0.02,  # 2%止损
        take_profit_percent=0.03   # 3%止盈
    )

    print(f"Order created: {bracket_order.primary_order['clientOrderId']}")

asyncio.run(place_bracket_order())
```

### 示例4：自定义交易所

```python
from backtrader.exchange import ExchangeAPI, LiveTradingEngine

class MyExchange(ExchangeAPI):
    """自定义交易所实现"""

    async def fetch_balance(self):
        # 实现获取余额逻辑
        pass

    async def create_order(self, symbol, order_type, side, quantity, **kwargs):
        # 实现创建订单逻辑
        pass

    # ... 实现其他方法

# 使用自定义交易所
engine = LiveTradingEngine(
    exchange_api=MyExchange(),
    symbol='MYASSET/USD',
    timeframe='1m'
)
```
