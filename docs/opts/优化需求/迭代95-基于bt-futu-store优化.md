### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/bt-futu-store
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### bt-futu-store项目简介
bt-futu-store是富途证券与backtrader的集成Store，具有以下核心特点：
- **富途集成**: 集成富途OpenAPI
- **港美股**: 支持港股和美股
- **实时行情**: 实时行情数据
- **实盘交易**: 支持实盘交易
- **历史数据**: 历史K线数据
- **账户管理**: 账户信息管理

### 重点借鉴方向
1. **富途API**: 富途API集成
2. **港美股**: 港美股市场特性
3. **Store设计**: Store设计模式
4. **实盘交易**: 实盘交易接口
5. **数据订阅**: 实时数据订阅
6. **账户集成**: 账户信息集成

---

# Backtrader优化需求文档 - 基于bt-futu-store

## 1. 项目对比分析

### 1.1 架构对比

| 特性 | Backtrader (当前) | bt-futu-store |
|------|-------------------|---------------|
| Store模式 | 已有多个Store实现 | 单一Store实现 |
| 单例模式 | ParameterizedSingletonMixin | MetaSingleton metaclass |
| 事件处理 | 内联处理 | 独立Handler类 |
| 市场支持 | 依赖具体Store | 多市场统一框架 |
| 订单类型映射 | 各Store自行实现 | 集中式映射 |
| Bracket订单 | 基础支持 | 完整支持 |
| 账户同步 | 基础查询 | 实时事件同步 |

### 1.2 bt-futu-store核心优势

#### 1.2.1 统一的Store架构
```python
# bt-futu-store的清晰分层
Cerebro → Broker → Store → ExchangeAPI
                ↓
             Feed → Store → MarketAPI
```

#### 1.2.2 多市场框架
```python
class FutuStore:
    (HKTrade, CNTrade, USTrade, FutureTrade, HKCCTrade) = range(5)

    def __init__(self):
        if self.p.trade == self.HKTrade:
            self.trade_ctx = ft.OpenHKTradeContext(...)
        elif self.p.trade == self.CNTrade:
            self.trade_ctx = ft.OpenCNTradeContext(...)
        # ... 统一接口，不同实现
```

#### 1.2.3 事件处理器模式
```python
class FutuTradeOrderHandler(ft.TradeOrderHandlerBase):
    def on_recv_rsp(self, rsp_pb):
        # 独立处理订单状态更新
        order_status = content['order_status']
        # ... 处理各种订单状态

class FutuTradeDealHandler(ft.TradeDealHandlerBase):
    def on_recv_rsp(self, rsp_pb):
        # 独立处理成交确认
        # ... 处理成交信息
```

#### 1.2.4 完整的订单类型支持
```python
# 支持的订单类型映射
if order.exectype == bt.Order.Market:
    order_type = ft.OrderType.NORMAL
elif order.exectype == bt.Order.Limit:
    order_type = ft.OrderType.ABSOLUTE_LIMIT
# Stop, StopLimit, StopTrail等
```

#### 1.2.5 Bracket订单支持
```python
# 止损止盈订单
if stopside is not None:
    okwargs['stopLossOnFill'] = v20.transaction.StopLossDetails(...)
if takeside is not None:
    okwargs['takeProfitOnFill'] = v20.transaction.TakeProfitDetails(...)
```

---

## 2. 需求文档

### 2.1 功能需求

#### FR1: 统一Store基类
**描述**: 创建一个统一的Store基类，规范所有Broker集成的实现

**需求详情**:
1. 定义Store标准接口
2. 提供公共功能实现
3. 规范事件处理机制
4. 统一参数定义

**验收标准**:
- [ ] 所有Store继承统一基类
- [ ] 接口一致性检查通过
- [ ] 文档完整

#### FR2: 多市场支持框架
**描述**: 实现可扩展的多市场支持框架

**需求详情**:
1. 定义市场类型枚举
2. 为每个市场提供独立的交易上下文
3. 统一的市场切换接口
4. 市场特定的参数配置

**验收标准**:
- [ ] 支持至少3种市场类型
- [ ] 市场切换无代码修改
- [ ] 每个市场独立配置

#### FR3: 事件处理器系统
**描述**: 实现独立的事件处理器用于订单和交易事件

**需求详情**:
1. OrderHandler处理订单状态变化
2. TradeHandler处理成交确认
3. PositionHandler处理持仓变化
4. AccountHandler处理账户信息

**验收标准**:
- [ ] 各Handler独立可测试
- [ ] 事件处理延迟<100ms
- [ ] 支持事件重放

#### FR4: 增强订单类型支持
**描述**: 完善各Broker的订单类型映射

**需求详情**:
1. Market订单
2. Limit订单
3. Stop订单
4. StopLimit订单
5. StopTrail订单
6. OCO订单
7. Bracket订单

**验收标准**:
- [ ] 所有订单类型可配置
- [ ] 订单验证完整
- [ ] 错误处理清晰

#### FR5: 实时账户同步
**描述**: 实现实时的账户信息同步机制

**需求详情**:
1. 账户事件监听
2. 持仓实时更新
3. 资金变动通知
4. 同步状态管理

**验收标准**:
- [ ] 账户数据延迟<1秒
- [ ] 支持多账户
- [ ] 断线重连恢复

#### FR6: 数据Feed增强
**描述**: 增强实时数据Feed的功能

