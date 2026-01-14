### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/ccxt-store
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### ccxt-store项目简介
ccxt-store是CCXT库与backtrader的集成Store，具有以下核心特点：
- **CCXT集成**: 集成CCXT统一API
- **多交易所**: 支持100+加密货币交易所
- **统一接口**: 统一的交易所接口
- **实时数据**: 实时行情数据
- **交易执行**: 交易执行支持
- **历史数据**: 历史数据获取

### 重点借鉴方向
1. **CCXT集成**: CCXT库集成方式
2. **统一接口**: 统一交易所接口设计
3. **Store模式**: Store设计模式
4. **数据适配**: 数据格式适配
5. **多交易所**: 多交易所支持
6. **实时交易**: 实时交易接口

---

## 研究分析

### ccxt-store项目架构特点总结

经过深入研究，ccxt-store项目是一个独立的CCXT与backtrader集成库。

#### 1. 核心组件架构

```
┌─────────────────────────────────────────────────────────┐
│                    ccxt-store架构                        │
├─────────────────────────────────────────────────────────┤
│  CcxtStore (Singleton)                                  │
│  ├── 多线程架构                                         │
│  ├── WebSocket实时数据流                                │
│  ├── 交易所API封装                                      │
│  └── 队重限制管理                                        │
│                                                          │
│  CcxtBroker                                            │
│  ├── Bracket订单支持 (OCO)                              │
│  ├── 交易所特定映射                                      │
│  ├── 双重成交检测                                        │
│  └── 手动余额刷新                                        │
│                                                          │
│  CcxtData                                              │
│  ├── 多时间框架支持                                      │
│  ├── 状态机管理 (历史/实时/回填)                         │
│  └── 智能K线处理                                        │
└─────────────────────────────────────────────────────────┘
```

#### 2. 多线程架构

ccxt-store使用专门的线程处理不同操作:
- `_t_streaming_listener`: 处理WebSocket事件
- `_t_streaming_events`: WebSocket连接管理
- `_t_balance`: 账户余额更新 (每10秒)
- `_t_order_create`: 订单提交
- `_t_order_cancel`: 订单取消
- `_t_candles`: 历史数据获取
- `_t_streaming_prices`: 实时价格更新

#### 3. 创新特性

1. **Bracket订单**: 支持止损/止盈的OCO订单
2. **智能时间轮询**: 根据时间框架调整更新频率
3. **双重成交检测**: 同时支持trade数组统计和累计成交量
4. **交易所映射系统**: 为每个交易所自定义订单类型和状态映射
5. **手动余额刷新**: 减少API调用避免触及限制
6. **日历时间过滤**: 仅返回交易时段数据
7. **智能回填**: 重连时自动填补缺失数据

### Backtrader当前CCXT集成问题

经过详细分析，发现backtrader的CCXT集成存在严重问题：

#### 关键发现
- **CcxtBroker实际上未使用CCXT**: 代码是从Alpaca实现复制而来，使用`oapi`而非CCXT API
- **CcxtFeed同样来自Alpaca**: 引用`candles()`和`streaming_prices()`来自Alpaca store
- **CCXTStore是唯一真正的CCXT集成**: 但只提供基础REST API功能

#### 当前实现问题

1. **Broker不完整**: 未真正实现CCXT订单执行
2. **Feed不完整**: 未使用CCXT数据流
3. **无WebSocket支持**: 仅REST轮询
4. **无多线程**: 所有操作同步阻塞
5. **缺少关键功能**: Bracket订单、智能填充检测等

---

## 需求规格文档

### 1. CCXT Broker重构

#### 1.1 功能描述
重写CCXTBroker，真正集成CCXT库实现订单执行。

#### 1.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| BROK-001 | 使用CCXT API而非Alpaca API | P0 |
| BROK-002 | 实现多线程订单处理 | P0 |
| BROK-003 | 实现WebSocket订单状态更新 | P1 |
| BROK-004 | 支持Bracket订单 | P1 |
| BROK-005 | 交易所特定订单类型映射 | P1 |
| BROK-006 | 双重成交检测机制 | P1 |
| BROK-007 | 手动余额缓存刷新 | P2 |

