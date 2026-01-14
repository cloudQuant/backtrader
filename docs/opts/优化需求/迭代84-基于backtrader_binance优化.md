### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/backtrader_binance
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### backtrader_binance项目简介
backtrader_binance是Binance交易所与backtrader的集成项目，具有以下核心特点：
- **Binance集成**: 与Binance API集成
- **现货交易**: 支持现货交易
- **合约交易**: 支持期货合约交易
- **实时数据**: WebSocket实时数据
- **历史数据**: 历史K线数据获取
- **订单管理**: 完整订单管理

### 重点借鉴方向
1. **加密货币**: 加密货币市场特性
2. **WebSocket**: WebSocket数据流
3. **合约交易**: 期货合约交易支持
4. **API设计**: REST API封装
5. **数据源**: 多种数据源支持
6. **实盘交易**: 实盘交易接口

---

## 架构对比分析

### Backtrader 核心特点

**优势:**
1. **成熟的回测引擎**: Cerebro统一管理策略、数据、经纪商、分析器
2. **完整的Line系统**: 基于循环缓冲区的高效时间序列数据管理
3. **丰富的技术指标**: 60+内置技术指标
4. **灵活的策略系统**: 支持多种策略编写方式
5. **多市场支持**: 支持股票、期货、加密货币等多种市场

**局限:**
1. **实时交易支持弱**: 主要面向回测，实盘交易需要额外配置
2. **WebSocket支持不完善**: 缺少统一的WebSocket数据流管理
3. **加密货币特性缺失**: 缺少24/7交易、手续费层级等加密货币特性
4. **订单状态管理**: 缺少实时订单状态更新机制
5. **数据缓存机制**: 缺少智能数据缓存和增量更新

### Backtrader_Binance 核心特点

**优势:**
1. **完善的Store架构**: Store-Broker-Feed三层架构设计
2. **WebSocket实时数据流**: ThreadedWebsocketManager集成，支持实时K线和用户数据
3. **现货合约统一**: BinanceStore和BinanceFutureStore统一接口
4. **智能数据缓存**: 本地CSV缓存+增量更新机制
5. **完整的订单管理**: 实时订单状态更新，支持多种订单类型
6. **重试机制**: 完善的API请求重试和错误处理
7. **多数据源支持**: Binance API、本地缓存、第三方数据源无缝切换
8. **状态机模式**: 清晰的数据流状态管理（ST_LIVE、ST_HISTORBACK、ST_OVER）
9. **K线形态策略**: 86个内置K线形态策略
10. **风险控制**: 插针检测、止损止盈自动执行

**局限:**
1. **依赖Binance API**: 功能与Binance API强耦合
2. **扩展性有限**: 添加其他交易所需要大量重复代码
3. **文档缺失**: 缺少详细的架构文档
4. **测试覆盖不足**: 缺少完整的单元测试

---

## 需求规格文档

### 1. 统一的Store架构 (优先级: 高)

**需求描述:**
参考backtrader_binance的Store模式，为Backtrader设计统一的数据存储和交易执行架构，支持多种交易所和数据源。

**功能需求:**
1. **Store基类**: 定义统一的Store接口，包含数据获取和订单执行
2. **Broker集成**: Store自动创建对应的Broker实例
3. **Feed集成**: Store支持创建多个数据Feed
4. **状态管理**: 统一的状态机管理连接、数据获取等状态
5. **重试机制**: 内置指数退避重试装饰器
6. **代理支持**: 自动处理代理配置

**非功能需求:**
1. 保持现有API兼容性
2. 支持异步操作
3. 线程安全设计

### 2. WebSocket数据流管理 (优先级: 高)

**需求描述:**
建立统一的WebSocket数据流管理系统，支持实时K线、订单状态、账户更新等多种数据流。

**功能需求:**
1. **WebSocket管理器**: 统一的WebSocket连接管理
2. **多流支持**: 同时订阅多个数据流（K线、深度、交易等）
3. **自动重连**: 连接断开时自动重连
4. **消息路由**: 消息自动路由到对应的处理函数
5. **心跳检测**: 定期ping/pong保持连接
6. **线程安全**: WebSocket消息与主线程的安全通信

**非功能需求:**
1. 低延迟（<100ms）
2. 支持高并发消息处理
3. 内存占用可控

### 3. 加密货币市场特性 (优先级: 高)

**需求描述:**
添加加密货币市场的特殊特性支持，包括24/7交易、手续费层级、资金费率等。

**功能需求:**
1. **24/7交易时间**: 支持无间断交易时间
2. **手续费层级**: 根据交易量动态计算手续费
3. **资金费率**: 合约资金费率计算和收取
4. **Maker/Taker费率**: 区分挂单和吃单费率
5. **最小交易量**: 加密货币特有的最小交易单位
6. **价格精度**: 动态价格和数量精度

**非功能需求:**
1. 准确的费用计算
2. 符合交易所规则

### 4. 智能数据缓存 (优先级: 中)

**需求描述:**
实现本地数据缓存机制，避免重复请求历史数据，支持增量更新。

**功能需求:**
1. **本地缓存**: 数据按月缓存到本地CSV/数据库
2. **增量更新**: 只下载缺失的时间段数据
3. **数据合并**: 自动合并多个文件的数据
4. **缓存检查**: 启动时检查并更新过期缓存
5. **数据验证**: 校验数据完整性和连续性
6. **压缩存储**: 支持数据压缩节省空间

**非功能需求:**
1. 缓存读取速度优于API请求
2. 支持多时间周期

### 5. 实时订单状态管理 (优先级: 中)

**需求描述:**
建立实时订单状态更新机制，通过WebSocket推送订单状态变化。