**需求详情**:
1. 订阅管理
2. 数据质量验证
3. 断线重连
4. 历史数据回填

**验收标准**:
- [ ] 支持多合约订阅
- [ ] 数据异常自动处理
- [ ] 重连后数据连续

### 2.2 非功能需求

#### NFR1: 性能
- 事件处理延迟 < 100ms
- 订单下单延迟 < 200ms
- 支持至少100个并发数据订阅

#### NFR2: 可靠性
- 连接断开自动重连
- 订单状态不丢失
- 数据完整性保证

#### NFR3: 可扩展性
- 新增Broker只需继承基类
- 新增市场类型无需修改核心代码
- Handler可插拔

#### NFR4: 兼容性
- 与现有backtrader API完全兼容
- 支持Python 3.7+
- 向后兼容现有策略

---

## 3. 设计文档

### 3.1 架构设计

#### 3.1.1 模块结构

```
backtrader/
├── stores/
│   ├── __init__.py
│   ├── base.py              # 统一Store基类
│   ├── ctpstore.py          # CTP Store (已存在，需重构)
│   ├── ibstore.py           # IB Store (已存在)
│   ├── oandastore.py        # Oanda Store (已存在)
│   ├── futustore.py         # 新增: 富途Store
│   └── xqstore.py           # 新增: 雪球Store
├── handlers/
│   ├── __init__.py
│   ├── base.py              # Handler基类
│   ├── order_handler.py     # 订单处理器
│   ├── trade_handler.py     # 成交处理器
│   ├── position_handler.py  # 持仓处理器
│   └── account_handler.py   # 账户处理器
├── brokers/
│   └── storebroker.py       # Store通用Broker
└── feeds/
    └── storefeed.py         # Store通用Feed
```

### 3.2 类设计

#### 3.2.1 统一Store基类