#### 1.3 接口设计
```python
class CCXTBroker(bt.BrokerBase):
    """真正的CCXT集成Broker"""

    def __init__(self, store, broker_mapping=None):
        """
        Args:
            store: CCXTStore实例
            broker_mapping: 交易所特定配置
        """

    def buy(self, data, size, price=None, exectype=None, **kwargs):
        """买入订单"""

    def sell(self, data, size, price=None, exectype=None, **kwargs):
        """卖出订单"""

    def _submit_order(self, order):
        """提交订单到交易所"""

    def _check_order_status(self):
        """检查订单状态"""

    def _handle_fill(self, order, trade):
        """处理成交"""

    def _bracketize(self, order, stopprice, stopexec, limitprice, limitexec):
        """创建Bracket订单"""
```

### 2. CCXT Feed重构

#### 2.1 功能描述
重写CCXTFeed，使用CCXT API获取数据。

#### 2.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| FEED-001 | 使用CCXT fetch_ohlcv获取数据 | P0 |
| FEED-002 | 实现状态机管理 (历史→实时) | P0 |
| FEED-003 | 支持WebSocket实时数据流 | P1 |
| FEED-004 | 实现智能回填机制 | P1 |
| FEED-005 | 支持不完整K线处理 | P1 |
| FEED-006 | 多时间框架优化轮询 | P2 |

#### 2.3 接口设计
```python
class CCXTFeed(bt.DataBase):
    """CCXT数据源"""

    params = (
        ('exchange', None),
        ('symbol', None),
        ('timeframe', '',),
        ('fromdate', None),
        ('todate', None),
        ('drop_newest', True),  # 是否丢弃不完整K线
        ('live', False),
    )

    def start(self):
        """启动数据源"""

    def _load_history(self):
        """加载历史数据"""

    def _load_live(self):
        """加载实时数据"""

    def _update_bar(self):
        """更新K线"""

    def _backfill(self):
        """回填缺失数据"""
```

### 3. WebSocket实时数据

#### 3.1 功能描述
添加WebSocket支持实现真正的实时数据流。

#### 3.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| WS-001 | 实现WebSocket连接管理 | P0 |
| WS-002 | 支持多订阅数据流 | P0 |
| WS-003 | 实现自动重连机制 | P0 |
| WS-004 | 支持断线后回填 | P1 |
| WS-005 | 实现心跳保活 | P2 |

#### 3.3 接口设计
```python
class CCXTWebSocket:
    """WebSocket连接管理器"""

    def __init__(self, exchange, symbols):
        self.exchange = exchange
        self.symbols = symbols

    def connect(self):
        """建立连接"""

    def subscribe(self, symbol):
        """订阅数据"""

    def get_message(self):
        """获取消息"""

    def disconnect(self):
        """断开连接"""

    def is_connected(self):
        """检查连接状态"""
```

### 4. 多线程架构

#### 4.1 功能描述
实现多线程架构提升性能和响应性。

#### 4.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| MT-001 | 实现线程安全的队列通信 | P0 |
| MT-002 | 创建独立数据更新线程 | P0 |
| MT-003 | 创建独立订单状态检查线程 | P1 |
| MT-004 | 创建独立余额更新线程 | P1 |
| MT-005 | 实现线程生命周期管理 | P2 |

#### 4.3 接口设计
```python
class ThreadedDataFeed:
    """多线程数据源"""

    def __init__(self):
        self.data_queue = queue.Queue()
        self.running = False

    def start_data_thread(self):
        """启动数据线程"""

    def stop(self):
        """停止所有线程"""


class ThreadedBroker:
    """多线程Broker"""

    def __init__(self):
        self.order_queue = queue.Queue()

    def start_order_thread(self):
        """启动订单线程"""

    def start_balance_thread(self):
        """启动余额线程"""
```

### 5. 队重限制优化

#### 5.1 功能描述
智能管理API调用频率避免触及限制。

#### 5.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| RATE-001 | 实现指数退避重试 | P0 |
| RATE-002 | 智能轮询间隔调整 | P0 |
| RATE-003 | 余额缓存机制 | P0 |
| RATE-004 | 批量API调用优化 | P1 |
| RATE-005 | 限流状态监控 | P2 |