**功能需求:**
1. **订单状态枚举**: 新建、挂起、部分成交、完全成交、已取消、拒绝
2. **WebSocket推送**: 实时接收订单执行报告
3. **状态同步**: 订单状态与交易所保持同步
4. **成交记录**: 详细的成交价格和数量记录
5. **订单事件**: 订单状态变化触发事件通知
6. **历史订单**: 查询历史订单记录

**非功能需求:**
1. 状态更新延迟<500ms
2. 不丢消息

### 6. 合约交易支持 (优先级: 中)

**需求描述:**
完善期货合约交易支持，包括杠杆、保证金、仓位管理等。

**功能需求:**
1. **杠杆设置**: 动态调整杠杆倍数
2. **保证金管理**: 维持保证金和追加保证金
3. **仓位模式**: 双向持仓和单向持仓
4. **合约规格**: 支持永续合约和交割合约
5. **强制平仓**: 模拟强平价格和触发条件
6. **资金费率**: 定期收取/支付资金费率

### 7. 风险控制增强 (优先级: 中)

**需求描述:**
参考backtrader_binance的风险控制机制，添加插针检测、异常交易检测等功能。

**功能需求:**
1. **插针检测**: 检测异常价格波动
2. **异常停机**: 检测到异常时自动停止交易
3. **仓位限制**: 单品种和总仓位限制
4. **止损止盈**: 自动执行止损止盈
5. **最大回撤控制**: 回撤超限时停止交易
6. **异常通知**: 邮件/短信通知

---

## 设计文档

### 1. Store架构设计

#### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                        Cerebro                          │
└─────────────────────────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
    ┌─────────┐      ┌─────────┐      ┌─────────┐
    │  Feed   │      │Strategy │      │ Broker  │
    └────┬────┘      └─────────┘      └────┬────┘
         │                                  │
         └────────────┬─────────────────────┘
                      │
              ┌───────▼────────┐
              │     Store      │
              │  (抽象基类)     │
              └───────┬────────┘
                      │
          ┌───────────┼───────────┐
          │           │           │
          ▼           ▼           ▼
    ┌─────────┐ ┌─────────┐ ┌──────────┐
    │ExchangeA│ │ExchangeB│ │LocalData │
    │ Store   │ │ Store   │ │ Store    │
    └─────────┘ └─────────┘ └──────────┘
```

#### 1.2 Store基类设计

```python
# backtrader/store/store_base.py
from abc import ABC, abstractmethod
import threading
from enum import Enum
from functools import wraps
import time

class StoreState(Enum):
    """Store状态枚举"""
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    ERROR = 3

class StoreBase(ABC):
    """
    数据存储和交易执行统一接口
    """
    _datas = {}  # 管理的DataFeed
    _broker = None  # 对应的Broker

    def __init__(self, credentials=None, retries=3, timeout=30,
                 proxy=None, testnet=False):
        """
        Args:
            credentials: API密钥等认证信息
            retries: 请求重试次数
            timeout: 请求超时时间
            proxy: 代理配置
            testnet: 是否使用测试网
        """
        self.credentials = credentials or {}
        self.retries = retries
        self.timeout = timeout
        self.proxy = self._parse_proxy(proxy)
        self.testnet = testnet
        self._state = StoreState.DISCONNECTED
        self._lock = threading.Lock()

        # 初始化客户端
        self._client = None
        self._ws_manager = None

    @staticmethod
    def _parse_proxy(proxy):
        """解析代理配置"""
        if not proxy:
            return {}
        if isinstance(proxy, dict):
            return proxy
        if isinstance(proxy, str):
            return {'http': proxy, 'https': proxy}
        return {}

    @staticmethod
    def retry_on_error(max_retries=None, delay=1.0, backoff=2.0):
        """错误重试装饰器"""
        def decorator(func):
            @wraps(func)
            def wrapper(self, *args, **kwargs):
                retries = max_retries or self.retries
                current_delay = delay

                for attempt in range(retries):
                    try:
                        return func(self, *args, **kwargs)
                    except Exception as e:
                        if attempt == retries - 1:
                            raise
                        time.sleep(current_delay)
                        current_delay *= backoff
            return wrapper
        return decorator

    @property
    def state(self):
        """获取当前状态"""
        return self._state

    @abstractmethod
    def connect(self):
        """建立连接"""
        pass

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        pass

    @abstractmethod
    def get_broker(self):
        """获取Broker实例"""
        pass

    @abstractmethod
    def getdata(self, symbol, timeframe, compression, fromdate, todate,
                live=False, **kwargs):
        """获取数据Feed"""
        pass

    @abstractmethod
    def get_historical_data(self, symbol, timeframe, compression,
                           start_date, end_date=None):
        """获取历史数据"""
        pass

    def _add_data(self, data):
        """添加DataFeed到管理列表"""
        with self._lock:
            self._datas[id(data)] = data

    def _remove_data(self, data):
        """从管理列表移除DataFeed"""
        with self._lock:
            self._datas.pop(id(data), None)
```

#### 1.3 Broker基类设计

```python
# backtrader/store/broker_base.py
from backtrader.broker import BrokerBase
from backtrader.order import Order
from enum import Enum

class OrderStatus(Enum):
    """订单状态"""
    CREATED = 'created'
    NEW = 'new'
    PARTIALLY_FILLED = 'partially_filled'
    FILLED = 'filled'
    CANCELED = 'canceled'
    REJECTED = 'rejected'
    EXPIRED = 'expired'