```python
# backtrader/stores/base.py

from abc import ABC, abstractmethod
from enum import Enum
import threading
import collections
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from backtrader.mixins import ParameterizedSingletonMixin
from backtrader.utils.py3 import queue


class MarketType(Enum):
    """市场类型枚举"""
    UNKNOWN = 0
    # 中国市场
    CN_STOCK = 1      # A股
    CN_FUTURE = 2     # 期货
    CN_OPTION = 3     # 期权
    # 香港市场
    HK_STOCK = 10     # 港股
    HK_FUTURE = 11    # 港期
    HK_OPTION = 12    # 港期权
    # 美国市场
    US_STOCK = 20     # 美股
    US_OPTION = 21    # 美期权
    US_FUTURE = 22    # 美期货
    # 加密货币
    CRYPTO = 30       # 加密货币
    # 其他
    FOREX = 40        # 外汇


@dataclass
class MarketConfig:
    """市场配置"""
    market_type: MarketType
    exchange: str
    timezone: str
    trading_hours: Dict[str, Any]
    currency: str
    multiplier: float = 1.0


class StoreEventHandler:
    """Store事件处理器基类"""

    def __init__(self, store: 'BaseStore'):
        self.store = store
        self.event_queue = queue.Queue()

    def put_event(self, event_type: str, data: Any):
        """放入事件到队列"""
        self.event_queue.put((event_type, data))

    def get_event(self, timeout: float = 0.1) -> Optional[tuple]:
        """从队列获取事件"""
        try:
            return self.event_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def process_events(self):
        """处理所有待处理事件"""
        while True:
            event = self.get_event(timeout=0)
            if event is None:
                break
            event_type, data = event
            handler = getattr(self, f'on_{event_type}', None)
            if handler:
                handler(data)


class OrderHandler(StoreEventHandler):
    """订单事件处理器"""

    def on_submitted(self, order):
        """订单已提交"""
        if hasattr(self.store, 'broker') and self.store.broker:
            self.store.broker._submit(order.ref)

    def on_accepted(self, order):
        """订单已接受"""
        if hasattr(self.store, 'broker') and self.store.broker:
            self.store.broker._accept(order.ref)

    def on_rejected(self, order, reason):
        """订单被拒绝"""
        if hasattr(self.store, 'broker') and self.store.broker:
            self.store.broker._reject(order.ref, reason)

    def on_partial(self, order):
        """部分成交"""
        if hasattr(self.store, 'broker') and self.store.broker:
            self.store.broker._partial(order.ref)

    def on_completed(self, order):
        """完全成交"""
        if hasattr(self.store, 'broker') and self.store.broker:
            self.store.broker._completed(order.ref)

    def on_cancelled(self, order):
        """订单已取消"""
        if hasattr(self.store, 'broker') and self.store.broker:
            self.store.broker._cancelled(order.ref)

    def on_expired(self, order):
        """订单已过期"""
        if hasattr(self.store, 'broker') and self.store.broker:
            self.store.broker._expired(order.ref)


class TradeHandler(StoreEventHandler):
    """成交事件处理器"""

    def on_trade(self, trade):
        """处理成交事件"""
        # 更新持仓
        # 更新资金
        # 通知策略
        pass


class PositionHandler(StoreEventHandler):
    """持仓事件处理器"""

    def on_position_update(self, position):
        """处理持仓更新"""
        if hasattr(self.store, 'broker') and self.store.broker:
            data_name = position.get('symbol')
            size = position.get('size', 0)
            price = position.get('avg_price', 0)
            self.store.broker.positions[data_name] = Position(size, price)


class AccountHandler(StoreEventHandler):
    """账户事件处理器"""

    def on_account_update(self, account):
        """处理账户更新"""
        if hasattr(self.store, 'broker') and self.store.broker:
            self.store._cash = account.get('available', 0)
            self.store._value = account.get('balance', 0)


class BaseStore(ParameterizedSingletonMixin, ABC):
    """统一Store基类

    所有Broker集成Store都应继承此类，确保接口一致性。
    """

    # 子类需要设置的类属性
    BrokerCls = None
    DataCls = None

    # 默认参数
    params = (
        ('host', '127.0.0.1'),
        ('port', None),
        ('debug', False),
        ('timeout', 30),
        ('reconnect', True),
        ('reconnect_interval', 5),
    )

    # 市场配置映射
    MARKET_CONFIGS: Dict[MarketType, MarketConfig] = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 通知队列
        self.notifs = collections.deque()

        # Broker引用
        self.broker = None

        # 订单管理
        self._orders = collections.OrderedDict()
        self._ordersrev = collections.OrderedDict()
        self._transpend = collections.defaultdict(collections.deque)

        # 账户信息
        self._cash = 0.0
        self._value = 0.0
        self._evt_acct = threading.Event()

        # 数据Feed注册
        self._feeds = {}
        self._feed_queues = {}

        # 事件处理器
        self.order_handler = OrderHandler(self)
        self.trade_handler = TradeHandler(self)
        self.position_handler = PositionHandler(self)
        self.account_handler = AccountHandler(self)

        # 连接状态
        self._connected = False
        self._authenticated = False

    @classmethod
    def getdata(cls, *args, **kwargs):
        """获取数据Feed实例"""
        return cls.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        """获取Broker实例"""
        return cls.BrokerCls(*args, **kwargs)

    @abstractmethod
    def connect(self):
        """连接到Broker

        子类必须实现此方法，建立与Broker的连接。
        """
        pass

    @abstractmethod
    def disconnect(self):
        """断开与Broker的连接

        子类必须实现此方法，清理连接资源。
        """
        pass

    @abstractmethod
    def subscribe_market_data(self, dataname, timeframe, compression):
        """订阅市场数据

        Args:
            dataname: 合约代码
            timeframe: 时间周期
            compression: 周期倍数
        """
        pass

    @abstractmethod
    def unsubscribe_market_data(self, dataname):
        """取消订阅市场数据"""
        pass

    def start(self, data=None, broker=None):
        """启动Store

        Args:
            data: 数据Feed实例
            broker: Broker实例
        """
        if data is None and broker is None:
            self._cash = None
            return

        if data is not None:
            self._register_feed(data)

        if broker is not None:
            self.broker = broker
            self._init_broker()

    def stop(self):
        """停止Store"""
        self.disconnect()

    def _register_feed(self, data):
        """注册数据Feed"""
        dataname = data.p.dataname
        self._feeds[dataname] = data
        self._feed_queues[dataname] = queue.Queue()
        data.set_store(self)
        return self._feed_queues[dataname]

    def _init_broker(self):
        """初始化Broker相关"""
        # 获取初始账户信息
        self._update_account()
        self.startingcash = self.cash = self._cash
        self.startingvalue = self.value = self._value

    @abstractmethod
    def _update_account(self):
        """更新账户信息"""
        pass

    @abstractmethod
    def _update_positions(self):
        """更新持仓信息"""
        pass

    # 订单操作
    @abstractmethod
    def order_create(self, order, stopside=None, takeside=None, **kwargs):
        """创建订单"""
        pass

    @abstractmethod
    def order_cancel(self, order):
        """取消订单"""
        pass

    @abstractmethod
    def order_modify(self, order, **kwargs):
        """修改订单"""
        pass

    # 账户查询
    def get_cash(self):
        """获取可用资金"""
        return self._cash

    def get_value(self):
        """获取账户总值"""
        return self._value

    def get_positions(self):
        """获取持仓信息"""
        if self.broker:
            return self.broker.positions
        return {}

    # 通知系统
    def put_notification(self, msg, *args, **kwargs):
        """放入通知"""
        self.notifs.append((msg, args, kwargs))

    def get_notifications(self):
        """获取所有通知"""
        self.notifs.append(None)
        return [x for x in iter(self.notifs.popleft, None)]

    # 市场配置
    @classmethod
    def register_market(cls, market_type: MarketType, config: MarketConfig):
        """注册市场配置"""
        cls.MARKET_CONFIGS[market_type] = config

    @classmethod
    def get_market_config(cls, market_type: MarketType) -> Optional[MarketConfig]:
        """获取市场配置"""
        return cls.MARKET_CONFIGS.get(market_type)

    # 连接状态
    @property
    def connected(self) -> bool:
        """是否已连接"""
        return self._connected

    @property
    def authenticated(self) -> bool:
        """是否已认证"""
        return self._authenticated
```

#### 3.2.2 富途Store实现