#### 5.3 接口设计
```python
class RateLimiter:
    """API限流管理器"""

    def __init__(self, rate_limit=1200):
        self.rate_limit = rate_limit
        self.request_times = []

    def acquire(self):
        """获取调用许可"""

    def release(self):
        """释放调用许可"""

    def wait_for_rate_limit(self):
        """等待限流结束"""

    def get_wait_time(self):
        """获取建议等待时间"""


def retry_with_backoff(retries=3, base_delay=1.0):
    """带指数退避的重试装饰器"""
```

### 6. 交易所特定配置

#### 6.1 功能描述
支持不同交易所的特定配置和API差异。

#### 6.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| EXCH-001 | 订单类型映射配置 | P0 |
| EXCH-002 | 订单状态映射配置 | P0 |
| EXCH-003 | 交易所参数配置 | P1 |
| EXCH-004 | 时间框架映射配置 | P1 |
| EXCH-005 | 费率配置 | P2 |

#### 6.3 接口设计
```python
class ExchangeConfig:
    """交易所配置"""

    ORDER_TYPES = {
        'binance': {
            'market': 'market',
            'limit': 'limit',
            'stop_loss_limit': 'stop_loss_limit',
            'stop_market': 'stop_market',
        },
        'kraken': {
            'market': 'market',
            'limit': 'limit',
            'stop': 'stop',
            # ...
        }
    }

    TIMEFRAMES = {
        'binance': {
            bt.TimeFrame.Minutes: '1m',
            bt.TimeFrame.Minutes * 5: '5m',
            # ...
        }
    }

    @classmethod
    def get_order_type(cls, exchange, bt_type):
        """获取交易所订单类型"""

    @classmethod
    def get_timeframe(cls, exchange, bt_tf):
        """获取交易所时间框架"""
```

---

## 设计文档

### 整体架构设计

#### 1. 目录结构
```
backtrader/
├── stores/
│   └── ccxtstore.py          # CCXTStore (已有，需增强)
│
├── brokers/
│   └── ccxtbroker.py          # CCXTBroker (需重写)
│
├── feeds/
│   └── ccxtfeed.py            # CCXTFeed (需重写)
│
└── ccxt/                     # 新增CCXT模块
    ├── __init__.py
    ├── config.py              # 交易所配置
    ├── websocket.py           # WebSocket管理
    ├── threading.py           # 多线程工具
    ├── ratelimit.py           # 限流管理
    ├── orders/                # 订单管理
    │   ├── __init__.py
    │   ├── bracket.py         # Bracket订单
    │   └── mapping.py         # 订单映射
    └── utils.py               # 工具函数
```

### 详细设计

#### 1. CCXTBroker重写

