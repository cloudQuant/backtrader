# CCXT Store 和 Broker API 参考手册

> CCXT (CryptoCurrency eXchange Trading) 库的 Backtrader 集成
>
> 本参考文档涵盖 `CCXTStore` 和 `CCXTBroker` 类，通过统一 API 实现 100+ 加密货币交易所的实盘交易。

- --

## 目录

1. [架构概览](#架构概览)
2. [CCXTStore 类](#ccxtstore-类)
3. [CCXTBroker 类](#ccxtbroker-类)
4. [订单类型与执行](#订单类型与执行)
5. [WebSocket 与 REST 模式](#websocket-与-rest-模式)
6. [账户数据流](#账户数据流)
7. [错误处理与重连](#错误处理与重连)
8. [配置示例](#配置示例)
9. [高级功能](#高级功能)

- --

## 架构概览

```mermaid
graph TB
    subgraph "Backtrader 引擎"
        Cerebro["Cerebro"]
        Strategy["策略"]
        Indicator["指标"]
    end

    subgraph "CCXT 层"
        Store["CCXTStore"]
        Broker["CCXTBroker"]
        Feed["CCXTFeed"]

        subgraph "增强模块"
            WS["WebSocket 管理器"]
            TM["线程订单管理器"]
            RL["自适应限流器"]
            CM["连接管理器"]
            BM["括号订单管理器"]
        end
    end

    subgraph "交易所 API"
        REST["REST API"]
        WSS["WebSocket"]
    end

    Cerebro --> Strategy
    Strategy --> Indicator
    Cerebro --> Feed
    Cerebro --> Broker

    Feed --> Store
    Broker --> Store

    Store --> RL
    Store --> CM
    Store --> WS

    Broker --> TM
    Broker --> BM
    Broker --> WS

    RL --> REST
    CM --> REST
    TM --> REST
    Store --> REST

    WS --> WSS

    style Store fill:#e1f5fe
    style Broker fill:#e1f5fe
    style WS fill:#f3e5f5
    style TM fill:#f3e5f5

```bash

### 数据流

```mermaid
sequenceDiagram
    participant S as 策略
    participant B as CCXTBroker
    participant St as CCXTStore
    participant E as 交易所

    S->>B: buy(size=0.1, price=50000)
    B->>St: create_order()
    St->>E: HTTP POST /order
    E-->>St: {id: "123", status: "open"}
    St-->>B: CCXTOrder
    B-->>S: Order (Submitted)

    loop 订单轮询/WS
        St->>E: fetch_order("123")
        E-->>St: {status: "closed", filled: 0.1}
        St->>B: 订单更新
        B->>S: notify_order(Completed)
    end

```bash

- --

## CCXTStore 类

`CCXTStore` 类管理加密货币交易所的连接，为数据源和经纪商提供共享资源。

### 位置

`backtrader/stores/ccxtstore.py`

### 类签名

```python
class CCXTStore(ParameterizedSingletonMixin):
    """CCXT 数据源和经纪商的 API 提供者"""

    BrokerCls = None  # 自动注册 CCXTBroker
    DataCls = None    # 自动注册 CCXTFeed

```bash

### 构造函数

```python
CCXTStore(
    exchange: str,
    currency: str,
    config: dict,
    retries: int = 3,
    debug: bool = False,
    sandbox: bool = False,
    use_rate_limiter: bool = True,
    use_connection_manager: bool = False,
) -> None

```bash

- *参数说明：**

| 参数 | 类型 | 默认值 | 说明 |

|------|------|--------|------|

| `exchange` | str | *必需*| 交易所 ID（如 'binance'、'okx'、'bybit'） |

| `currency` | str |*必需*| 基础货币（如 'USDT'、'BTC'） |

| `config` | dict |*必需*| 包含 API 密钥的交易所配置 |

| `retries` | int | `3` | 失败请求的重试次数 |

| `debug` | bool | `False` | 启用调试输出 |

| `sandbox` | bool | `False` | 使用交易所测试网/沙箱模式 |

| `use_rate_limiter` | bool | `True` | 启用智能限流 |

| `use_connection_manager` | bool | `False` | 启用自动重连管理 |

- *配置字典格式：**

```python
config = {
    'apiKey': 'your_api_key',
    'secret': 'your_secret',
    'password': 'your_passphrase',  # OKX、KuCoin 需要
    'enableRateLimit': True,
    'timeout': 30000,
    'options': {
        'defaultType': 'spot',  # 'spot'、'future'、'margin'
        'adjustForTimeDifference': True,
    }
}

```bash

### 主要方法

#### getdata()

```python
def getdata(self, *args, **kwargs) -> CCXTFeed:
    """返回使用此存储实例的数据源"""

```bash

- *示例：**

```python
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=5,
    historical=False,
)

```bash

#### getbroker()

```python
def getbroker(self, *args, **kwargs) -> CCXTBroker:
    """返回使用此存储实例的经纪商"""

```bash

- *示例：**

```python
broker = store.getbroker(
    use_threaded_order_manager=True,
    debug=False,
)

```bash

#### create_order()

```python
@retry
def create_order(
    self,
    symbol: str,
    order_type: str,
    side: str,
    amount: float,
    price: float,
    params: dict,
) -> dict:
    """在交易所创建订单

    参数:
        symbol: 交易对（如 'BTC/USDT'）
        order_type: 'market'、'limit' 等
        side: 'buy' 或 'sell'
        amount: 订单数量
        price: 限价价格（市价单为 None）
        params: 交易所特定参数

    返回:
        交易所的订单响应字典
    """

```bash

#### cancel_order()

```python
@retry
def cancel_order(self, order_id: str, symbol: str) -> dict:
    """取消现有订单"""

```bash

#### fetch_order()

```python
@retry
def fetch_order(self, oid: str, symbol: str) -> dict:
    """获取特定订单的详细信息"""

```bash

#### fetch_ohlcv()

```python
@retry
def fetch_ohlcv(
    self,
    symbol: str,
    timeframe: str,
    since: int,
    limit: int,
    params: dict = None,
) -> list:
    """获取 OHLCV（K 线）数据

    返回:
        [时间戳, 开盘, 最高, 最低, 收盘, 成交量] 列表的列表
    """

```bash

#### get_balance()

```python
@retry
def get_balance(self) -> None:
    """从交易所获取并更新当前余额

    更新 self._cash（可用余额）和 self._value（总余额）
    """

```bash

#### get_wallet_balance()

```python
@retry
def get_wallet_balance(self, params: dict = None) -> dict:
    """获取可选参数的钱包余额

    适用于保证金交易或多币种余额

    参数:
        params: 交易所特定参数（如 {'type': 'future'}）

    返回:
        包含 'free' 和 'total' 子字典的余额字典
    """

```bash

#### get_websocket_manager()

```python
def get_websocket_manager(self) -> CCXTWebSocketManager:
    """获取或创建共享的 WebSocket 管理器

    多个数据源/经纪商共享一个 WS 连接

    返回:
        CCXTWebSocketManager 或 None（如果 ccxt.pro 不可用）
    """

```bash

#### stop()

```python
def stop(self) -> None:
    """停止存储并清理资源

    停止 WebSocket 连接和连接监控
    """

```bash

### 支持的时间粒度

| TimeFrame | 周期 | 粒度 |

|-----------|------|------|

| Minutes | 1 | `1m` |

| Minutes | 3 | `3m` |

| Minutes | 5 | `5m` |

| Minutes | 15 | `15m` |

| Minutes | 30 | `30m` |

| Minutes | 60 | `1h` |

| Minutes | 240 | `4h` |

| Days | 1 | `1d` |

| Days | 3 | `3d` |

| Weeks | 1 | `1w` |

| Months | 1 | `1M` |

| Years | 1 | `1y` |

- --

## CCXTBroker 类

`CCXTBroker` 类在加密货币交易所执行订单并管理投资组合状态。

### 位置

`backtrader/brokers/ccxtbroker.py`

### 类签名

```python
@_register_ccxt_broker_class
class CCXTBroker(BrokerBase):
    """CCXT 加密货币交易的经纪商实现"""

    order_types = {
        Order.Market: "market",
        Order.Limit: "limit",
        Order.Stop: "stop",
        Order.StopLimit: "stop limit",
    }

    mappings = {
        "closed_order": {"key": "status", "value": "closed"},
        "canceled_order": {"key": "status", "value": "canceled"},
    }

```bash

### 构造函数

```python
CCXTBroker(
    broker_mapping: dict = None,
    debug: bool = False,
    use_threaded_order_manager: bool = False,
    use_websocket_orders: bool = False,
    store: CCXTStore = None,
    max_retries: int = 3,
    retry_delay: float = 1.0,

    - *kwargs,

) -> None

```bash

- *参数说明：**

| 参数 | 类型 | 默认值 | 说明 |

|------|------|--------|------|

| `broker_mapping` | dict | `None` | 自定义订单类型/状态映射 |

| `debug` | bool | `False` | 启用调试输出 |

| `use_threaded_order_manager` | bool | `False` | 使用后台线程检查订单状态 |

| `use_websocket_orders` | bool | `False` | 使用 WebSocket 获取订单更新（最低延迟） |

| `store` | CCXTStore | `None` | 现有的存储实例 |

| `max_retries` | int | `3` | API 调用的最大重试次数 |

| `retry_delay` | float | `1.0` | 指数退避的基础延迟 |

### 自定义经纪商映射

某些交易所使用不同的订单类型名称。使用 `broker_mapping` 自定义：

```python

# Kraken 示例

broker_mapping = {
    'order_types': {
        bt.Order.Market: 'market',
        bt.Order.Limit: 'limit',
        bt.Order.Stop: 'stop-loss',  # Kraken 使用 'stop-loss'
        bt.Order.StopLimit: 'stop-loss-limit',
    },
    'mappings': {
        'closed_order': {'key': 'status', 'value': 'closed'},
        'canceled_order': {'key': 'status', 'value': 'canceled'},
    }
}

broker = CCXTBroker(broker_mapping=broker_mapping, ...)

```bash

### 主要方法

#### buy()

```python
def buy(
    self,
    owner: Strategy,
    data: DataFeed,
    size: float,
    price: float = None,
    plimit: float = None,
    exectype: int = None,
    valid: float = None,
    tradeid: int = 0,
    oco: int = None,
    trailamount: float = None,
    trailpercent: float = None,

    - *kwargs,

) -> CCXTOrder:
    """创建买单

    常用 kwargs:
        params: dict - 交易所特定参数

    示例:
        order = broker.buy(
            owner=self,
            data=self.data,
            size=0.001,
            price=50000,
            exectype=bt.Order.Limit,
            params={'postOnly': True}
        )
    """

```bash

#### sell()

```python
def sell(
    self,
    owner: Strategy,
    data: DataFeed,
    size: float,
    price: float = None,
    plimit: float = None,
    exectype: int = None,
    valid: float = None,
    tradeid: int = 0,
    oco: int = None,
    trailamount: float = None,
    trailpercent: float = None,

    - *kwargs,

) -> CCXTOrder:
    """创建卖单"""

```bash

#### cancel()

```python
def cancel(self, order: CCXTOrder) -> CCXTOrder:
    """取消未完成的订单

    参数:
        order: 要取消的 CCXTOrder 实例

    返回:
        被取消的订单实例
    """

```bash

#### get_balance()

```python
def get_balance(self) -> tuple:
    """从交易所获取并更新账户余额

    返回:
        (cash, value) 元组，cash 为可用资金，
        value 为总投资组合价值
    """

```bash

#### get_wallet_balance()

```python
def get_wallet_balance(
    self,
    currency_list: list,
    params: dict = None,
) -> dict:
    """获取多个币种的余额

    参数:
        currency_list: 币种列表（如 ['BTC', 'ETH']）
        params: 可选参数，用于保证金/期货余额

    返回:
        {
            'BTC': {'cash': 0.5, 'value': 0.5},
            'ETH': {'cash': 10.0, 'value': 10.0},
        }
    """

```bash

#### getposition()

```python
def getposition(self, data: DataFeed, clone: bool = True) -> Position:
    """获取数据源的当前持仓

    参数:
        data: 数据源
        clone: 如果为 True，返回副本（防止修改）

    返回:
        包含 size、price 属性的 Position 对象
    """

```bash

#### create_bracket_order()

```python
def create_bracket_order(
    self,
    data: DataFeed,
    size: float,
    entry_price: float,
    stop_price: float,
    limit_price: float,
    entry_type: int = None,
    side: str = "buy",
) -> BracketOrder:
    """创建括号订单（入场 + 止损 + 止盈）

    当入场订单成交时，止损和止盈订单自动下单。
    使用 OCO（一方成交另一方取消）逻辑。

    参数:
        data: 交易品种数据源
        size: 持仓大小
        entry_price: 入场价格
        stop_price: 止损触发价格
        limit_price: 止盈价格
        entry_type: 入场订单类型（默认：限价单）
        side: 'buy' 做多，'sell' 做空

    返回:
        BracketOrder 实例或 None（增强功能不可用时）

    示例:
        bracket = broker.create_bracket_order(
            data=self.data,
            size=0.01,
            entry_price=50000,
            stop_price=49500,
            limit_price=51000,
            side='buy'
        )
    """

```bash

### 订单状态映射

| Backtrader 状态 | CCXT 状态 | 说明 |

|-----------------|-----------|------|

| `Order.Created` | - | 订单已创建 |

| `Order.Submitted` | - | 已发送到交易所 |

| `Order.Accepted` | `open` | 交易所已接受 |

| `Order.Partial` | `open` | 部分成交 |

| `Order.Completed` | `closed` | 完全成交 |

| `Order.Canceled` | `canceled` | 已取消 |

| `Order.Margin` | `rejected` | 保证金不足 |

| `Order.Rejected` | `rejected` | 被交易所拒绝 |

- --

## 订单类型与执行

### 订单类型

```python
import backtrader as bt

# 市价单

order = broker.buy(
    owner=self,
    data=self.data,
    size=0.001,
    exectype=bt.Order.Market,
)

# 限价单

order = broker.buy(
    owner=self,
    data=self.data,
    size=0.001,
    price=50000,
    exectype=bt.Order.Limit,
)

# 止损单（触发后市价成交）

order = broker.sell(
    owner=self,
    data=self.data,
    size=0.001,
    price=49000,  # 止损价格
    exectype=bt.Order.Stop,
)

# 止限单

order = broker.buy(
    owner=self,
    data=self.data,
    size=0.001,
    price=50500,    # 限价
    plimit=50400,   # 止损触发价
    exectype=bt.Order.StopLimit,
)

```bash

### 订单生命周期

```mermaid
stateDiagram-v2
    [*] --> Created: 策略调用 buy/sell
    Created --> Submitted: 发送到交易所
    Submitted --> Accepted: 交易所确认
    Submitted --> Rejected: 交易所拒绝

    Accepted --> Partial: 部分成交
    Partial --> Partial: 更多成交
    Partial --> Completed: 完全成交
    Accepted --> Completed: 完全成交

    Accepted --> Canceled: 用户取消
    Partial --> Canceled: 用户取消剩余

    Completed --> [*]
    Canceled --> [*]
    Rejected --> [*]

```bash

### 交易所特定参数

通过 `params` kwarg 传递交易所特定选项：

```python

# 币安只做 maker 单

order = broker.buy(
    owner=self,
    data=self.data,
    size=0.001,
    price=50000,
    exectype=bt.Order.Limit,
    params={
        'postOnly': True,
        'timeInForce': 'GTX',  # Good-Till-Crossing
    }
)

# 币安期货只减仓

order = broker.sell(
    owner=self,
    data=self.data,
    size=0.001,
    price=50000,
    exectype=bt.Order.Stop,
    params={
        'reduceOnly': True,
        'stopPrice': 49000,
    }
)

# OKX 只做 maker 单

order = broker.buy(
    owner=self,
    data=self.data,
    size=0.001,
    price=50000,
    exectype=bt.Order.Limit,
    params={
        'postOnly': True,
        'tdMode': 'cross',  # 全仓保证金模式
    }
)

```bash

- --

## WebSocket 与 REST 模式

### REST 轮询模式（默认）

- *特点：**
- 配置简单，无需额外依赖
- 限流轮询（3 秒间隔）
- 延迟较高（数秒）
- 适用于所有交易所

```python

# REST 模式 - 默认

data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    historical=False,
)

broker = store.getbroker(
    use_threaded_order_manager=True,  # 后台轮询

)

```bash

### WebSocket 模式（推荐）

- *特点：**
- 需要 `ccxtpro` 包
- 推送式更新（最低延迟）
- 限流使用率低
- 自动重连（指数退避）
- 连接问题时回退到 REST

```python

# 首先安装 ccxtpro

# pip install ccxtpro

# WebSocket 数据源

data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    use_websocket=True,
    ws_reconnect_delay=5.0,
    ws_max_reconnect_delay=60.0,
    ws_health_check_interval=30.0,
    backfill_start=True,  # 重连时回补数据

)

# WebSocket 订单跟踪

broker = store.getbroker(
    use_websocket_orders=True,  # 实时成交更新

)

```bash

### 模式对比

| 特性 | REST 轮询 | WebSocket |

|------|-----------|-----------|

| 延迟 | 1-5 秒 | <100ms |

| 限流使用 | 高 | 低 |

| 依赖项 | 仅 ccxt | ccxt + ccxtpro |

| 重连 | 手动 | 自动 |

| 交易所支持 | 全部 | 有限 |

| 复杂度 | 简单 | 中等 |

- --

## 账户数据流

### 余额更新

- *缓存模式（默认）：**

```python

# cash 和 value 被缓存以减少 API 调用

cash = broker.getcash()       # 返回缓存值

value = broker.getvalue()     # 返回缓存值

# 需要时手动刷新

broker.get_balance()          # 从交易所获取

cash = broker.getcash()       # 现在已更新

```bash

- *多币种余额：**

```python

# 获取多个币种余额

balances = broker.get_wallet_balance(
    currency_list=['USDT', 'BTC', 'ETH'],
    params={'type': 'funding'}  # 币安资金账户

)

for currency, info in balances.items():
    print(f"{currency}: {info['cash']} 可用")

```bash

### 持仓跟踪

```python
class MyStrategy(bt.Strategy):
    def next(self):

# 获取当前持仓
        pos = self.getposition()
        print(f"数量: {pos.size}, 价格: {pos.price}")

# 获取特定数据源的持仓
        pos_btc = self.getposition(data=self.data_btc)
        pos_eth = self.getposition(data=self.data_eth)

    def notify_order(self, order):
        if order.status == order.Completed:

# 持仓已更新
            pos = self.getposition(order.data)
            print(f"新持仓数量: {pos.size}")

```bash

### 订单通知

```python
class MyStrategy(bt.Strategy):
    def notify_order(self, order):

# 订单引用
        print(f"订单 ref: {order.ref}")
        print(f"订单状态: {order.getstatusname()}")

        if order.status in [order.Submitted, order.Accepted]:
            print(f"{'买入' if order.isbuy() else '卖出'}订单待处理")

        elif order.status == order.Completed:
            print(f"""
            订单完成:

            - 方向: {'买入' if order.isbuy() else '卖出'}
            - 数量: {order.executed.size}
            - 价格: {order.executed.price}
            - 成交额: {order.executed.value}
            - 手续费: {order.executed.comm}

            """)

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f"订单失败: {order.getstatusname()}")
            if hasattr(order, 'ccxt_order'):
                error = order.ccxt_order.get('error', '')
                if error:
                    print(f"错误: {error}")

        self.order = None  # 重置订单引用

```bash

- --

## 错误处理与重连

### 重试逻辑

经纪商对瞬态错误实现指数退避：

```python

# 默认重试配置

broker = CCXTBroker(
    store=store,
    max_retries=3,         # 最大重试次数
    retry_delay=1.0,       # 基础延迟（秒）

)

# 重试行为:

# 第 1 次: 立即

# 第 2 次: 1 秒后 (2^0 *1.0)

# 第 3 次: 2 秒后 (2^1*1.0)

# 第 4 次: 4 秒后 (2^2* 1.0)

```bash

### 错误类别

| 错误类型 | 基础异常 | 行为 |

|----------|---------|------|

| 网络超时 | `NetworkError` | 指数退避重试 |

| 交易所不可用 | `ExchangeNotAvailable` | 指数退避重试 |

| 超过限流 | `ExchangeError` (429) | 指数退避重试 |

| 余额不足 | `ExchangeError` | 拒绝订单 |

| 无效订单 | `ExchangeError` | 拒绝订单 |

| 订单不存在 | `ExchangeError` | 本地取消 |

### 连接管理器

```python
from backtrader.ccxt.connection import ConnectionManager

# 创建带连接管理的存储

store = CCXTStore(
    exchange='binance',
    currency='USDT',
    config=config,
    use_connection_manager=True,
)

# 访问连接管理器

cm = store.get_connection_manager()

# 注册回调

def on_disconnect():
    print("交易所断连!")

# 暂停策略、平仓等

def on_reconnect():
    print("重新连接到交易所")

# 恢复策略、回补数据等

cm.on_disconnect(on_disconnect)
cm.on_reconnect(on_reconnect)

# 检查连接状态

if cm.is_connected():
    print("连接健康")

```bash

### WebSocket 重连

```mermaid
stateDiagram-v2
    [*] --> Connected
    Connected --> Disconnected: 连接错误
    Disconnected --> Reconnecting: 延迟后 (1s)
    Reconnecting --> Connected: 成功
    Reconnecting --> Reconnecting: 失败 (2s, 4s, 8s...)
    Reconnecting --> Disconnected: 最大重试次数

    note right of Reconnecting
        指数退避:

        - 第 1 次: 1s
        - 第 2 次: 2s
        - 第 3 次: 4s
        - 最大: 60s

    end note

```bash

- --

## 配置示例

### 币安现货

```python
import backtrader as bt

# 存储配置

config = {
    'apiKey': 'YOUR_BINANCE_API_KEY',
    'secret': 'YOUR_BINANCE_SECRET',
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',
        'adjustForTimeDifference': True,
    }
}

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config=config,
    retries=3,
    use_rate_limiter=True,
)

# 数据源

data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    ohlcv_limit=100,
    drop_newest=True,
    historical=False,
)

# 经纪商

broker = store.getbroker(
    use_threaded_order_manager=True,
)

```bash

### 币安合约

```python

# USDT 永续合约

config = {
    'apiKey': 'YOUR_BINANCE_FUTURES_KEY',
    'secret': 'YOUR_BINANCE_FUTURES_SECRET',
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',  # COIN 合约使用 'delivery'
        'adjustForTimeDifference': True,
    }
}

# 或直接使用 binanceusdm 存储

store = bt.stores.CCXTStore(
    exchange='binanceusdm',
    currency='USDT',
    config=config,
)

# 合约交易需要特定符号格式

data = store.getdata(
    dataname='BTC/USDT:USDT',  # 永续合约
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
)

```bash

### OKX

```python

# OKX 需要 passphrase

config = {
    'apiKey': 'YOUR_OKX_API_KEY',
    'secret': 'YOUR_OKX_SECRET',
    'password': 'YOUR_OKX_PASSPHRASE',  # 必需
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',  # 'spot'、'swap'、'futures'
    }
}

store = bt.stores.CCXTStore(
    exchange='okx',
    currency='USDT',
    config=config,
)

# OKX swap 格式

data = store.getdata(
    dataname='BTC/USDT:USDT',  # 永续合约
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
)

```bash

### Bybit

```python
config = {
    'apiKey': 'YOUR_BYBIT_KEY',
    'secret': 'YOUR_BYBIT_SECRET',
    'enableRateLimit': True,
    'options': {
        'defaultType': 'linear',  # 'spot'、'linear'、'inverse'
    }
}

store = bt.stores.CCXTStore(
    exchange='bybit',
    currency='USDT',
    config=config,
)

data = store.getdata(
    dataname='BTC/USDT:USDT',  # USDT 永续
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
)

```bash

### 环境变量（推荐）

```python

# .env 文件

EXCHANGE_ID=binance
EXCHANGE_API_KEY=your_key
EXCHANGE_SECRET=your_secret
EXCHANGE_CURRENCY=USDT

# Python 代码

import os
from dotenv import load_dotenv

load_dotenv()

config = {
    'apiKey': os.getenv('EXCHANGE_API_KEY'),
    'secret': os.getenv('EXCHANGE_SECRET'),
    'enableRateLimit': True,
}

store = bt.stores.CCXTStore(
    exchange=os.getenv('EXCHANGE_ID'),
    currency=os.getenv('EXCHANGE_CURRENCY'),
    config=config,
)

```bash

- --

## 高级功能

### 括号订单（OCO）

```python
class MyStrategy(bt.Strategy):
    def next(self):
        if not self.position:

# 创建括号订单：入场 + 止损 + 止盈
            bracket = self.broker.create_bracket_order(
                data=self.data,
                size=0.01,
                entry_price=50000,
                stop_price=49500,    # 1% 止损
                limit_price=51000,   # 2% 止盈
                side='buy',
            )

# 括号 ID 用于跟踪
            print(f"括号 ID: {bracket.bracket_id}")
        else:

# 修改现有括号订单
            bm = self.broker.get_bracket_manager()
            active = bm.get_active_brackets()
            for bracket in active:
                bm.modify_bracket(
                    bracket.bracket_id,
                    stop_price=49600,  # 移动止损
                )

```bash

### 限流控制

```python
from backtrader.ccxt.ratelimit import AdaptiveRateLimiter

# 创建自定义限流器

limiter = AdaptiveRateLimiter(
    initial_rpm=1200,  # 每分钟请求数
    min_rpm=60,        # 被限制时的最小值
    max_rpm=2400,      # 无错误时的最大值

)

# 存储将使用自适应限流

store = CCXTStore(
    exchange='binance',
    currency='USDT',
    config=config,
    use_rate_limiter=True,
)

```bash

### 多策略交易

```python

# 单个存储，多个策略

cerebro = bt.Cerebro()

store = bt.stores.CCXTStore(...)

# 所有策略共用单个经纪商

broker = store.getbroker()
cerebro.setbroker(broker)

# 多个数据源

btc_data = store.getdata(dataname='BTC/USDT', ...)
eth_data = store.getdata(dataname='ETH/USDT', ...)

cerebro.adddata(btc_data)
cerebro.adddata(eth_data)

# 多个策略

cerebro.addstrategy(BTCStrategy)
cerebro.addstrategy(ETHStrategy)

```bash

### WebSocket 资金费率

```python

# 永续合约资金费率

from backtrader.feeds.ccxtfeed_funding import CCXTFeedWithFunding

data = CCXTFeedWithFunding(
    store=store,
    dataname='BTC/USDT:USDT',
    use_websocket=True,
    funding_rate_callback=self.on_funding_rate,
)

class MyStrategy(bt.Strategy):
    def on_funding_rate(self, rate, next_time):
        """处理资金费率更新"""
        print(f"资金费率: {rate}, 下次: {next_time}")

# 根据资金费率调整仓位
        if rate > 0.0001:  # 正费率：多头付费给空头
            self.close()  # 避免支付资金费率

```bash

- --

## API 参考总结

### CCXTStore 关键属性

| 属性 | 类型 | 说明 |

|------|------|------|

| `exchange` | ccxt.Exchange | CCXT 交易所实例 |

| `exchange_id` | str | 交易所标识符 |

| `currency` | str | 基础货币 |

| `_cash` | float | 缓存的可用余额 |

| `_value` | float | 缓存的总余额 |

| `retries` | int | 重试次数 |

| `debug` | bool | 调试标志 |

| `_rate_limiter` | RateLimiter | 限流器实例 |

| `_ws_manager` | CCXTWebSocketManager | WebSocket 管理器 |

### CCXTBroker 关键属性

| 属性 | 类型 | 说明 |

|------|------|------|

| `store` | CCXTStore | 关联的存储 |

| `currency` | str | 账户货币 |

| `positions` | dict | 按符号索引的持仓对象 |

| `open_orders` | dict | 按 ID 索引的活动订单 |

| `cash` | float | 缓存的现金余额 |

| `value` | float | 缓存的总价值 |

| `startingcash` | float | 初始现金 |

| `startingvalue` | float | 初始价值 |

- --

## 另见

- [CCXT 实盘交易指南](../CCXT_LIVE_TRADING_GUIDE.md) - 完整实盘交易设置
- [WebSocket 指南](../WEBSOCKET_GUIDE.md) - WebSocket 架构详情
- [资金费率指南](../FUNDING_RATE_GUIDE.md) - 永续合约资金费率
- [环境配置](../CCXT_ENV_CONFIG.md) - 使用环境变量设置

- --

- 最后更新: 2026-03-01*