```python
# backtrader/stores/futustore.py

"""
富途证券Store实现

基于py-futu-api的backtrader集成，支持:
- 港股现货、期货、期权
- A股现货
- 美股现货、期权
- 实时行情数据
- 实盘/模拟交易
"""

import threading
from typing import Optional
from datetime import datetime

import backtrader as bt
from backtrader.position import Position
from backtrader.stores.base import (
    BaseStore,
    MarketType,
    MarketConfig,
    OrderHandler,
    TradeHandler,
    PositionHandler,
    AccountHandler,
)

try:
    import futu as ft
except ImportError:
    ft = None


class FutuOrderHandler(OrderHandler):
    """富途订单处理器"""

    def on_recv_rsp(self, rsp_pb):
        """处理订单响应"""
        ret, content = super().on_recv_rsp(rsp_pb)

        if ret == ft.RET_OK:
            order_status = content['order_status']
            oid = content['order_id']

            # 映射富途订单状态到backtrader
            status_map = {
                ft.OrderStatus.UNSUBMITTED: 'pending',
                ft.OrderStatus.WAITING_SUBMIT: 'pending',
                ft.OrderStatus.SUBMITTING: 'submitted',
                ft.OrderStatus.SUBMITTED: 'submitted',
                ft.OrderStatus.SUBMIT_FAILED: 'rejected',
                ft.OrderStatus.FILLED_PART: 'partial',
                ft.OrderStatus.FILLED_ALL: 'completed',
                ft.OrderStatus.CANCELLING_ALL: 'cancelling',
                ft.OrderStatus.CANCELLED_ALL: 'cancelled',
                ft.OrderStatus.FAILED: 'rejected',
                ft.OrderStatus.TIMEOUT: 'expired',
            }

            bt_status = status_map.get(order_status, 'unknown')

            # 获取backtrader订单
            bt_order = self.store._orders.get(oid)
            if bt_order:
                handler = getattr(self, f'on_{bt_status}', None)
                if handler:
                    handler(bt_order, content.get('order_msg', ''))

        return ret, content


class FutuTradeHandler(TradeHandler):
    """富途成交处理器"""

    def on_recv_rsp(self, rsp_pb):
        """处理成交响应"""
        ret, content = super().on_recv_rsp(rsp_pb)

        if ret == ft.RET_OK:
            # 处理成交信息
            self.on_trade(content)

        return ret, content


class FutuStore(BaseStore):
    """富途证券Store

    支持富途OpenAPI连接，提供港股、A股、美股等市场的行情和交易功能。

    示例:
        >>> store = bt.stores.FutuStore(
        ...     trade_env=ft.TrdEnv.SIMULATE,
        ...     market=MarketType.HK_STOCK,
        ...     host='127.0.0.1',
        ...     port=11111
        ... )
        >>> cerebro.setbroker(store.getbroker())
    """

    # 富途特定参数
    params = (
        *BaseStore.params,
        ('trade_env', None),           # 交易环境: SIMULATE/REAL
        ('market', MarketType.HK_STOCK),
        ('unlock_password', None),     # 实盘解锁密码
        ('lang', 'zh'),                # 语言
    )

    # 订单类型映射
    ORDER_TYPE_MAP = {
        bt.Order.Market: ft.OrderType.NORMAL,
        bt.Order.Limit: ft.OrderType.ABSOLUTE_LIMIT,
        # 其他订单类型需要扩展
    }

    def __init__(self, **kwargs):
        if ft is None:
            raise ImportError('futu package is required for FutuStore')

        super().__init__(**kwargs)

        # 初始化富途交易上下文
        self.trade_ctx = None
        self.quote_ctx = None

        # 设置市场配置
        self._setup_market_configs()

    def _setup_market_configs(self):
        """设置市场配置"""
        # 港股配置
        self.register_market(MarketType.HK_STOCK, MarketConfig(
            market_type=MarketType.HK_STOCK,
            exchange='SEHK',
            timezone='Asia/Hong_Kong',
            trading_hours={
                'morning': ('09:30', '12:00'),
                'afternoon': ('13:00', '16:00')
            },
            currency='HKD'
        ))

        # A股配置
        self.register_market(MarketType.CN_STOCK, MarketConfig(
            market_type=MarketType.CN_STOCK,
            exchange='SSE/SZSE',
            timezone='Asia/Shanghai',
            trading_hours={
                'morning': ('09:30', '11:30'),
                'afternoon': ('13:00', '15:00')
            },
            currency='CNY'
        ))

        # 美股配置
        self.register_market(MarketType.US_STOCK, MarketConfig(
            market_type=MarketType.US_STOCK,
            exchange='NASDAQ/NYSE',
            timezone='America/New_York',
            trading_hours={
                'regular': ('09:30', '16:00')
            },
            currency='USD'
        ))

    def connect(self):
        """连接到富途OpenD"""
        try:
            # 创建行情上下文
            self.quote_ctx = ft.OpenQuoteContext(
                host=self.p.host,
                port=self.p.port
            )

            # 根据市场类型创建交易上下文
            market = self.p.market

            if market == MarketType.HK_STOCK:
                self.trade_ctx = ft.OpenHKTradeContext(
                    host=self.p.host,
                    port=self.p.port
                )
            elif market == MarketType.CN_STOCK:
                self.trade_ctx = ft.OpenCNTradeContext(
                    host=self.p.host,
                    port=self.p.port
                )
            elif market == MarketType.US_STOCK:
                self.trade_ctx = ft.OpenUSTradeContext(
                    host=self.p.host,
                    port=self.p.port
                )
            elif market == MarketType.CN_FUTURE:
                self.trade_ctx = ft.OpenFutureTradeContext(
                    host=self.p.host,
                    port=self.p.port
                )
            else:
                raise ValueError(f'Unsupported market: {market}')

            # 设置交易环境
            if self.p.trade_env is None:
                self.p.trade_env = ft.TrdEnv.SIMULATE

            self._connected = True

        except Exception as e:
            self.put_notification(f'Connection failed: {e}')
            self._connected = False
            raise

    def disconnect(self):
        """断开连接"""
        if self.quote_ctx:
            self.quote_ctx.close()
        if self.trade_ctx:
            self.trade_ctx.close()
        self._connected = False
        self._authenticated = False

    def _init_broker(self):
        """初始化Broker"""
        super()._init_broker()

        # 实盘交易需要解锁
        if self.p.trade_env == ft.TrdEnv.REAL:
            if self.p.unlock_password:
                ret, data = self.trade_ctx.unlock_trade(
                    password=self.p.unlock_password
                )
                if ret == ft.RET_OK:
                    self._authenticated = True
                else:
                    raise PermissionError('Failed to unlock trade')
        else:
            self._authenticated = True

        # 设置订单和成交处理器
        self.trade_ctx.set_handler(FutuOrderHandler(self))
        self.trade_ctx.set_handler(FutuTradeHandler(self))

        # 查询账户信息
        self._update_account()
        self._update_positions()

    def subscribe_market_data(self, dataname, timeframe, compression):
        """订阅市场数据"""
        if self.quote_ctx is None:
            raise RuntimeError('Quote context not connected')

        # 订阅行情
        ret, err = self.quote_ctx.subscribe(
            [dataname],
            [ft.SubType.QUOTE]  # 可扩展: K_1M, K_5M, K_DAY等
        )

        if ret != ft.RET_OK:
            self.put_notification(f'Subscribe failed: {err}')

        return ret == ft.RET_OK

    def unsubscribe_market_data(self, dataname):
        """取消订阅市场数据"""
        if self.quote_ctx:
            self.quote_ctx.unsubscribe([dataname], [ft.SubType.QUOTE])

    def _update_account(self):
        """更新账户信息"""
        if self.trade_ctx is None:
            return

        ret, account = self.trade_ctx.accinfo_query(
            trd_env=self.p.trade_env
        )

        if ret == ft.RET_OK:
            self._cash = account['cash']
            self._value = account['total_assets']
            self._evt_acct.set()
        else:
            self.put_notification(f'Account query failed: {account}')

    def _update_positions(self):
        """更新持仓信息"""
        if self.trade_ctx is None or self.broker is None:
            return

        ret, positions = self.trade_ctx.position_list_query(
            trd_env=self.p.trade_env
        )

        if ret == ft.RET_OK:
            for pos in positions:
                data_name = pos['code']
                size = int(pos['qty']) * (1 if pos['position_side'] == 'long' else -1)
                price = float(pos['cost_price']) if size != 0 else 0

                self.broker.positions[data_name] = Position(size, price)

    def get_history_data(self, dataname, start_dt, end_dt, timeframe='D'):
        """获取历史K线数据

        Args:
            dataname: 合约代码
            start_dt: 开始日期
            end_dt: 结束日期
            timeframe: 周期类型

        Returns:
            list: K线数据列表
        """
        if self.quote_ctx is None:
            return []

        # 映射timeframe
        ktype_map = {
            'M': ft.KLType.K_1M,
            '5': ft.KLType.K_5M,
            '15': ft.KLType.K_15M,
            '30': ft.KLType.K_30M,
            '60': ft.KLType.K_60M,
            'D': ft.KLType.K_DAY,
            'W': ft.KLType.K_WEEK,
            'M': ft.KLType.K_MON,
        }

        ktype = ktype_map.get(timeframe, ft.KLType.K_DAY)

        ret, data = self.quote_ctx.get_history_kline(
            code=dataname,
            start=start_dt.strftime('%Y-%m-%d'),
            end=end_dt.strftime('%Y-%m-%d'),
            ktype=ktype,
            fields=[ft.KL_FIELD.ALL]
        )

        if ret == ft.RET_OK:
            return data
        return []

    def order_create(self, order, stopside=None, takeside=None, **kwargs):
        """创建订单

        Args:
            order: backtrader订单对象
            stopside: 止损订单
            takeside: 止盈订单
            **kwargs: 额外参数

        Returns:
            order: 创建的订单
        """
        if self.trade_ctx is None:
            raise RuntimeError('Trade context not connected')

        dataname = order.data._dataname

        # 获取合约精度
        precision = self._get_contract_precision(dataname)

        # 确定订单方向
        trd_side = ft.TrdSide.BUY if order.isbuy() else ft.TrdSide.SELL

        # 确定订单类型
        order_type = self._map_order_type(order.exectype)

        # 构建订单参数
        order_params = {
            'code': dataname,
            'trd_side': trd_side,
            'order_type': order_type,
            'qty': abs(int(order.created.size)),
            'trd_env': self.p.trade_env,
        }

        # 设置限价单价格
        if order.exectype == bt.Order.Limit:
            order_params['price'] = round(
                order.created.price,
                precision
            )

        # 设置有效期
        if order.valid is None:
            order_params['time_in_force'] = ft.TimeInForceType.GTC
        else:
            order_params['time_in_force'] = ft.TimeInForceType.GTD
            order_params['gtd_date'] = order.data.num2date(order.valid)

        # 添加止损止盈
        if stopside is not None:
            # 添加止损参数
            pass

        if takeside is not None and takeside.price is not None:
            # 添加止盈参数
            pass

        # 提交订单
        ret, result = self.trade_ctx.place_order(**order_params)

        if ret == ft.RET_OK:
            order_ref = result['order_id']
            self._orders[order_ref] = order
            order.info['futu_order_id'] = order_ref
            self.order_handler.on_submitted(order)
        else:
            self.order_handler.on_rejected(order, str(result))

        return order

    def order_cancel(self, order):
        """取消订单"""
        if self.trade_ctx is None:
            return

        order_id = order.info.get('futu_order_id')
        if order_id:
            ret, result = self.trade_ctx.cancel_order(order_id=order_id)
            if ret == ft.RET_OK:
                self.order_handler.on_cancelled(order)

    def order_modify(self, order, **kwargs):
        """修改订单"""
        if self.trade_ctx is None:
            return

        order_id = order.info.get('futu_order_id')
        if order_id and 'price' in kwargs:
            ret, result = self.trade_ctx.modify_order(
                order_id=order_id,
                price=kwargs['price'],
                qty=kwargs.get('qty', order.created.size)
            )
            return ret == ft.RET_OK
        return False

    def _map_order_type(self, bt_order_type):
        """映射backtrader订单类型到富途订单类型"""
        return self.ORDER_TYPE_MAP.get(
            bt_order_type,
            ft.OrderType.NORMAL
        )

    def _get_contract_precision(self, dataname):
        """获取合约价格精度"""
        # 简化实现，实际应该查询合约信息
        return 2
```