```python
# brokers/ccxtbroker.py
import backtrader as bt
from backtrader.broker import BrokerBase
from backtrader.order import Order, BuyOrder, SellOrder
import threading
import queue
import time

class CCXTBroker(BrokerBase):
    """CCXT Broker实现

    真正使用CCXT API进行订单执行，而非从Alpaca复制
    """

    params = (
        ('store', None),
        ('check_interval', 3),  # 订单检查间隔(秒)
        ('use_websocket', False),  # 是否使用WebSocket
        ('broker_mapping', None),  # 交易所特定映射
    )

    def __init__(self):
        super().__init__()

        if self.p.store is None:
            raise ValueError("store parameter is required")

        self.store = self.p.store
        self.exchange = self.store.ccxt

        # 订单管理
        self._orders = {}  # ccxt_id -> Order
        self._pending = queue.Queue()

        # 余额缓存
        self._balance_cache = {}
        self._balance_timestamp = 0
        self._balance_ttl = 10  # 缓存10秒

        # 线程
        self._order_thread = None
        self._balance_thread = None
        self._running = False

        # 交易所映射
        self.broker_mapping = self.p.broker_mapping or self._default_broker_mapping()

    def start(self):
        """启动broker"""
        self._running = True

        if self.p.use_websocket:
            self._start_websocket()

        # 启动订单检查线程
        self._order_thread = threading.Thread(
            target=self._order_loop, daemon=True)
        self._order_thread.start()

        # 启动余额更新线程
        self._balance_thread = threading.Thread(
            target=self._balance_loop, daemon=True)
        self._balance_thread.start()

    def stop(self):
        """停止broker"""
        self._running = False

    def _default_broker_mapping(self):
        """默认交易所映射配置"""
        return {
            'order_types': {
                bt.Order.Market: 'market',
                bt.Order.Limit: 'limit',
                bt.Order.Stop: 'stop_loss',  # 默认使用stop_loss
                bt.Order.StopLimit: 'stop_loss_limit',
            },
            'order_statuses': {
                'open': [bt.Accepted, bt.Partial],
                'closed': [bt.Completed],
                'canceled': [bt.Cancelled],
            }
        }

    def buy(self, data, size, price=None, exectype=None, **kwargs):
        """买入"""
        order = self._create_order(data, BuyOrder, size, price, exectype, **kwargs)
        self._submit_order(order)
        return order

    def sell(self, data, size, price=None, exectype=None, **kwargs):
        """卖出"""
        order = self._create_order(data, SellOrder, size, price, exectype, **kwargs)
        self._submit_order(order)
        return order

    def _create_order(self, data, order_cls, size, price, exectype, **kwargs):
        """创建订单对象"""
        order = order_cls()
        order.data = data
        order.size = size
        order.price = price
        order.exectype = exectype or bt.Order.Market
        order.simulated = False  # 真实订单

        # 设置订单类型
        if order.exectype == bt.Order.Market:
            order.ordtype = self.broker_mapping['order_types'][bt.Order.Market]
        elif order.exectype == bt.Order.Limit:
            order.ordtype = self.broker_mapping['order_types'][bt.Order.Limit]
        elif order.exectype == bt.Order.Stop:
            order.ordtype = self.broker_mapping['order_types'][bt.Order.Stop]
            # 对于stop订单，price是触发价
            order.trigger = price
        elif order.exectype == bt.Order.StopLimit:
            order.ordtype = self.broker_mapping['order_types'][bt.Order.StopLimit]
            order.trigger = price
            order.pricelimit = kwargs.get('pricelimit')

        return order

    def _submit_order(self, order):
        """提交订单到交易所"""
        try:
            # 准备参数
            symbol = order.data._name
            params = {}

            # 设置订单参数
            if order.exectype == bt.Order.Market:
                ccxt_order = self.exchange.create_market_buy_order(
                    symbol, order.size, params)
            elif order.exectype == bt.Order.Limit:
                ccxt_order = self.exchange.create_limit_buy_order(
                    symbol, order.size, order.price, params)
            elif order.exectype == bt.Order.Stop:
                # 停损单
                params['stopPrice'] = order.trigger
                ccxt_order = self.exchange.create_order(
                    symbol, 'market', 'buy', order.size, None, params)
            elif order.exectype == bt.Order.StopLimit:
                params['stopPrice'] = order.trigger
                params['price'] = order.pricelimit
                ccxt_order = self.exchange.create_order(
                    symbol, 'limit', 'buy', order.size, order.pricelimit, params)

            # 保存CCXT订单ID
            order.ccxt_id = ccxt_order['id']
            self._orders[order.ccxt_id] = order

            # 更新订单状态
            order.accepted()

            # 通知策略
            self.notify(order)

        except Exception as e:
            order.reject()
            self.notify(order)
            raise

    def _order_loop(self):
        """订单状态检查循环"""
        while self._running:
            try:
                # 检查所有待处理订单
                orders = [o for o in self._orders.values()
                          if o.status in [order.Accepted, order.Partial]]

                for order in orders:
                    self._check_order(order)

                time.sleep(self.p.check_interval)

            except Exception as e:
                print(f"Order check error: {e}")
                time.sleep(self.p.check_interval)

    def _check_order(self, order):
        """检查订单状态"""
        try:
            ccxt_order = self.exchange.fetch_order(order.ccxt_id)

            # 检查成交
            if 'filled' in ccxt_order:
                filled = ccxt_order['filled']
                if filled > 0:
                    self._process_fill(order, ccxt_order)

            # 检查状态
            status = ccxt_order['status']
            if status == 'closed':
                order.completed()
                self.notify(order)
            elif status == 'canceled':
                order.cancelled()
                self.notify(order)
            elif status == 'open' or status == 'expired':
                # 继续等待
                pass

        except Exception as e:
            print(f"Fetch order error: {e}")

    def _process_fill(self, order, ccxt_order):
        """处理成交"""
        # 获取成交详情
        if 'trades' in ccxt_order and ccxt_order['trades']:
            # 使用trade数组
            for trade in ccxt_order['trades']:
                self._fill_order(order, trade)
        else:
            # 使用累计成交量
            filled = ccxt_order.get('filled', 0)
            remaining = ccxt_order.get('remaining', 0)
            price = ccxt_order.get('price', 0)

            if price > 0:
                # 计算已成交部分
                executed = order.executed
                if executed.size < filled:
                    # 新成交
                    new_size = filled - executed.size
                    order.execute(new_size, price)

    def _balance_loop(self):
        """余额更新循环"""
        while self._running:
            try:
                # 强制刷新余额
                self._refresh_balance()
                time.sleep(self._balance_ttl)

            except Exception as e:
                print(f"Balance update error: {e}")
                time.sleep(self._balance_ttl)

    def _refresh_balance(self):
        """刷新账户余额"""
        try:
            balance = self.exchange.fetch_balance()

            # 更新余额缓存
            self._balance_cache = balance
            self._balance_timestamp = time.time()

        except Exception as e:
            print(f"Fetch balance error: {e}")

    def get_balance(self, currency=None):
        """获取余额"""
        # 使用缓存
        if currency:
            return self._balance_cache.get(currency, {}).get('free', 0)
        return self._balance_cache

    def get_wallet_balance(self):
        """获取钱包余额"""
        return self.get_balance()
```