class StoreBroker(BrokerBase):
    """
    基于Store的Broker基类
    """
    params = (
        ('check_buyprice', False),  # 不检查买入价格合法性
        ('check_sellprice', False),  # 不检查卖出价格合法性
    )

    def __init__(self, store):
        """
        Args:
            store: Store实例
        """
        self._store = store
        self._orders = {}  # 订单管理: {order_id: Order}
        self._orders_rev = {}  # 反向映射: {exchange_order_id: order_id}
        super().__init__()

    @property
    def store(self):
        """获取关联的Store"""
        return self._store

    def _submit(self, owner, data, side, exectype, size, price):
        """提交订单到交易所"""
        raise NotImplementedError

    def _cancel(self, order):
        """取消订单"""
        raise NotImplementedError

    def _get_order(self, order_id):
        """获取订单"""
        return self._orders.get(order_id)

    def _get_order_by_exchange_id(self, exchange_id):
        """通过交易所订单ID获取订单"""
        order_id = self._orders_rev.get(exchange_id)
        if order_id:
            return self._orders.get(order_id)
        return None

    def _add_order(self, order, exchange_id=None):
        """添加订单到管理"""
        self._orders[order.ref] = order
        if exchange_id:
            self._orders_rev[exchange_id] = order.ref

    def _remove_order(self, order):
        """从管理移除订单"""
        self._orders.pop(order.ref, None)

    def _execute_order(self, order, dt, size, price, commission=0):
        """执行订单"""
        # 更新持仓
        if order.isbuy():
            self.buying = size
            self.buyprice = price
        else:
            self.selling = size
            self.sellprice = price

        # 执行订单
        order.execute(dt, size, price, commission, closed=True)

    def _set_order_status(self, order, status):
        """设置订单状态"""
        if status == OrderStatus.NEW:
            order.accepted()
        elif status == OrderStatus.PARTIALLY_FILLED:
            order.partial()
        elif status == OrderStatus.FILLED:
            # 已在_execute_order中处理
            pass
        elif status == OrderStatus.CANCELED:
            order.cancel()
        elif status == OrderStatus.REJECTED:
            order.reject()
```

#### 1.4 Feed基类设计

```python
# backtrader/store/feed_base.py
from backtrader.feed import DataBase
from enum import Enum
import threading

class FeedState(Enum):
    """Feed状态"""
    DISCONNECTED = 0
    HISTORICAL = 1  # 获取历史数据
    LIVE = 2        # 实时数据
    OVER = 3        # 数据结束

class StoreFeed(DataBase):
    """
    基于Store的DataFeed基类
    """
    params = (
        ('symbol', None),
        ('timeframe', None),
        ('compression', 1),
        ('fromdate', None),
        ('todate', None),
        ('live', False),
    )

    def __init__(self, store):
        self._store = store
        self._state = FeedState.DISCONNECTED
        self._live_bars = False
        self._hist_bars = False
        self._data = []  # 缓存数据
        self._lock = threading.Lock()
        super().__init__()

    def haslivedata(self):
        """是否有实时数据"""
        return self._live_bars

    def islive(self):
        """是否实时模式"""
        return self.p.live

    def start(self):
        """启动数据源"""
        if not self.p.live:
            # 纯历史模式
            self._state = FeedState.HISTORICAL
            self._load_historical_data()
        else:
            # 实时模式
            self._state = FeedState.HISTORICAL
            self._load_historical_data()
            self._start_live()

    def stop(self):
        """停止数据源"""
        if self._state == FeedState.LIVE:
            self._stop_live()
        self._state = FeedState.OVER

    def _load_historical_data(self):
        """加载历史数据"""
        raise NotImplementedError

    def _start_live(self):
        """启动实时数据"""
        raise NotImplementedError

    def _stop_live(self):
        """停止实时数据"""
        raise NotImplementedError

    def _handle_ws_message(self, msg):
        """处理WebSocket消息"""
        raise NotImplementedError
```

### 2. WebSocket管理器设计

```python
# backtrader/ws/ws_manager.py
import threading
import queue
import time
import logging
from enum import Enum
from typing import Callable, Dict, List

class WSState(Enum):
    """WebSocket状态"""
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    RECONNECTING = 3
    STOPPED = 4

class WebSocketMessage:
    """WebSocket消息"""
    def __init__(self, stream, data):
        self.stream = stream  # 数据流名称
        self.data = data      # 消息数据
        self.timestamp = time.time()

class WebSocketManager:
    """
    统一的WebSocket管理器
    """
    def __init__(self, max_reconnect=10, ping_interval=20,
                 ping_timeout=10, queue_size=10000):
        """
        Args:
            max_reconnect: 最大重连次数
            ping_interval: ping间隔（秒）
            ping_timeout: ping超时（秒）
            queue_size: 消息队列大小
        """
        self._state = WSState.DISCONNECTED
        self._max_reconnect = max_reconnect
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._reconnect_count = 0
        self._last_ping = 0

        # 数据流管理
        self._streams = {}  # {stream_name: callback}
        self._active_streams = set()  # 活跃的流

        # 消息队列
        self._message_queue = queue.Queue(maxsize=queue_size)

        # 线程
        self._ws_thread = None
        self._process_thread = None
        self._ping_thread = None
        self._running = False

        # 日志
        self._logger = logging.getLogger(__name__)

        # WebSocket连接（由子类实现）
        self._ws = None

    def connect(self):
        """建立WebSocket连接"""
        if self._state in [WSState.CONNECTED, WSState.CONNECTING]:
            return

        self._state = WSState.CONNECTING
        self._running = True

        # 启动线程
        self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self._process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._ping_thread = threading.Thread(target=self._ping_loop, daemon=True)

        self._ws_thread.start()
        self._process_thread.start()
        self._ping_thread.start()

    def disconnect(self):
        """断开WebSocket连接"""
        self._running = False
        self._state = WSState.STOPPED

        if self._ws:
            self._ws.close()

    def subscribe(self, stream: str, callback: Callable):
        """
        订阅数据流

        Args:
            stream: 流名称（如 'kline:BTCUSDT:1m'）
            callback: 消息回调函数
        """
        self._streams[stream] = callback

    def unsubscribe(self, stream: str):
        """取消订阅"""
        self._streams.pop(stream, None)
        self._active_streams.discard(stream)

    def _ws_loop(self):
        """WebSocket接收循环"""
        while self._running:
            try:
                # 实现具体的WebSocket连接和消息接收
                # 这里需要子类实现
                self._run_ws()

            except Exception as e:
                self._logger.error(f"WebSocket error: {e}")

                # 尝试重连
                if self._reconnect_count < self._max_reconnect:
                    self._state = WSState.RECONNECTING
                    self._reconnect_count += 1
                    time.sleep(2 ** self._reconnect_count)  # 指数退避
                else:
                    self._state = WSState.DISCONNECTED
                    break

    def _process_loop(self):
        """消息处理循环"""
        while self._running:
            try:
                msg = self._message_queue.get(timeout=1)
                if msg:
                    callback = self._streams.get(msg.stream)
                    if callback:
                        callback(msg.data)
            except queue.Empty:
                continue
            except Exception as e:
                self._logger.error(f"Process error: {e}")

    def _ping_loop(self):
        """心跳循环"""
        while self._running:
            time.sleep(self._ping_interval)

            if self._state == WSState.CONNECTED:
                try:
                    self._send_ping()
                    self._last_ping = time.time()
                except Exception as e:
                    self._logger.error(f"Ping error: {e}")

    def _send_ping(self):
        """发送ping（子类实现）"""
        pass

    def _run_ws(self):
        """运行WebSocket（子类实现）"""
        raise NotImplementedError

    def _put_message(self, stream, data):
        """将消息放入队列"""
        try:
            self._message_queue.put_nowait(WebSocketMessage(stream, data))
        except queue.Full:
            self._logger.warning("Message queue full, dropping message")