#### 3.2.3 Store通用Broker

```python
# backtrader/brokers/storebroker.py

"""
Store通用Broker实现

为所有Store提供统一的Broker接口。
"""

import collections
from backtrader import BrokerBase, OrderBase, BuyOrder, SellOrder
from backtrader.commissions import CommInfoBase
from backtrader.position import Position
from backtrader.utils.py3 import with_metaclass


class StoreBroker(BrokerBase):
    """通用Store Broker

    为所有Store实现提供统一的Broker接口。

    子类只需:
    1. 设置store属性
    2. 实现特定的佣金计算
    """

    def __init__(self, store, **kwargs):
        """初始化Broker

        Args:
            store: Store实例
            **kwargs: 额外参数
        """
        super().__init__(**kwargs)

        self.store = store
        self.orders = collections.OrderedDict()
        self.notifs = collections.deque()
        self.opending = collections.defaultdict(list)
        self.brackets = dict()

        # OCO订单管理
        self._ocos = dict()
        self._ocol = collections.defaultdict(list)
        self._pchildren = collections.defaultdict(collections.deque)

        # 初始资金
        self.startingcash = self.cash = 0.0
        self.startingvalue = self.value = 0.0
        self.positions = collections.defaultdict(Position)

    def start(self):
        """启动Broker"""
        super().start()
        self.store.start(broker=self)
        self.startingcash = self.cash = self.store.get_cash()
        self.startingvalue = self.value = self.store.get_value()

    def stop(self):
        """停止Broker"""
        super().stop()
        self.store.stop()

    def getcash(self):
        """获取可用资金"""
        self.cash = cash = self.store.get_cash()
        return cash

    def getvalue(self, datas=None):
        """获取账户总值"""
        self.value = self.store.get_value()
        return self.value

    def getposition(self, data, clone=True):
        """获取持仓"""
        pos = self.positions[data._dataname]
        if clone:
            pos = pos.clone()
        return pos

    def orderstatus(self, order):
        """获取订单状态"""
        o = self.orders.get(order.ref)
        if o:
            return o.status
        return None

    def buy(self, owner, data,
            size, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None,
            trailamount=None, trailpercent=None,
            parent=None, transmit=True,
            histnotify=False, _checksubmit=True,
            **kwargs):
        """买入"""
        order = BuyOrder(
            owner=owner, data=data,
            size=size, price=price, pricelimit=plimit,
            exectype=exectype, valid=valid, tradeid=tradeid,
            trailamount=trailamount, trailpercent=trailpercent,
            parent=parent, transmit=transmit,
            histnotify=histnotify
        )

        order.addinfo(**kwargs)
        self._ocoize(order, oco)
        return self.submit(order, check=_checksubmit)

    def sell(self, owner, data,
             size, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None,
             trailamount=None, trailpercent=None,
             parent=None, transmit=True,
             histnotify=False, _checksubmit=True,
             **kwargs):
        """卖出"""
        order = SellOrder(
            owner=owner, data=data,
            size=size, price=price, pricelimit=plimit,
            exectype=exectype, valid=valid, tradeid=tradeid,
            trailamount=trailamount, trailpercent=trailpercent,
            parent=parent, transmit=transmit,
            histnotify=histnotify
        )

        order.addinfo(**kwargs)
        self._ocoize(order, oco)
        return self._transmit(order)

    def notify(self, order):
        """通知订单状态"""
        self.notifs.append(order.clone())

    def _ocoize(self, order, oco):
        """处理OCO订单"""
        if oco is not None:
            self._ocos[order.ref] = oco
            self._ocol[oco].append(order)

    def _transmit(self, order):
        """传输订单"""
        oref = order.ref
        pref = getattr(order.parent, 'ref', oref)

        if order.transmit:
            if oref != pref:  # 子订单
                pending = self.opending.pop(pref)
                while len(pending) < 2:
                    pending.append(None)
                parent, child = pending

                # 确定止损止盈
                if order.exectype in [order.StopTrail, order.Stop]:
                    stopside = order
                    takeside = child
                else:
                    takeside = order
                    stopside = child

                # 记录订单
                for o in parent, stopside, takeside:
                    if o is not None:
                        self.orders[o.ref] = o

                self.brackets[pref] = [parent, stopside, takeside]
                self.store.order_create(parent, stopside, takeside)
                return takeside or stopside

            else:  # 主订单
                self.orders[order.ref] = order
                return self.store.order_create(order)

        else:  # 不立即传输
            self.opending[pref].append(order)
            return order

    def submit(self, order, check=True):
        """提交订单"""
        if check:
            # 检查订单有效性
            if not self._order_valid(order):
                return None

        return self._transmit(order)

    def _order_valid(self, order):
        """检查订单是否有效"""
        # 检查资金
        if not order.isbuy():
            return True

        # 检查是否有足够资金
        required = order.created.size * order.created.price
        if required > self.cash:
            return False

        return True


class StoreCommInfo(CommInfoBase):
    """Store通用佣金信息"""

    params = (
        ('commission', 0.0003),  # 默认万三佣金
        ('mult', 1.0),
        ('margin', None),
        ('commtype', CommInfoBase.COMM_PERC),
    )

    def _getcommission(self, size, price, pseudoexec=False):
        """计算佣金"""
        if self.p.commtype == self.COMM_PERC:
            return abs(size) * price * self.p.commission * self.p.mult
        else:
            return abs(size) * self.p.commission * self.p.mult
```