#### 2. CCXTFeed重写

```python
# feeds/ccxtfeed.py
import backtrader as bt
from backtrader.utils import date2num
import time
import threading
import queue

class CCXTFeed(bt.DataBase):
    """CCXT数据源

    使用CCXT fetch_ohlcv获取历史和实时数据
    """

    params = (
        ('exchange', None),
        ('symbol', None),
        ('timeframe', '1h'),
        ('fromdate', None),
        ('todate', None),
        ('drop_newest', True),  # 丢弃不完整K线
        ('live', False),
        ('check_interval', 60),  # 实时数据检查间隔(秒)
    )

    # 状态常量
    _ST_LIVE, _ST_HISTORBACK, _ST_OVER = range(3)

    def __init__(self):
        super().__init__()

        self._state = self._ST_HISTORBACK
        self._last_ts = 0
        self._queue = queue.Queue()

        # CCXT实例
        import ccxt
        self.exchange = getattr(ccxt, self.p.exchange)()

        # 线程
        self._data_thread = None
        self._running = False

    def start(self):
        """启动数据源"""
        if self.p.fromdate:
            self._load_history()
        else:
            self._state = self._ST_LIVE

        if self.p.live:
            self._start_live()

    def _load_history(self):
        """加载历史数据"""
        granularity = self._get_granularity()
        since = self.p.fromdate.timestamp() * 1000

        while True:
            try:
                # 获取OHLCV数据 (每次最多1000条)
                ohlcv = self.exchange.fetch_ohlcv(
                    self.p.symbol,
                    timeframe=granularity,
                    since=since,
                    limit=1000
                )

                if not ohlcv:
                    break

                # 处理数据
                for bar in ohlcv:
                    self._process_bar(bar)

                # 更新时间戳
                since = ohlcv[-1][0] + 1

                # 检查是否到达结束日期
                if self.p.todate and ohlcv[-1][0] >= self.p.todate.timestamp() * 1000:
                    break

            except Exception as e:
                print(f"Fetch history error: {e}")
                break

        # 转换到实时状态
        self._state = self._ST_LIVE

    def _start_live(self):
        """启动实时数据"""
        self._running = True
        self._data_thread = threading.Thread(
            target=self._data_loop, daemon=True)
        self._data_thread.start()

    def _data_loop(self):
        """实时数据循环"""
        while self._running:
            try:
                if self._state == self._ST_LIVE:
                    self._update_bar()

                time.sleep(self.p.check_interval)

            except Exception as e:
                print(f"Live data error: {e}")
                time.sleep(self.p.check_interval)

    def _update_bar(self):
        """更新K线"""
        try:
            # 获取最新K线
            ohlcv = self.exchange.fetch_ohlcv(
                self.p.symbol,
                timeframe=self._get_granularity(),
                limit=1
            )

            if ohlcv:
                bar = ohlcv[0]

                # 检查是否重复
                if bar[0] <= self._last_ts:
                    return

                # 检查是否是不完整K线
                if self._is_incomplete_bar(bar):
                    if self.p.drop_newest:
                        return

                # 处理K线
                self._process_bar(bar)
                self._last_ts = bar[0]

        except Exception as e:
            print(f"Update bar error: {e}")

    def _is_incomplete_bar(self, bar):
        """检查是否是不完整K线"""
        # 最新K线可能还未完成
        timestamp = bar[0]
        now = time.time() * 1000

        # 如果K线时间在当前时间区间内，认为可能不完整
        granularity_ms = self._get_granularity_ms()
        bar_end = timestamp + granularity_ms

        return bar_end > now

    def _process_bar(self, bar):
        """处理K线数据"""
        timestamp, open_price, high, low, close, volume = bar

        # 转换并添加到lines
        self.lines.datetime[0] = date2num(timestamp)
        self.lines.open[0] = open_price
        self.lines.high[0] = high
        self.lines.low[0] = low
        self.lines.close[0] = close
        self.lines.volume[0] = volume

    def _get_granularity(self):
        """获取CCXT时间框架"""
        tf_map = {
            (bt.TimeFrame.Minutes, 1): '1m',
            (bt.TimeFrame.Minutes, 5): '5m',
            (bt.TimeFrame.Minutes, 15): '15m',
            (bt.TimeFrame.Minutes, 30): '30m',
            (bt.TimeFrame.Minutes, 60): '1h',
            (bt.TimeFrame.Minutes, 240): '4h',
            (bt.TimeFrame.Minutes, 1440): '1d',
        }

        # 解析时间框架
        if isinstance(self.p.timeframe, int):
            tf = (bt.TimeFrame.Minutes, self.p.timeframe)
        else:
            tf = self.p.timeframe

        return tf_map.get(tf, '1h')

    def _get_granularity_ms(self):
        """获取时间框架毫秒数"""
        granularity = self._get_granularity()
        tf_map = {
            '1m': 60 * 1000,
            '5m': 5 * 60 * 1000,
            '15m': 15 * 60 * 1000,
            '1h': 60 * 60 * 1000,
            '4h': 4 * 60 * 60 * 1000,
            '1d': 24 * 60 * 60 * 1000,
        }
        return tf_map.get(granularity, 60 * 60 * 1000)

    def haslivedata(self):
        """是否有实时数据"""
        return self._state == self._ST_LIVE

    def stop(self):
        """停止数据源"""
        self._running = False
```