```

### 3. 加密货币市场特性设计

#### 3.1 手续费计算器

```python
# backtrader/commission/crypto_commission.py
from backtrader.commission import CommInfoBase
from enum import Enum

class FeeLevel(Enum):
    """手续费层级"""
    VIP0 = (0.0010, 0.0010)   # (maker, taker)
    VIP1 = (0.0009, 0.0010)
    VIP2 = (0.0008, 0.0010)
    VIP3 = (0.0007, 0.0009)
    VIP4 = (0.0007, 0.0008)
    VIP5 = (0.0006, 0.0008)
    VIP6 = (0.0005, 0.0007)
    VIP7 = (0.0004, 0.0007)
    VIP8 = (0.0004, 0.0006)
    VIP9 = (0.0003, 0.0005)

    def __init__(self, maker, taker):
        self.maker_fee = maker
        self.taker_fee = taker

class CryptoCommInfo(CommInfoBase):
    """
    加密货币手续费计算
    """
    params = (
        ('maker_fee', 0.001),    # 默认maker费率 0.1%
        ('taker_fee', 0.001),    # 默认taker费率 0.1%
        ('fee_level', FeeLevel.VIP0),
        ('commission', 0.001),   # 向后兼容
        ('auto_detect_fee', False),  # 自动检测订单类型
    )

    def _getcommission(self, size, price, pseudoexec):
        """
        计算手续费

        考虑maker和taker费率差异
        """
        # 如果启用了自动检测，需要根据订单类型判断
        # 这里简化处理，使用平均费率
        if self.p.auto_detect_fee:
            # 实际实现需要知道订单是limit还是market
            fee_rate = (self.p.maker_fee + self.p.taker_fee) / 2
        else:
            fee_rate = self.p.commission

        return abs(size) * price * fee_rate

    def get_maker_fee(self):
        """获取maker费率"""
        return self.p.maker_fee

    def get_taker_fee(self):
        """获取taker费率"""
        return self.p.taker_fee

    def set_fee_level(self, level):
        """
        根据VIP等级设置费率

        Args:
            level: FeeLevel枚举值
        """
        self.p.maker_fee = level.maker_fee
        self.p.taker_fee = level.taker_fee

    def set_fee_by_volume(self, volume_30d):
        """
        根据30天交易量自动设置VIP等级

        Args:
            volume_30d: 30天交易量（BTC/USDT）
        """
        # 币安VIP等级示例（单位：BTC）
        vip_thresholds = [
            (50, FeeLevel.VIP1),
            (500, FeeLevel.VIP2),
            (1500, FeeLevel.VIP3),
            (5000, FeeLevel.VIP4),
            (10000, FeeLevel.VIP5),
            (20000, FeeLevel.VIP6),
            (50000, FeeLevel.VIP7),
            (100000, FeeLevel.VIP8),
            (300000, FeeLevel.VIP9),
        ]

        for threshold, level in reversed(vip_thresholds):
            if volume_30d >= threshold:
                self.set_fee_level(level)
                return

        self.set_fee_level(FeeLevel.VIP0)
```

#### 3.2 资金费率计算

```python
# backtrader/utils/funding_rate.py
from datetime import datetime, timedelta
from backtrader.utils.py3 import date2num

class FundingRate:
    """
    合约资金费率计算
    """
    def __init__(self, interval_hours=8, rate=0.0001):
        """
        Args:
            interval_hours: 资金费率收取间隔（小时）
            rate: 资金费率（默认0.01%）
        """
        self.interval = timedelta(hours=interval_hours)
        self.rate = rate
        self.last_funding_time = None

    def should_charge(self, current_time):
        """
        检查是否应该收取资金费率

        Args:
            current_time: 当前时间

        Returns:
            bool: 是否应该收取
        """
        if self.last_funding_time is None:
            self.last_funding_time = current_time
            return False

        return (current_time - self.last_funding_time) >= self.interval

    def calculate(self, position_value, rate=None):
        """
        计算资金费率金额

        Args:
            position_value: 持仓价值
            rate: 资金费率（如果为None使用默认值）

        Returns:
            float: 资金费率金额（正数收取，负数支付）
        """
        if rate is None:
            rate = self.rate

        return position_value * rate

    def update_funding_time(self, current_time):
        """更新上次收取时间"""
        self.last_funding_time = current_time