#### 3.2.4 Store通用Feed

```python
# backtrader/feeds/storefeed.py

"""
Store通用数据Feed实现

为所有Store提供统一的数据Feed接口。
"""

import time
from collections import deque
from datetime import datetime

from backtrader.feed import DataBase
from backtrader.utils.py3 import with_metaclass


class StoreFeed(DataBase):
    """通用Store数据Feed

    从Store获取实时行情数据。

    参数:
        store: Store实例
        dataname: 合约代码
        timeframe: 时间周期
        compression: 周期倍数
    """

    params = (
        ('store', None),
        ('usehist', True),        # 是否使用历史数据
        ('reconnect', True),      # 是否自动重连
        ('reconnect_pause', 3.0), # 重连间隔(秒)
    )

    # 数据列映射
    datafields = [
        'datetime', 'open', 'high', 'low', 'close',
        'volume', 'openinterest'
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._store = None
        self._qlive = None
        self._histdata = []
        self._hist_idx = 0
        self._laststamp = 0

    def set_store(self, store):
        """设置Store"""
        self._store = store
        self._qlive = store._feed_queues.get(self.p.dataname)

    def start(self):
        """启动数据Feed"""
        super().start()

        # 注册到Store
        if self._store is None and self.p.store:
            self._store = self.p.store
            self._qlive = self._store._register_feed(self)

        # 订阅行情
        if self._store:
            self._store.subscribe_market_data(
                self.p.dataname,
                self.p.timeframe,
                self.p.compression
            )

        # 获取历史数据
        if self.p.usehist:
            self._load_history()

    def stop(self):
        """停止数据Feed"""
        if self._store:
            self._store.unsubscribe_market_data(self.p.dataname)
        super().stop()

    def _load_history(self):
        """加载历史数据"""
        if hasattr(self._store, 'get_history_data'):
            end_dt = datetime.now()
            start_dt = datetime.now()

            # 根据minperiod计算需要的数据量
            days_needed = (self.p.timeframe * self.p.compression * self._minperiod) / (24 * 60)
            start_dt = datetime(end_dt.year, end_dt.month, end_dt.day - int(days_needed))

            # 映射timeframe
            tf_map = {
                (bt.TimeFrame.Minutes, 1): 'M',
                (bt.TimeFrame.Minutes, 5): '5',
                (bt.TimeFrame.Minutes, 15): '15',
                (bt.TimeFrame.Minutes, 30): '30',
                (bt.TimeFrame.Minutes, 60): '60',
                (bt.TimeFrame.Days, 1): 'D',
                (bt.TimeFrame.Weeks, 1): 'W',
                (bt.TimeFrame.Months, 1): 'M',
            }

            tf_str = tf_map.get((self.p.timeframe, self.p.compression), 'D')

            hist_data = self._store.get_history_data(
                self.p.dataname,
                start_dt,
                end_dt,
                tf_str
            )

            self._histdata = deque(hist_data)

    def _load(self):
        """加载数据"""
        # 先加载历史数据
        if self._hist_idx < len(self._histdata):
            return self._load_from_history()

        # 再加载实时数据
        return self._load_from_live()

    def _load_from_history(self):
        """从历史数据加载"""
        data = self._histdata[self._hist_idx]
        self._hist_idx += 1

        # 映射数据字段
        self.lines.datetime[0] = self.date2num(data['time_key'])
        self.lines.open[0] = float(data.get('open', 0))
        self.lines.high[0] = float(data.get('high', 0))
        self.lines.low[0] = float(data.get('low', 0))
        self.lines.close[0] = float(data.get('close', 0))
        self.lines.volume[0] = float(data.get('volume', 0))
        self.lines.openinterest[0] = float(data.get('open_interest', 0))

        return True

    def _load_from_live(self):
        """从实时数据加载"""
        if self._qlive is None:
            time.sleep(0.1)
            return True  # 等待队列就绪

        try:
            data = self._qlive.get(timeout=0.1)

            # 映射数据字段
            self.lines.datetime[0] = self.date2num(data['datetime'])
            self.lines.open[0] = float(data.get('open_price', data.get('open', 0)))
            self.lines.high[0] = float(data.get('high_price', data.get('high', 0)))
            self.lines.low[0] = float(data.get('low_price', data.get('low', 0)))
            self.lines.close[0] = float(data.get('close_price', data.get('close', 0)))
            self.lines.volume[0] = float(data.get('volume', 0))
            self.lines.openinterest[0] = float(data.get('open_interest', 0))

            return True

        except:
            time.sleep(0.01)
            return True

    def haslive(self):
        """是否有实时数据"""
        return True

    def islive(self):
        """是否为实时数据"""
        return True
```