#### 3. WebSocket支持

```python
# ccxt/websocket.py
import ccxt.async_support
import asyncio
import json

class CCXTWebSocket:
    """CCXT WebSocket管理器

    支持WebSocket实时数据流和订单更新
    """

    def __init__(self, exchange_id, symbol):
        self.exchange_id = exchange_id
        self.symbol = symbol

        # 创建异步交易所实例
        exchange_class = getattr(ccxt.async_support, exchange_id)
        self.exchange = exchange_class({
            'enableRateLimit': True,
        })

        self.loop = None
        self.running = False

    async def connect(self):
        """建立WebSocket连接"""
        await self.exchange.load_markets()

        if self.exchange.has['watchTicker']:
            await self.exchange.watch_ticker(self.symbol)
        if self.exchange.has['watchOHLCV']:
            await self.exchange.watch_ohlcv(
                self.symbol,
                timeframe=self.timeframe
            )

    async def watch_ticker(self, callback):
        """监听ticker数据"""
        while self.running:
            try:
                ticker = await self.exchange.watch_ticker(self.symbol)
                await callback(ticker)
            except Exception as e:
                print(f"WebSocket error: {e}")
                await asyncio.sleep(1)

    async def watch_ohlcv(self, callback):
        """监听K线数据"""
        while self.running:
            try:
                ohlcv = await self.exchange.watch_ohlcv(
                    self.symbol,
                    timeframe=self.timeframe
                )
                await callback(ohlcv)
            except Exception as e:
                print(f"WebSocket error: {e}")
                await asyncio.sleep(1)

    def start(self):
        """启动WebSocket"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        self.running = True
        self.loop.run_until_complete(self.connect())

    def stop(self):
        """停止WebSocket"""
        self.running = False
        if self.loop:
            self.loop.close()


class WebSocketFeed(CCXTFeed):
    """WebSocket数据源"""

    params = (
        ('use_websocket', True),
        ('ws_callbacks', None),
    )

    def _start_live(self):
        """启动WebSocket实时数据"""
        if not self.p.use_websocket:
            return super()._start_live()

        self.ws = CCXTWebSocket(self.p.exchange, self.p.symbol)
        self.ws_thread = threading.Thread(
            target=self._ws_run, daemon=True)
        self.ws_thread.start()

    def _ws_run(self):
        """WebSocket运行循环"""
        async def watch_loop():
            await self.ws.connect()

            async def ohlcv_callback(ohlcv):
                for bar in ohlcv:
                    self._process_bar(bar)

            await self.ws.watch_ohlcv(ohlcv_callback)

        # 运行asyncio循环
        import asyncio
        asyncio.run(watch_loop())
```