class FundingRateObserver:
    """
    资金费率观察器
    """
    def __init__(self, strategy):
        self.strategy = strategy
        self.funding_rates = {}  # {data: FundingRate}

    def add_funding_rate(self, data, funding_rate):
        """为数据源添加资金费率"""
        self.funding_rates[data] = funding_rate

    def check_funding(self):
        """检查并处理资金费率"""
        for data, fr in self.funding_rates.items():
            current_time = data.datetime.datetime()
            if fr.should_charge(current_time):
                position = self.strategy.getposition(data)
                if position.size != 0:
                    position_value = position.size * data.close[0]
                    fee = fr.calculate(position_value)

                    # 更新账户余额
                    # 注意：这里需要根据多空方向决定是收取还是支付
                    if position.size > 0:  # 多头
                        self.strategy.broker.add_cash(-fee)
                    else:  # 空头
                        self.strategy.broker.add_cash(fee)

                fr.update_funding_time(current_time)
```

#### 3.3 7x24交易时间

```python
# backtrader/utils/crypto_calendar.py
from backtrader.utils.date import date2num
from datetime import time, datetime, timedelta

class CryptoCalendar:
    """
    加密货币7x24小时交易日历
    """
    def __init__(self):
        """加密货币市场24/7开放，没有休市时间"""
        pass

    def is_open(self, dt):
        """
        检查指定时间是否开市

        加密货币市场永远开市
        """
        return True

    def is_trading_time(self, dt):
        """检查是否为交易时间"""
        return True

    def get_next_open_time(self, dt):
        """获取下次开市时间"""
        return dt + timedelta(seconds=1)

    def get_prev_close_time(self, dt):
        """获取上次闭市时间"""
        # 加密货币没有闭市时间，返回一个较小的值
        return dt - timedelta(days=1)

    def get_session_bounds(self, dt):
        """
        获取交易时段边界

        加密货币全天交易，返回一天的开始和结束
        """
        start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1) - timedelta(microseconds=1)
        return start, end
```

### 4. 智能数据缓存设计

```python
# backtrader/store/cache_manager.py
import os
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import logging