### 3.3 使用示例

```python
"""
使用富途Store的完整示例
"""

import backtrader as bt
from backtrader.stores.futustore import FutuStore
from backtrader.stores.base import MarketType
import futu as ft


# 策略定义
class MyStrategy(bt.Strategy):
    params = (
        ('fast_period', 10),
        ('slow_period', 30),
    )

    def __init__(self):
        self.fast_ma = bt.indicators.SMA(period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)

    def next(self):
        if not self.position:
            if self.crossover > 0:
                # 买入，设置止损止盈
                self.buy(
                    size=100,
                    exectype=bt.Order.Limit,
                    price=self.data.close[0] * 0.999  # 限价单
                )

                # 设置止损
                self.sell(
                    size=100,
                    exectype=bt.Order.Stop,
                    price=self.data.close[0] * 0.98,
                    parent=self.order  # 关联到主订单
                )

                # 设置止盈
                self.sell(
                    size=100,
                    exectype=bt.Order.Limit,
                    price=self.data.close[0] * 1.02,
                    parent=self.order  # 关联到主订单
                )

        elif self.crossover < 0:
            self.close()


# 创建Cerebro
cerebro = bt.Cerebro()

# 创建富途Store
store = FutuStore(
    trade_env=ft.TrdEnv.SIMULATE,  # 模拟环境
    market=MarketType.HK_STOCK,     # 港股市场
    host='127.0.0.1',
    port=11111,
    debug=True
)

# 设置Broker
cerebro.setbroker(store.getbroker())

# 添加数据
data = store.getdata(
    dataname='00700.HK',  # 腾讯控股
    timeframe=bt.TimeFrame.Minutes,
    compression=5,
    fromdate=datetime(2024, 1, 1),
    todate=datetime.now()
)
cerebro.adddata(data)

# 添加策略
cerebro.addstrategy(MyStrategy)

# 设置初始资金
cerebro.broker.setcash(1000000)

# 运行
result = cerebro.run()

# 输出结果
print(f'Final Portfolio Value: {cerebro.broker.getvalue():.2f}')
```