#### 4. 限流管理

```python
# ccxt/ratelimit.py
import time
from functools import wraps

class RateLimiter:
    """API限流管理器"""

    def __init__(self, requests_per_minute=1200):
        """
        Args:
            requests_per_minute: 每分钟允许的请求数
        """
        self.rpm = requests_per_minute
        self.request_times = []
        self.lock = threading.Lock()

    def acquire(self):
        """获取调用许可，如果需要则等待"""
        with self.lock:
            now = time.time()

            # 清除1分钟前的记录
            cutoff = now - 60
            self.request_times = [t for t in self.request_times if t > cutoff]

            # 检查是否需要等待
            if len(self.request_times) >= self.rpm:
                # 等待到最早的请求超过1分钟
                wait_time = 60 - (now - self.request_times[0])
                if wait_time > 0:
                    time.sleep(wait_time)
                    now = time.time()
                    self.request_times = []

            # 记录本次请求
            self.request_times.append(now)

    def get_wait_time(self):
        """获取建议等待时间(秒)"""
        with self.lock:
            now = time.time()

            # 清除1分钟前的记录
            cutoff = now - 60
            self.request_times = [t for t in self.request_times if t > cutoff]

            if len(self.request_times) >= self.rpm:
                return 60 - (now - self.request_times[0])
            return 0


def retry_with_backoff(max_retries=3, base_delay=1.0, max_delay=60.0):
    """带指数退避的重试装饰器

    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟时间(秒)
        max_delay: 最大延迟时间(秒)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    # 如果是最后一次尝试，直接抛出
                    if attempt == max_retries - 1:
                        raise

                    # 计算延迟时间 (指数退避)
                    delay = min(base_delay * (2 ** attempt), max_delay)

                    print(f"Retry {attempt + 1}/{max_retries} "
                          f"after {delay:.2f}s: {e}")
                    time.sleep(delay)

            raise last_exception

        return wrapper
    return decorator
```

#### 5. Bracket订单

```python
# ccxt/orders/bracket.py
import backtrader as bt

class BracketOrderManager:
    """Bracket订单管理器

    实现OCO (One-Cancels-Other) 订单
    """

    def __init__(self, broker):
        self.broker = broker
        self.brackets = {}  # entry_order_id -> (stop_order_id, limit_order_id)

    def create_bracket(self, data, size, entry_price, stop_price, limit_price):
        """创建Bracket订单

        Args:
            data: 数据源
            size: 数量
            entry_price: 入场价格
            stop_price: 止损价格
            limit_price: 止盈价格

        Returns:
            entry_order: 入场订单
        """
        # 1. 创建入场订单
        entry_order = self.broker.buy(data, size, price=entry_price, exectype=bt.Order.Limit)

        # 2. 创建关联的止损和止盈订单
        stop_order = self.broker.sell(
            data, size,
            price=stop_price,
            exectype=bt.Order.Stop,
            oco=entry_order  # 关联入场订单
        )

        limit_order = self.broker.sell(
            data, size,
            price=limit_price,
            exectype=bt.Order.Limit,
            oco=entry_order  # 关联入场订单
        )

        # 保存关联关系
        self.brackets[entry_order.ref] = {
            'stop': stop_order.ref,
            'limit': limit_order.ref,
            'entry': entry_order.ref
        }

        return entry_order

    def on_order_fill(self, order):
        """订单成交处理

        当入场订单成交时激活止损/止盈
        当任一保护订单成交时取消另一个
        """
        # 检查是否是入场订单成交
        for entry_id, bracket in self.brackets.items():
            if order.ref == entry_id:
                # 激活保护订单
                self._activate_protection(bracket)
                break

            # 检查是否是保护订单成交
            if order.ref in [bracket['stop'], bracket['limit']]:
                # 取消另一个保护订单
                self._cancel_other_protection(order.ref, bracket)
                break

    def _activate_protection(self, bracket):
        """激活保护订单"""
        # 将止损和止盈订单状态从pending变为active
        pass

    def _cancel_other_protection(self, filled_order_ref, bracket):
        """取消另一个保护订单"""
        if filled_order_ref == bracket['stop']:
            # 止损成交，取消止盈
            self.broker.cancel(bracket['limit'])
        else:
            # 止盈成交，取消止损
            self.broker.cancel(bracket['stop'])

        # 清理bracket记录
        del self.brackets[bracket['entry']]
```