class DataCache:
    """
    数据缓存管理器
    """
    def __init__(self, cache_dir='data/cache', format='csv'):
        """
        Args:
            cache_dir: 缓存目录
            format: 存储格式 ('csv', 'parquet', 'pickle')
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.format = format
        self.logger = logging.getLogger(__name__)

    def _get_cache_path(self, symbol, interval, year, month):
        """生成缓存文件路径"""
        filename = f"{symbol}_{interval}_{year}_{month:02d}.{self.format}"
        return self.cache_dir / symbol / interval / filename

    def _get_cache_range(self, symbol, interval, start_date, end_date):
        """
        获取需要缓存的时间范围

        Returns:
            list: 需要下载的 (year, month) 列表
        """
        ranges = []
        current = datetime(start_date.year, start_date.month, 1)
        end = datetime(end_date.year, end_date.month, 1)

        while current <= end:
            ranges.append((current.year, current.month))
            # 移到下个月
            if current.month == 12:
                current = datetime(current.year + 1, 1, 1)
            else:
                current = datetime(current.year, current.month + 1, 1)

        return ranges

    def get_cached_data(self, symbol, interval, start_date, end_date):
        """
        获取缓存数据

        Returns:
            DataFrame: 缓存的数据，如果不存在返回None
        """
        ranges = self._get_cache_range(symbol, interval, start_date, end_date)
        dfs = []

        for year, month in ranges:
            cache_path = self._get_cache_path(symbol, interval, year, month)

            if cache_path.exists():
                try:
                    if self.format == 'csv':
                        df = pd.read_csv(cache_path, parse_dates=['datetime'])
                    elif self.format == 'parquet':
                        df = pd.read_parquet(cache_path)
                    elif self.format == 'pickle':
                        df = pd.read_pickle(cache_path)
                    else:
                        raise ValueError(f"Unsupported format: {self.format}")

                    dfs.append(df)
                except Exception as e:
                    self.logger.warning(f"Failed to read cache {cache_path}: {e}")

        if dfs:
            # 合并所有数据
            result = pd.concat(dfs, ignore_index=True)
            # 过滤时间范围
            result = result[
                (result['datetime'] >= start_date) &
                (result['datetime'] <= end_date)
            ]
            # 排序去重
            result = result.sort_values('datetime').drop_duplicates(subset=['datetime'])
            return result

        return None

    def save_data(self, symbol, interval, data):
        """
        保存数据到缓存

        Args:
            data: DataFrame with 'datetime' column
        """
        data = data.copy()
        data['datetime'] = pd.to_datetime(data['datetime'])

        # 按月分组存储
        grouped = data.groupby([data['datetime'].dt.year, data['datetime'].dt.month])

        for (year, month), group in grouped:
            cache_path = self._get_cache_path(symbol, interval, year, month)
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            # 检查是否已存在数据
            if cache_path.exists():
                # 读取现有数据
                if self.format == 'csv':
                    existing = pd.read_csv(cache_path, parse_dates=['datetime'])
                elif self.format == 'parquet':
                    existing = pd.read_parquet(cache_path)
                else:
                    existing = pd.read_pickle(cache_path)

                # 合并新数据
                combined = pd.concat([existing, group], ignore_index=True)
                combined = combined.sort_values('datetime').drop_duplicates(subset=['datetime'])
                group = combined

            # 保存
            try:
                if self.format == 'csv':
                    group.to_csv(cache_path, index=False)
                elif self.format == 'parquet':
                    group.to_parquet(cache_path, index=False)
                elif self.format == 'pickle':
                    group.to_pickle(cache_path)
            except Exception as e:
                self.logger.error(f"Failed to save cache {cache_path}: {e}")

    def is_cache_complete(self, symbol, interval, start_date, end_date):
        """
        检查缓存是否完整

        Returns:
            bool: 是否有完整缓存
        """
        cached = self.get_cached_data(symbol, interval, start_date, end_date)

        if cached is None or cached.empty:
            return False

        # 检查时间范围是否覆盖
        cached_start = cached['datetime'].min()
        cached_end = cached['datetime'].max()

        if cached_start > start_date or cached_end < end_date:
            return False

        # 检查数据连续性（简化版，只检查是否有缺失的K线）
        # 实际实现应根据interval检查
        return True

    def get_missing_ranges(self, symbol, interval, start_date, end_date):
        """
        获取缺失的时间范围

        Returns:
            list: 缺失的 (start, end) 元组列表
        """
        missing = []
        cached = self.get_cached_data(symbol, interval, start_date, end_date)

        if cached is None or cached.empty:
            missing.append((start_date, end_date))
            return missing

        # 检查开始部分
        cached_start = cached['datetime'].min()
        if cached_start > start_date:
            missing.append((start_date, cached_start - timedelta(seconds=1)))

        # 检查结束部分
        cached_end = cached['datetime'].max()
        if cached_end < end_date:
            missing.append((cached_end + timedelta(seconds=1), end_date))

        return missing

    def clear_cache(self, symbol=None, interval=None, before_date=None):
        """
        清理缓存

        Args:
            symbol: 指定币种，None表示所有
            interval: 指定周期，None表示所有
            before_date: 清理此日期之前的缓存
        """
        if symbol:
            symbol_dir = self.cache_dir / symbol
            if interval:
                interval_dir = symbol_dir / interval
                paths = [interval_dir] if interval_dir.exists() else []
            else:
                paths = symbol_dir.iterdir() if symbol_dir.exists() else []
        else:
            paths = self.cache_dir.rglob('*')

        for path in paths:
            if path.is_file():
                if before_date:
                    # 从文件名解析日期
                    # 这里需要根据文件名格式解析
                    pass
                try:
                    path.unlink()
                    self.logger.info(f"Deleted cache: {path}")
                except Exception as e:
                    self.logger.error(f"Failed to delete {path}: {e}")
```

### 5. 实时订单状态管理设计

```python
# backtrader/store/order_manager.py
from enum import Enum
from datetime import datetime
import threading
from typing import Dict, List, Callable

class OrderEventType(Enum):
    """订单事件类型"""
    CREATED = 'created'
    NEW = 'new'
    PARTIALLY_FILLED = 'partially_filled'
    FILLED = 'filled'
    CANCELED = 'canceled'
    EXPIRED = 'expired'
    REJECTED = 'rejected'
    TRADE = 'trade'  # 成交事件

class OrderEvent:
    """订单事件"""
    def __init__(self, event_type, order_id, data=None):
        self.event_type = event_type
        self.order_id = order_id
        self.data = data or {}
        self.timestamp = datetime.now()

class OrderManager:
    """
    订单管理器，负责跟踪和更新订单状态
    """
    def __init__(self, broker):
        """
        Args:
            broker: 关联的Broker实例
        """
        self.broker = broker
        self._orders: Dict[int, dict] = {}  # {order_id: order_info}
        self._exchange_id_map: Dict[str, int] = {}  # {exchange_id: local_id}
        self._listeners: List[Callable] = []
        self._lock = threading.Lock()

    def add_order(self, order, exchange_id=None):
        """添加订单跟踪"""
        with self._lock:
            info = {
                'order': order,
                'exchange_id': exchange_id,
                'status': OrderEventType.CREATED,
                'filled_size': 0,
                'avg_price': 0,
                'commission': 0,
                'trades': [],
            }
            self._orders[order.ref] = info

            if exchange_id:
                self._exchange_id_map[exchange_id] = order.ref

    def get_order(self, order_id):
        """获取订单信息"""
        return self._orders.get(order_id)

    def get_order_by_exchange_id(self, exchange_id):
        """通过交易所订单ID获取订单"""
        local_id = self._exchange_id_map.get(exchange_id)
        if local_id:
            return self._orders.get(local_id)
        return None

    def update_order_status(self, order_id, status, **kwargs):
        """
        更新订单状态

        Args:
            order_id: 本地订单ID或交易所订单ID
            status: 新状态
            **kwargs: 其他订单信息
        """
        # 处理交易所ID
        if isinstance(order_id, str):
            info = self.get_order_by_exchange_id(order_id)
            if not info and 'client_order_id' in kwargs:
                # 尝试通过client_order_id查找
                local_id = kwargs['client_order_id']
                info = self._orders.get(local_id)
        else:
            info = self._orders.get(order_id)

        if not info:
            return

        old_status = info['status']

        # 更新订单信息
        info['status'] = status
        for key, value in kwargs.items():
            if key in ['filled_size', 'avg_price', 'commission']:
                info[key] = value

        # 处理成交
        if status == OrderEventType.PARTIALLY_FILLED:
            filled = kwargs.get('filled_size', 0)
            price = kwargs.get('price', 0)
            commission = kwargs.get('commission', 0)

            # 更新平均价格
            if info['filled_size'] + filled > 0:
                total_value = (info['avg_price'] * info['filled_size'] +
                              price * filled)
                info['avg_price'] = total_value / (info['filled_size'] + filled)

            info['filled_size'] += filled
            info['commission'] += commission

            # 记录成交
            info['trades'].append({
                'size': filled,
                'price': price,
                'commission': commission,
                'timestamp': kwargs.get('trade_time')
            })

            # 触发事件
            self._notify(OrderEvent(OrderEventType.TRADE, info['order'].ref, kwargs))

        elif status == OrderEventType.FILLED:
            # 更新最终成交信息
            filled = kwargs.get('filled_size', info['order'].size - info['filled_size'])
            price = kwargs.get('price', 0)
            commission = kwargs.get('commission', 0)

            if info['filled_size'] + filled > 0:
                total_value = (info['avg_price'] * info['filled_size'] +
                              price * filled)
                info['avg_price'] = total_value / (info['filled_size'] + filled)

            info['filled_size'] += filled
            info['commission'] += commission

        # 状态变化时触发事件
        if old_status != status:
            event = OrderEvent(status, info['order'].ref, kwargs)
            self._notify(event)

    def cancel_order(self, order_id):
        """取消订单"""
        info = self._orders.get(order_id)
        if info:
            info['status'] = OrderEventType.CANCELED

    def add_listener(self, callback):
        """添加事件监听器"""
        self._listeners.append(callback)

    def remove_listener(self, callback):
        """移除事件监听器"""
        self._listeners.remove(callback)

    def _notify(self, event):
        """通知所有监听器"""
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as e:
                logging.error(f"Order event listener error: {e}")

    def get_open_orders(self):
        """获取所有未完成订单"""
        with self._lock:
            return [
                info for info in self._orders.values()
                if info['status'] in [
                    OrderEventType.CREATED,
                    OrderEventType.NEW,
                    OrderEventType.PARTIALLY_FILLED
                ]
            ]

    def get_order_trades(self, order_id):
        """获取订单的所有成交记录"""
        info = self._orders.get(order_id)
        if info:
            return info['trades']
        return []
```

### 6. 风险控制增强设计

```python
# backtrader/risk/risk_control.py
import logging
from datetime import datetime
from backtrader.utils.py3 import date2num

class RiskEvent:
    """风险事件"""
    def __init__(self, level, message, data=None):
        self.level = level  # 'info', 'warning', 'error', 'critical'
        self.message = message
        self.data = data
        self.timestamp = datetime.now()

class PinBarDetector:
    """
    插针检测器
    """
    def __init__(self, threshold_ratio=0.003, min_body_ratio=0.3):
        """
        Args:
            threshold_ratio: 插针占K线的最小比例
            min_body_ratio: 实体占K线的最大比例（小于此值才算插针）
        """
        self.threshold_ratio = threshold_ratio
        self.min_body_ratio = min_body_ratio

    def is_pin_up(self, high, low, open, close):
        """
        检测上插针

        上插针特征：
        1. 上影线很长（>threshold_ratio * (high-low)）
        2. 实体较小（<min_body_ratio * (high-low)）
        3. 下影线很短
        """
        total_range = high - low
        if total_range <= 0:
            return False

        body_top = max(open, close)
        body_bottom = min(open, close)
        upper_shadow = high - body_top
        lower_shadow = body_bottom - low
        body_size = body_top - body_bottom

        return (
            upper_shadow / total_range > self.threshold_ratio and
            lower_shadow / total_range < 0.2 and
            body_size / total_range < self.min_body_ratio
        )

    def is_pin_down(self, high, low, open, close):
        """检测下插针"""
        total_range = high - low
        if total_range <= 0:
            return False

        body_top = max(open, close)
        body_bottom = min(open, close)
        upper_shadow = high - body_top
        lower_shadow = body_bottom - low
        body_size = body_top - body_bottom

        return (
            lower_shadow / total_range > self.threshold_ratio and
            upper_shadow / total_range < 0.2 and
            body_size / total_range < self.min_body_ratio
        )

    def detect(self, data):
        """
        检测当前K线是否为插针

        Returns:
            dict: {'is_pin': bool, 'direction': 'up'/'down'/None}
        """
        if len(data) < 1:
            return {'is_pin': False, 'direction': None}

        high = data.high[0]
        low = data.low[0]
        open = data.open[0]
        close = data.close[0]

        if self.is_pin_up(high, low, open, close):
            return {'is_pin': True, 'direction': 'up'}
        elif self.is_pin_down(high, low, open, close):
            return {'is_pin': True, 'direction': 'down'}

        return {'is_pin': False, 'direction': None}

class RiskManager:
    """
    风险管理器
    """
    params = (
        ('max_position_pct', 0.3),       # 单品种最大仓位比例
        ('max_total_position_pct', 1.0),  # 总仓位最大比例
        ('max_drawdown_pct', 0.2),        # 最大回撤限制
        ('enable_pin_detection', True),   # 启用插针检测
        ('stop_on_pin', False),           # 检测到插针是否停止交易
        ('pin_threshold_ratio', 0.003),   # 插针检测阈值
    )

    def __init__(self, strategy):
        self.strategy = strategy
        self.pin_detector = PinBarDetector(
            threshold_ratio=self.p.pin_threshold_ratio
        ) if self.p.enable_pin_detection else None

        self.stop_trade = False
        self.events = []
        self.peak_value = strategy.broker.getvalue()
        self.logger = logging.getLogger(__name__)

    def check_entry(self, data, size, price):
        """
        检查是否允许开仓

        Returns:
            (bool, str): (是否允许, 原因)
        """
        if self.stop_trade:
            return False, "Trading stopped due to risk event"

        # 检查单品种仓位限制
        position = self.strategy.getposition(data)
        current_value = abs(position.size * price)
        new_value = current_value + abs(size * price)
        account_value = self.strategy.broker.getvalue()

        if new_value / account_value > self.p.max_position_pct:
            return False, f"Position exceeds {self.p.max_position_pct*100}% limit"

        # 检查总仓位
        total_position = self._get_total_position_value()
        new_total = total_position + abs(size * price)

        if new_total / account_value > self.p.max_total_position_pct:
            return False, f"Total position exceeds {self.p.max_total_position_pct*100}% limit"

        return True, ""

    def check_risk_events(self, data):
        """
        检查风险事件

        Returns:
            list: RiskEvent列表
        """
        events = []
        current_value = self.strategy.broker.getvalue()

        # 检查回撤
        if current_value > self.peak_value:
            self.peak_value = current_value

        drawdown = (self.peak_value - current_value) / self.peak_value

        if drawdown > self.p.max_drawdown_pct:
            event = RiskEvent(
                'critical',
                f"Max drawdown exceeded: {drawdown*100:.2f}%",
                {'drawdown': drawdown}
            )
            events.append(event)
            self.stop_trade = True

        # 检查插针
        if self.pin_detector:
            pin_result = self.pin_detector.detect(data)
            if pin_result['is_pin']:
                event = RiskEvent(
                    'warning',
                    f"Pin bar detected: {pin_result['direction']}",
                    pin_result
                )
                events.append(event)

                if self.p.stop_on_pin:
                    self.stop_trade = True

        self.events.extend(events)
        return events

    def _get_total_position_value(self):
        """获取总持仓价值"""
        total = 0
        for data in self.strategy.datas:
            position = self.strategy.getposition(data)
            if position.size != 0:
                total += abs(position.size * data.close[0])
        return total

    def get_risk_events(self, level=None):
        """获取风险事件"""
        if level:
            return [e for e in self.events if e.level == level]
        return self.events.copy()

    def clear_events(self):
        """清除事件记录"""
        self.events.clear()

    def reset_stop_trade(self):
        """重置停止交易标志"""
        self.stop_trade = False
```

### 7. 使用示例

#### 7.1 基础使用

```python
import backtrader as bt
from backtrader.store.binance import BinanceStore

# 创建Store
store = BinanceStore(
    api_key='your_api_key',
    api_secret='your_api_secret',
    coin_target='USDT',
    testnet=False
)

# 创建Cerebro
cerebro = bt.Cerebro()

# 添加数据
data = store.getdata(
    symbol='BTCUSDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    fromdate=datetime(2024, 1, 1),
    todate=datetime(2024, 12, 31),
    live=False
)
cerebro.adddata(data)

# 设置Broker
cerebro.setbroker(store.get_broker())

# 添加策略
cerebro.addstrategy(MyStrategy)

# 运行
result = cerebro.run()
```

#### 7.2 实时交易

```python
# 实时交易模式
store = BinanceStore(
    api_key='your_api_key',
    api_secret='your_api_secret',
    coin_target='USDT'
)

cerebro = bt.Cerebro()

# 实时数据
data = store.getdata(
    symbol='BTCUSDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    live=True
)
cerebro.adddata(data)

# 实时Broker
cerebro.setbroker(store.get_broker())

# 添加风险控制
cerebro.addstrategy(MyStrategyWithRiskControl)

# 运行
cerebro.run()
```

#### 7.3 带风险控制的策略

```python
class RiskControlledStrategy(bt.Strategy):
    params = (
        ('ema_fast', 5),
        ('ema_slow', 96),
    )

    def __init__(self):
        self.ema_fast = bt.indicators.EMA(self.data.close, period=self.params.ema_fast)
        self.ema_slow = bt.indicators.EMA(self.data.close, period=self.params.ema_slow)

        # 创建风险管理器
        self.risk_manager = RiskManager(self)

    def next(self):
        # 检查风险事件
        events = self.risk_manager.check_risk_events(self.data)
        for event in events:
            if event.level == 'critical':
                # 平仓停止交易
                self.close()
                return

        # 正常交易逻辑
        if self.ema_fast[0] > self.ema_slow[0]:
            if not self.position:
                # 检查是否可以开仓
                allowed, reason = self.risk_manager.check_entry(
                    self.data,
                    size=0.1,
                    price=self.data.close[0]
                )
                if allowed:
                    self.buy(size=0.1)
                else:
                    print(f"Entry blocked: {reason}")
        elif self.ema_fast[0] < self.ema_slow[0]:
            if self.position:
                self.close()
```

---

## 实施路线图

### 阶段1: Store基础架构 (3-4周)
- [ ] 创建store包结构
- [ ] 实现StoreBase基类
- [ ] 实现BrokerBase基类
- [ ] 实现FeedBase基类
- [ ] 实现重试装饰器
- [ ] 编写单元测试

### 阶段2: WebSocket管理 (2-3周)
- [ ] 实现WebSocketManager
- [ ] 实现消息队列和路由
- [ ] 实现心跳机制
- [ ] 实现自动重连
- [ ] 编写集成测试

### 阶段3: 加密货币特性 (2-3周)
- [ ] 实现CryptoCommInfo手续费计算
- [ ] 实现FundingRate资金费率
- [ ] 实现CryptoCalendar日历
- [ ] 实现合约交易支持
- [ ] 编写测试用例

### 阶段4: 数据缓存 (1-2周)
- [ ] 实现DataCache
- [ ] 实现增量更新逻辑
- [ ] 支持多种存储格式
- [ ] 性能优化

### 阶段5: 订单管理 (2周)
- [ ] 实现OrderManager
- [ ] 实现订单事件系统
- [ ] 集成WebSocket订单推送
- [ ] 测试各种订单状态

### 阶段6: 风险控制 (1-2周)
- [ ] 实现PinBarDetector
- [ ] 实现RiskManager
- [ ] 集成到Strategy基类
- [ ] 编写文档和示例

### 阶段7: 完整集成测试 (1-2周)
- [ ] 回测模式测试
- [ ] 实时交易测试
- [ ] 性能测试
- [ ] 文档完善

---

## 附录: 关键文件路径

### Backtrader关键文件
- `cerebro.py`: 核心引擎
- `broker.py`: 经纪商基类
- `strategy.py`: 策略基类
- `feed.py`: 数据源基类
- `linebuffer.py`: Line缓冲区实现
- `indicator.py`: 指标基类

### Backtrader_Binance关键文件
- `backtrader_binance/binance_store.py`: Store主类
- `backtrader_binance/binance_broker.py`: Broker实现
- `backtrader_binance/binance_feed.py`: Feed实现
- `backtrader_binance/binance_future_store.py`: 合约Store
- `Strategy/BaseStrategy.py`: 基础策略
- `KLineStrategy/`: K线形态策略库