### 3.4 扩展其他Store

```python
# 雪球Store示例

from backtrader.stores.base import BaseStore, MarketType

class XueqiuStore(BaseStore):
    """雪球证券Store"""

    params = (
        *BaseStore.params,
        ('username', ''),
        ('password', ''),
        ('cookie', ''),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def connect(self):
        # 实现雪球连接逻辑
        pass

    def disconnect(self):
        # 实现断开逻辑
        pass

    # ... 实现其他抽象方法
```

---

## 4. 实施计划

### 阶段1: 基础架构 (优先级: 高)
1. 创建BaseStore基类
2. 实现事件处理器系统
3. 创建StoreBroker和StoreFeed通用类
4. 编写单元测试

### 阶段2: 富途Store实现 (优先级: 高)
1. 实现FutuStore核心功能
2. 实现订单类型映射
3. 实现账户/持仓同步
4. 编写集成测试

### 阶段3: 现有Store重构 (优先级: 中)
1. 重构CTPStore继承BaseStore
2. 重构OandaStore继承BaseStore
3. 确保向后兼容

### 阶段4: 高级功能 (优先级: 中)
1. Bracket订单支持
2. OCO订单支持
3. 历史数据回填
4. 断线重连

### 阶段5: 文档和优化 (优先级: 低)
1. API文档
2. 示例代码
3. 性能优化
4. 错误处理完善

---

## 5. 测试策略

### 5.1 单元测试
- BaseStore各方法测试
- 事件处理器测试
- 订单映射测试

### 5.2 集成测试
- 连接测试
- 订单生命周期测试
- 数据流测试

### 5.3 模拟交易测试
- 完整策略回测
- 订单执行测试
- 异常恢复测试

---

## 6. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| API不稳定 | 高 | 版本锁定+适配器模式 |
| 连接断开 | 高 | 自动重连+状态持久化 |
| 订单丢失 | 高 | 本地确认+状态校验 |
| 性能问题 | 中 | 异步处理+队列缓冲 |
| 兼容性 | 低 | 充分测试+版本管理 |

---

## 7. 总结

通过借鉴bt-futu-store的设计，backtrader可以实现:

1. **统一的Store架构**: 规范所有Broker集成
2. **多市场支持**: 一套代码支持多个市场
3. **完整订单支持**: Bracket、OCO等高级订单类型
4. **实时同步**: 账户和持仓实时更新
5. **易于扩展**: 新增Store只需继承BaseStore

这将大大增强backtrader在实盘交易领域的能力。