### 使用示例

#### 示例1: 基础CCXT回测和实盘

```python
import backtrader as bt
from backtrader.brokers import CCXTBroker
from backtrader.feeds import CCXTFeed
import ccxt

# 创建CCXT Store
exchange_config = {
    'apiKey': 'your_api_key',
    'secret': 'your_secret',
    'enableRateLimit': True,
}

store = CCXTStore(
    exchange='binance',
    config=exchange_config
)

# 创建Cerebro
cerebro = bt.Cerebro()

# 设置Broker
cerebro.setbroker(CCXTBroker(store=store))

# 添加数据
data = CCXTFeed(
    exchange='binance',
    symbol='BTC/USDT',
    timeframe='1h',
    fromdate=datetime(2023, 1, 1),
    todate=datetime(2023, 12, 31),
    live=False  # 回测模式
)
cerebro.adddata(data)

# 运行
result = cerebro.run()
```

#### 示例2: 实盘交易

```python
# 实盘配置
data = CCXTFeed(
    exchange='binance',
    symbol='BTC/USDT',
    timeframe='1h',
    live=True,  # 实时模式
    check_interval=30
)

cerebro.setbroker(CCXTBroker(
    store=store,
    check_interval=5,
    use_websocket=True
))
```

#### 示例3: Bracket订单

```python
class BracketStrategy(bt.Strategy):
    """使用Bracket订单的策略"""

    def __init__(self):
        self.bracket_mgr = BracketOrderManager(self.broker)

    def next(self):
        if not self.position:
            if self.data.close[0] > self.data.sma[0]:
                # 创建Bracket订单
                entry = self.data.close[0]
                stop = entry * 0.95
                limit = entry * 1.05

                self.bracket_mgr.create_bracket(
                    self.data,
                    size=0.1,
                    entry_price=entry,
                    stop_price=stop,
                    limit_price=limit
                )
```

### 实施计划

#### 第一阶段 (P0功能)
1. 重写CCXTBroker使用真正的CCXT API
2. 重写CCXTFeed使用fetch_ohlcv
3. 实现基础的订单状态检查
4. 实现历史数据加载

#### 第二阶段 (P1功能)
1. 添加WebSocket支持
2. 实现多线程数据更新
3. 添加Bracket订单支持
4. 实现限流优化

#### 第三阶段 (P2功能)
1. 添加更多交易所特定配置
2. 实现高级订单类型
3. 添加更多性能监控
4. 实现自动重连优化

---

## 总结

通过借鉴ccxt-store项目的设计理念，Backtrader的CCXT集成可以进行以下改进：

1. **真正的CCXT集成**: 修复Broker和Feed未使用CCXT的问题
2. **WebSocket支持**: 实现真正的实时数据流
3. **多线程架构**: 提升性能和响应性
4. **Bracket订单**: 支持OCO订单提升风险管理能力
5. **智能限流**: 避免触及交易所API限制
6. **交易所配置**: 灵活适配不同交易所特性

这些改进将使Backtrader成为一个功能完整的加密货币实盘交易平台，而不仅仅是一个回测框架。
