### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/alpaca-backtrader-api
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### alpaca-backtrader-api项目简介
alpaca-backtrader-api是Alpaca交易所与backtrader的集成项目，具有以下核心特点：
- **Alpaca集成**: 与Alpaca API无缝集成
- **实时数据**: 支持实时行情数据
- **实盘交易**: 支持实盘交易执行
- **WebSocket**: WebSocket数据流支持
- **Paper Trading**: 支持模拟交易
- **美股市场**: 专注于美股市场

### 重点借鉴方向
1. **API集成**: 交易所API集成模式
2. **实时数据**: 实时数据流处理
3. **WebSocket**: WebSocket连接管理
4. **Store设计**: Store模式设计
5. **Broker集成**: Broker接口实现
6. **数据源**: DataFeed实现

---

# 分析与设计文档

## 一、框架对比分析

### 1.1 backtrader vs alpaca-backtrader-api 对比

| 维度 | backtrader (原生) | alpaca-backtrader-api |
|------|------------------|----------------------|
| **定位** | 通用回测框架 | Alpaca实时交易适配器 |
| **数据源** | CSV、Pandas、Yahoo等静态数据 | WebSocket实时数据流 |
| **Broker** | 模拟经纪商 | Alpaca实盘/模拟经纪商 |
| **API集成** | 无原生交易所API | 深度集成Alpaca API |
| **实时性** | 回测为主 | 实时交易为主 |
| **状态管理** | 简单状态机 | 完整连接状态管理 |
| **线程模型** | 单线程 | 多线程+异步WebSocket |
| **重连机制** | 无 | 完善的WebSocket重连 |

### 1.2 可借鉴的核心优势

1. **Store模式**: 统一管理API连接、WebSocket、Broker和DataFeed
2. **状态机管理**: 清晰的数据流状态转换（历史→实时）
3. **线程安全设计**: Queue实现线程间通信
4. **环境切换**: 统一的实盘/模拟交易切换机制
5. **错误处理**: 完善的API异常处理和重试
6. **断线重连**: WebSocket自动重连机制

---

## 二、需求规格文档

### 2.1 统一Store模式设计

**需求描述**: 创建一个通用的Store基类，用于管理交易所API连接、WebSocket连接、Broker实例和DataFeed实例。

**功能要求**:
- Store作为单例模式，确保全局唯一连接
- 统一管理API认证信息
- 提供环境切换（实盘/模拟）
- 作为工厂创建Broker和DataFeed实例
- 管理WebSocket连接生命周期

**接口定义**:
```python
class StoreBase(with_metaclass(MetaSingleton, object)):
    """Store基类，用于管理交易所API连接"""

    params = (
        ('key_id', ''),
        ('secret_key', ''),
        ('base_url', None),
        ('paper', True),  # 默认模拟交易
        ('use_positions', True),
    )

    # 子类必须实现
    def getbroker(self): pass
    def getdata(self, **kwargs): pass
    def streaming_events(self, tmout=None): pass
```

### 2.2 增强WebSocket连接管理

**需求描述**: 实现一个健壮的WebSocket连接管理器，支持自动重连、心跳保活和消息队列缓冲。

**功能要求**:
- 自动重连机制（指数退避）
- 心跳保活（ping/pong）
- 消息队列缓冲（防止数据丢失）
- 连接状态回调
- 线程安全设计

**状态定义**:
```python
class ConnectionState(Enum):
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    RECONNECTING = 3
    SHUTTING_DOWN = 4
```

### 2.3 实时数据流处理

**需求描述**: 支持从WebSocket接收实时行情数据，并平滑切换到历史数据回填模式。

**功能要求**:
- 状态机管理数据流状态
- 历史数据回填
- 实时数据追加
- 断线时数据缓存
- 重连后数据同步

**数据流状态**:
```python
_ST_FROM = 0      # 初始状态
_ST_START = 1     # 开始获取历史数据
_ST_LIVE = 2      # 实时数据状态
_ST_HISTORBACK = 3  # 历史数据回填
_ST_OVER = 4      # 结束
```

### 2.4 通用Broker API适配器

**需求描述**: 创建一个通用Broker适配器基类，方便集成各种交易所API。

**功能要求**:
- 统一的订单类型映射
- 统一的状态转换
- 订单超时处理
- 多账户支持
- 持仓实时同步

**订单类型映射**:
```python
_ORDER_EXECTYPES = {
    Order.Market: 'market',
    Order.Limit: 'limit',
    Order.Stop: 'stop',
    Order.StopLimit: 'stop_limit',
}
```

### 2.5 线程安全的事件队列

**需求描述**: 实现线程安全的事件队列系统，用于多线程环境下的事件传递。

**功能要求**:
- 线程安全的Queue封装
- 事件优先级支持
- 超时机制
- 批量处理支持

### 2.6 API限流和错误处理

**需求描述**: 统一处理API限流、错误重试和异常捕获。

**功能要求**:
- 速率限制检测和处理
- 指数退避重试
- 错误分类和日志
- 降级策略

---

## 三、详细设计文档

### 3.1 Store模式实现

**设计思路**: 采用单例模式+工厂模式，Store作为中央管理器负责API连接和实例创建。

```python
# backtrader/store.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
from .. import metabase
from ..utils.py3 import queue, with_metaclass

class MetaSingleton(type):
    """单例元类"""
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(MetaSingleton, cls).__call__(
                *args, **kwargs)
        return cls._instances[cls]


class StoreBase(with_metaclass(MetaSingleton, metabase.AutoInfoClass)):
    """Store基类 - 管理交易所API连接"""

    params = (
        ('key_id', ''),
        ('secret_key', ''),
        ('base_url', None),
        ('paper', True),  # 模拟交易模式
        ('api_version', 'v2'),
        ('timeout', 30),
        ('retries', 3),
        ('use_positions', True),
    )

    # Broker和Data类通过元类注册
    BrokerCls = None
    DataCls = None

    def __init__(self):
        super(StoreBase, self).__init__()

        # 配置环境
        self._configure_environment()

        # API客户端（子类实现）
        self.oapi = None

        # 事件队列
        self.q_account = queue.Queue()
        self.q_ordercreate = queue.Queue()
        self.q_ordercancel = queue.Queue()

        # 线程管理
        self._threads = []
        self._running = False

    def _configure_environment(self):
        """配置API环境（实盘/模拟）"""
        if self.p.paper:
            self._oenv = 'paper'
            self.p.base_url = self.p.base_url or self._ENV_PAPER_URL
        else:
            self._oenv = 'live'
            self.p.base_url = self.p.base_url or self._ENV_LIVE_URL

    def getbroker(self, **kwargs):
        """获取Broker实例"""
        if self.BrokerCls is None:
            raise NotImplementedError('BrokerCls not defined')
        return self.BrokerCls(store=self, **kwargs)

    def getdata(self, **kwargs):
        """获取Data实例"""
        if self.DataCls is None:
            raise NotImplementedError('DataCls not defined')
        return self.DataCls(store=self, **kwargs)

    def start(self):
        """启动Store和后台线程"""
        if self._running:
            return

        self._running = True

        # 启动账户更新线程
        t = threading.Thread(target=self._t_account)
        t.daemon = True
        t.start()
        self._threads.append(t)

        # 启动订单创建线程
        t = threading.Thread(target=self._t_order_create)
        t.daemon = True
        t.start()
        self._threads.append(t)

        # 启动订单取消线程
        t = threading.Thread(target=self._t_order_cancel)
        t.daemon = True
        t.start()
        self._threads.append(t)

    def stop(self):
        """停止Store"""
        self._running = False

    def _t_account(self):
        """账户更新线程"""
        while self._running:
            try:
                self._update_account()
                time.sleep(self._ACCOUNT_UPDATE_INTERVAL)
            except Exception as e:
                logger.error(f'Account update error: {e}')

    def _t_order_create(self):
        """订单创建线程"""
        while self._running:
            try:
                order, kwargs = self.q_ordercreate.get(timeout=1)
                self._submit_order(order, **kwargs)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f'Order create error: {e}')

    def _t_order_cancel(self):
        """订单取消线程"""
        while self._running:
            try:
                order = self.q_ordercancel.get(timeout=1)
                self._cancel_order(order)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f'Order cancel error: {e}')

    def _update_account(self):
        """更新账户信息（子类实现）"""
        raise NotImplementedError()

    def _submit_order(self, order, **kwargs):
        """提交订单（子类实现）"""
        raise NotImplementedError()

    def _cancel_order(self, order):
        """取消订单（子类实现）"""
        raise NotImplementedError()

    def streaming_events(self, tmout=None):
        """获取实时事件流（子类实现）"""
        raise NotImplementedError()
```

### 3.2 WebSocket连接管理器

**设计思路**: 封装WebSocket连接，提供自动重连、心跳保活和消息队列功能。

```python
# backtrader/wsmanager.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import threading
import time
import logging
import queue
from enum import Enum
from collections import deque

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """连接状态"""
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    RECONNECTING = 3
    SHUTTING_DOWN = 4


class WebSocketManager:
    """WebSocket连接管理器

    特性：
    - 自动重连（指数退避）
    - 心跳保活
    - 消息队列缓冲
    - 连接状态回调
    """

    # 重连参数
    INITIAL_RECONNECT_DELAY = 1.0  # 初始重连延迟（秒）
    MAX_RECONNECT_DELAY = 60.0     # 最大重连延迟
    RECONNECT_DELAY_MULTIPLIER = 1.5  # 退避乘数

    # 心跳参数
    PING_INTERVAL = 30.0  # ping间隔（秒）
    PING_TIMEOUT = 10.0   # ping超时（秒）

    def __init__(self, url, on_message=None, on_connect=None,
                 on_disconnect=None, on_error=None):
        """
        参数:
            url: WebSocket URL
            on_message: 消息回调
            on_connect: 连接成功回调
            on_disconnect: 断开连接回调
            on_error: 错误回调
        """
        self.url = url
        self.on_message = on_message
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_error = on_error

        # 连接状态
        self._state = ConnectionState.DISCONNECTED
        self._state_lock = threading.Lock()
        self._ws = None

        # 重连控制
        self._reconnect_delay = self.INITIAL_RECONNECT_DELAY
        self._should_reconnect = True

        # 消息队列
        self._message_queue = queue.Queue(maxsize=10000)
        self._buffer = deque(maxlen=1000)  # 断线时的消息缓冲

        # 心跳
        self._last_ping_time = 0
        self._last_pong_time = 0

        # 线程
        self._receiver_thread = None
        self._heartbeat_thread = None
        self._running = False

    @property
    def state(self):
        """获取当前连接状态"""
        with self._state_lock:
            return self._state

    def connect(self):
        """建立WebSocket连接"""
        with self._state_lock:
            if self._state in (ConnectionState.CONNECTED,
                              ConnectionState.CONNECTING):
                return
            self._state = ConnectionState.CONNECTING

        self._running = True
        self._should_reconnect = True

        # 启动接收线程
        self._receiver_thread = threading.Thread(target=self._receive_loop)
        self._receiver_thread.daemon = True
        self._receiver_thread.start()

        # 启动心跳线程
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop)
        self._heartbeat_thread.daemon = True
        self._heartbeat_thread.start()

    def disconnect(self):
        """断开WebSocket连接"""
        self._should_reconnect = False
        self._running = False

        with self._state_lock:
            self._state = ConnectionState.SHUTTING_DOWN

        if self._ws:
            self._ws.close()

    def send(self, data):
        """发送数据"""
        if self.state != ConnectionState.CONNECTED:
            logger.warning(f'Cannot send, state: {self.state}')
            return False

        try:
            self._ws.send(data)
            return True
        except Exception as e:
            logger.error(f'Send error: {e}')
            self._on_connection_lost()
            return False

    def get_message(self, timeout=None):
        """获取消息（阻塞）"""
        try:
            return self._message_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _receive_loop(self):
        """接收循环"""
        import websocket

        while self._running and self._should_reconnect:
            if self.state == ConnectionState.CONNECTING:
                try:
                    # 尝试连接
                    self._ws = websocket.WebSocketApp(
                        self.url,
                        on_open=self._on_open,
                        on_message=self._on_message,
                        on_error=self._on_error,
                        on_close=self._on_close
                    )

                    # 运行WebSocket
                    self._ws.run_forever(ping_interval=self.PING_INTERVAL)

                except Exception as e:
                    logger.error(f'WebSocket error: {e}')
                    self._on_connection_lost()

            # 处理重连
            if self._should_reconnect:
                with self._state_lock:
                    self._state = ConnectionState.RECONNECTING

                time.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * self.RECONNECT_DELAY_MULTIPLIER,
                    self.MAX_RECONNECT_DELAY
                )
                with self._state_lock:
                    self._state = ConnectionState.CONNECTING

    def _heartbeat_loop(self):
        """心跳循环"""
        while self._running:
            time.sleep(self.PING_INTERVAL / 2)

            if self.state == ConnectionState.CONNECTED:
                # 检查pong超时
                if time.time() - self._last_pong_time > self.PING_TIMEOUT:
                    logger.warning('Pong timeout, reconnecting...')
                    self._on_connection_lost()

    def _on_open(self, ws):
        """连接打开回调"""
        logger.info(f'WebSocket connected: {self.url}')
        with self._state_lock:
            self._state = ConnectionState.CONNECTED
        self._reconnect_delay = self.INITIAL_RECONNECT_DELAY
        self._last_pong_time = time.time()

        # 发送缓冲的消息
        while self._buffer:
            msg = self._buffer.popleft()
            self.send(msg)

        if self.on_connect:
            self.on_connect()

    def _on_message(self, ws, message):
        """消息接收回调"""
        self._last_pong_time = time.time()

        try:
            # 放入队列（非阻塞，满时丢弃）
            self._message_queue.put_nowait(message)

            if self.on_message:
                self.on_message(message)
        except Exception as e:
            logger.error(f'Message handling error: {e}')

    def _on_error(self, ws, error):
        """错误回调"""
        logger.error(f'WebSocket error: {error}')
        if self.on_error:
            self.on_error(error)

    def _on_close(self, ws, *args):
        """连接关闭回调"""
        logger.info('WebSocket connection closed')

    def _on_connection_lost(self):
        """连接丢失处理"""
        with self._state_lock:
            if self._state != ConnectionState.RECONNECTING:
                self._state = ConnectionState.DISCONNECTED

        if self._ws:
            self._ws.close()
            self._ws = None

        if self.on_disconnect:
            self.on_disconnect()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
```

### 3.3 实时DataFeed状态机

**设计思路**: 使用状态机模式管理数据流从历史数据到实时数据的平滑切换。

```python
# backtrader/feeds/livedata.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import threading
import time
import queue
from .. import feed
from ..utils.py3 import Queue

# 数据流状态常量
_ST_FROM = 0          # 初始状态
_ST_START = 1         # 开始获取历史数据
_ST_LIVE = 2          # 实时数据状态
_ST_HISTORBACK = 3    # 历史数据回填
_ST_OVER = 4          # 结束

class LiveDataFeed(feed.DataBase):
    """实时数据Feed基类

    支持从历史数据平滑过渡到实时数据
    """

    params = (
        ('historical', True),      # 是否获取历史数据
        ('live', True),            # 是否订阅实时数据
        ('backfill_from', None),   # 回填数据源
        ('backfill_start', True),  # 是否启动时回填
        ('qcheck', 0.5),           # 队列检查间隔（秒）
        ('reconnect', True),       # 是否自动重连
        ('reconnect_max', 5),      # 最大重连次数
    )

    def __init__(self, **kwargs):
        super(LiveDataFeed, self).__init__(**kwargs)

        # 状态管理
        self._state = _ST_FROM
        self._state_lock = threading.Lock()

        # 数据队列
        self.qlive = Queue()
        self.qhist = Queue()

        # 重连计数
        self._reconnect_count = 0
        self._last_reconnect_time = 0

        # 数据缺失检测
        self._last_datetime = None
        self._gap_tolerance = 2  # 容忍的gap数量

        # 启动数据流
        self._start_data()

    def _start_data(self):
        """启动数据流"""
        if self.p.historical and self.p.backfill_start:
            self._start_historical()
        elif self.p.live:
            self._start_live()

    def _start_historical(self):
        """启动历史数据获取"""
        with self._state_lock:
            self._state = _ST_START

        # 在新线程中获取历史数据
        t = threading.Thread(target=self._fetch_historical)
        t.daemon = True
        t.start()

    def _start_live(self):
        """启动实时数据订阅"""
        with self._state_lock:
            self._state = _ST_LIVE

        # 请求Store启动实时数据流
        self.o.store.subscribe_data(self._dataname, self.qlive)

    def _load(self):
        """加载数据（backtrader调用）"""
        while True:
            # 检查重连
            if self._need_reconnect():
                self._do_reconnect()

            # 根据状态处理数据
            if self._state == _ST_LIVE:
                if not self._load_live():
                    continue
                return True

            elif self._state == _ST_HISTORBACK:
                if not self._load_historical():
                    continue
                # 历史数据完成后切换到实时
                self._transition_to_live()
                continue

            elif self._state == _ST_START:
                # 等待历史数据获取完成
                time.sleep(0.1)
                continue

            # 无数据可加载
            return False

    def _load_live(self):
        """加载实时数据"""
        try:
            msg = self.qlive.get(timeout=self.p.qcheck)
        except queue.Empty:
            return False

        # 解析消息
        dt, data = self._parse_message(msg)
        if dt is None:
            return False

        # 检查数据缺失
        if self._last_datetime and self._has_gap(dt):
            logger.warning(f'Data gap detected at {dt}')

        # 更新lines
        self.lines.datetime[0] = date2num(dt)
        self.lines.open[0] = data.get('open', data['close'])
        self.lines.high[0] = data.get('high', data['close'])
        self.lines.low[0] = data.get('low', data['close'])
        self.lines.close[0] = data['close']
        self.lines.volume[0] = data.get('volume', 0)

        self._last_datetime = dt
        return True

    def _load_historical(self):
        """加载历史数据"""
        try:
            msg = self.qhist.get(timeout=self.p.qcheck)
        except queue.Empty:
            return False

        dt, data = self._parse_message(msg)
        if dt is None:
            return False

        self.lines.datetime[0] = date2num(dt)
        self.lines.open[0] = data.get('open', data['close'])
        self.lines.high[0] = data.get('high', data['close'])
        self.lines.low[0] = data.get('low', data['close'])
        self.lines.close[0] = data['close']
        self.lines.volume[0] = data.get('volume', 0)

        self._last_datetime = dt
        return True

    def _transition_to_live(self):
        """切换到实时数据状态"""
        with self._state_lock:
            self._state = _ST_LIVE

        logger.info(f'Transitioned to live data: {self._dataname}')

        # 通知backtrader重新计算最小周期
        self._dataname = self._dataname

    def _fetch_historical(self):
        """获取历史数据（子类实现）"""
        raise NotImplementedError()

    def _parse_message(self, msg):
        """解析消息（子类实现）"""
        raise NotImplementedError()

    def _need_reconnect(self):
        """检查是否需要重连"""
        if not self.p.reconnect:
            return False

        # 超时检测
        if (time.time() - self._last_reconnect_time >
            self.p.qcheck * 10 and self._state == _ST_LIVE):
            return True

        return False

    def _do_reconnect(self):
        """执行重连"""
        if self._reconnect_count >= self.p.reconnect_max:
            logger.error('Max reconnect attempts reached')
            self._state = _ST_OVER
            return

        self._reconnect_count += 1
        self._last_reconnect_time = time.time()

        logger.info(f'Reconnecting {self._dataname} '
                   f'(attempt {self._reconnect_count})')

        # 重新订阅
        self.o.store.resubscribe_data(self._dataname, self.qlive)
```

### 3.4 通用Broker适配器

**设计思路**: 创建通用Broker适配器基类，统一处理订单类型转换和状态管理。

```python
# backtrader/brokers/api_broker.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import threading
import time
import logging
from collections import defaultdict
from .. import broker
from ..utils.py3 import queue

logger = logging.getLogger(__name__)


class APIBrokerBase(broker.BrokerBase):
    """API Broker基类

    提供通用的交易所API集成接口
    """

    params = (
        ('use_positions', True),      # 使用API持仓
        ('account_update_interval', 10),  # 账户更新间隔（秒）
        ('order_timeout', 60),        # 订单超时（秒）
        ('check_sync', True),         # 检查订单同步
    )

    # 订单类型映射（子类覆盖）
    _ORDER_EXECTYPES = {
        broker.Order.Market: 'market',
        broker.Order.Limit: 'limit',
        broker.Order.Stop: 'stop',
        broker.Order.StopLimit: 'stop_limit',
    }

    # 订单状态映射（子类覆盖）
    _ORDER_STATUS_MAP = {
        'new': broker.Order.Created,
        'submitted': broker.Order.Submitted,
        'accepted': broker.Order.Accepted,
        'partially_filled': broker.Order.Partial,
        'filled': broker.Order.Completed,
        'cancelled': broker.Order.Cancelled,
        'rejected': broker.Order.Rejected,
        'expired': broker.Order.Expired,
    }

    def __init__(self, **kwargs):
        super(APIBrokerBase, self).__init__()

        self.store = kwargs.pop('store', None)
        if self.store is None:
            raise ValueError('store parameter is required')

        # 订单跟踪
        self._orders = {}  # order_ref -> Order
        self._orders_by_broker_ref = {}  # broker_ref -> Order
        self._orders_lock = threading.Lock()

        # 持仓缓存
        self._positions = defaultdict(lambda: None)

        # 账户数据
        self._account_data = {}
        self._account_lock = threading.Lock()
        self._last_account_update = 0

        # 后台线程
        self._start_broker_threads()

    def _start_broker_threads(self):
        """启动后台线程"""
        # 账户更新线程
        t = threading.Thread(target=self._t_account_updater)
        t.daemon = True
        t.start()

        # 订单状态检查线程
        t = threading.Thread(target=self._t_order_checker)
        t.daemon = True
        t.start()

    def _t_account_updater(self):
        """账户更新线程"""
        while True:
            try:
                time.sleep(self.p.account_update_interval)
                self._update_account()
                self._update_positions()
            except Exception as e:
                logger.error(f'Account update error: {e}')

    def _t_order_checker(self):
        """订单状态检查线程"""
        while True:
            try:
                time.sleep(1)
                if self.p.check_sync:
                    self._check_pending_orders()
            except Exception as e:
                logger.error(f'Order check error: {e}')

    def _update_account(self):
        """更新账户信息"""
        try:
            account = self.store.oapi.get_account()

            with self._account_lock:
                self._account_data = {
                    'cash': float(account.get('cash', 0)),
                    'value': float(account.get('portfolio_value', 0)),
                    'margin': float(account.get('buying_power', 0)),
                }
                self._last_account_update = time.time()

        except Exception as e:
            logger.error(f'Failed to update account: {e}')

    def _update_positions(self):
        """更新持仓"""
        if not self.p.use_positions:
            return

        try:
            positions = self.store.oapi.list_positions()

            for pos in positions:
                symbol = pos.get('symbol', '')
                if not symbol:
                    continue

                # 查找对应的数据源
                data = self._get_data_by_symbol(symbol)
                if not data:
                    continue

                size = float(pos.get('qty', 0))
                price = float(pos.get('avg_entry_price', 0))

                with self._orders_lock:
                    self._positions[data] = (size, price)

        except Exception as e:
            logger.error(f'Failed to update positions: {e}')

    def _get_data_by_symbol(self, symbol):
        """根据symbol查找数据源"""
        for data in self.datas:
            if hasattr(data, '_name') and data._name == symbol:
                return data
        return None

    def _submit_order(self, order):
        """提交订单到交易所"""
        try:
            # 构建订单参数
            okwargs = self._build_order_params(order)

            # 调用API
            response = self.store.q_ordercreate.put((order, okwargs))

            return True

        except Exception as e:
            logger.error(f'Order submission failed: {e}')
            order.reject(e)
            return False

    def _build_order_params(self, order):
        """构建订单参数"""
        data = order.data
        params = {
            'symbol': data._name or getattr(data, '_dataname', ''),
            'qty': abs(int(order.created.size)),
            'side': 'buy' if order.isbuy() else 'sell',
            'type': self._ORDER_EXECTYPES.get(order.exectype, 'market'),
            'time_in_force': 'gtc',
        }

        # 限价单价格
        if order.exectype in (broker.Order.Limit, broker.Order.StopLimit):
            params['price'] = order.created.price

        # 止损单价格
        if order.exectype in (broker.Order.Stop, broker.Order.StopLimit):
            params['stop_price'] = order.created.pricelimit

        return params

    def _check_pending_orders(self):
        """检查待处理订单"""
        with self._orders_lock:
            pending = [o for o in self._orders.values()
                      if o.alive() and o.exectype != broker.Order.Market]

        for order in pending:
            # 检查超时
            if (time.time() - order.execdt.timestamp() >
                self.p.order_timeout):
                logger.warning(f'Order timeout: {order.ref}')
                self.cancel(order)

    def order_created(self, order):
        """订单创建回调"""
        super(APIBrokerBase, self).order_created(order)

        with self._orders_lock:
            self._orders[order.ref] = order

    def order_accepted(self, order):
        """订单接受回调"""
        super(APIBrokerBase, self).order_accepted(order)

    def order_rejected(self, order):
        """订单拒绝回调"""
        super(APIBrokerBase, self).order_rejected(order)

        with self._orders_lock:
            if order.ref in self._orders:
                del self._orders[order.ref]

    def order_completed(self, order):
        """订单完成回调"""
        super(APIBrokerBase, self).order_completed(order)

        with self._orders_lock:
            if order.ref in self._orders:
                del self._orders[order.ref]

    def cancel(self, order):
        """取消订单"""
        if not order.alive():
            return

        logger.info(f'Cancelling order: {order.ref}')
        self.store.q_ordercancel.put(order)

        super(APIBrokerBase, self).cancel(order)

    def getposition(self, data):
        """获取持仓"""
        if not self.p.use_positions:
            return super(APIBrokerBase, self).getposition(data)

        pos = self._positions.get(data)
        if pos:
            size, price = pos
            return broker.Position(size, price)
        return broker.Position(0, 0)

    def getcash(self):
        """获取现金"""
        with self._account_lock:
            return self._account_data.get('cash', 0)

    def getvalue(self):
        """获取账户价值"""
        with self._account_lock:
            return self._account_data.get('value', 0)
```

### 3.5 API限流和错误处理

**设计思路**: 统一处理API限流、错误重试和降级策略。

```python
# backtrader/utils/api_client.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import time
import logging
import functools
from collections import deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """速率限制器"""

    def __init__(self, max_requests, time_window):
        """
        参数:
            max_requests: 时间窗口内最大请求数
            time_window: 时间窗口（秒）
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.lock = threading.Lock()

    def acquire(self, block=True, timeout=None):
        """获取请求许可"""
        with self.lock:
            now = time.time()

            # 清理过期请求
            while self.requests and self.requests[0] < now - self.time_window:
                self.requests.popleft()

            # 检查是否超过限制
            if len(self.requests) >= self.max_requests:
                if not block:
                    return False

                # 计算等待时间
                wait_time = self.requests[0] + self.time_window - now
                if timeout is not None and wait_time > timeout:
                    return False

                time.sleep(wait_time)
                now = time.time()

                # 再次清理
                while self.requests and self.requests[0] < now - self.time_window:
                    self.requests.popleft()

            # 记录请求
            self.requests.append(now)
            return True


class RetryStrategy:
    """重试策略"""

    def __init__(self, max_retries=3, base_delay=1.0, max_delay=60.0,
                 exponential_base=2):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base

    def get_delay(self, attempt):
        """获取重试延迟（指数退避）"""
        delay = self.base_delay * (self.exponential_base ** attempt)
        return min(delay, self.max_delay)

    def should_retry(self, attempt, error):
        """判断是否应该重试"""
        if attempt >= self.max_retries:
            return False

        # 可重试的错误类型
        if isinstance(error, (TimeoutError, ConnectionError)):
            return True

        # API错误码
        if hasattr(error, 'code'):
            # 429 Too Many Requests
            # 500 Server Error
            # 502 Bad Gateway
            # 503 Service Unavailable
            if error.code in (429, 500, 502, 503):
                return True

        return False


def api_retry(max_retries=3, base_delay=1.0, max_delay=60.0):
    """API重试装饰器"""
    strategy = RetryStrategy(max_retries, base_delay, max_delay)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(strategy.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if not strategy.should_retry(attempt, e):
                        logger.error(f'API error (no retry): {e}')
                        raise

                    delay = strategy.get_delay(attempt)
                    logger.warning(f'API error, retrying in {delay}s: {e}')
                    time.sleep(delay)

            raise Exception('Max retries exceeded')

        return wrapper
    return decorator


class APIClient:
    """API客户端基类

    特性：
    - 速率限制
    - 自动重试
    - 错误处理
    - 请求/响应日志
    """

    def __init__(self, key_id, secret_key, base_url,
                 rate_limit=None, **kwargs):
        """
        参数:
            key_id: API密钥ID
            secret_key: API密钥
            base_url: API基础URL
            rate_limit: 速率限制 (max_requests, time_window)
        """
        self.key_id = key_id
        self.secret_key = secret_key
        self.base_url = base_url

        # 速率限制
        if rate_limit:
            self.rate_limiter = RateLimiter(*rate_limit)
        else:
            self.rate_limiter = None

        # 会话
        self._session = None

    def _get_session(self):
        """获取会话（懒加载）"""
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers.update(self._get_headers())
        return self._session

    def _get_headers(self):
        """获取请求头"""
        return {
            'Content-Type': 'application/json',
            'User-Agent': 'backtrader-api/1.0',
        }

    def request(self, method, path, data=None, params=None,
               retry=True, timeout=30):
        """发送API请求

        参数:
            method: HTTP方法
            path: API路径
            data: 请求体
            params: URL参数
            retry: 是否重试
            timeout: 超时时间

        返回:
            响应数据
        """
        # 速率限制
        if self.rate_limiter:
            if not self.rate_limiter.acquire(timeout=timeout):
                raise Exception('Rate limit timeout')

        url = self.base_url + path

        # 记录请求
        logger.debug(f'{method} {url}')

        # 装饰重试
        if retry:
            @api_retry(max_retries=3)
            def _do_request():
                session = self._get_session()
                response = session.request(
                    method=method,
                    url=url,
                    json=data,
                    params=params,
                    timeout=timeout
                )
                return self._handle_response(response)
            return _do_request()
        else:
            response = self._get_session().request(
                method=method,
                url=url,
                json=data,
                params=params,
                timeout=timeout
            )
            return self._handle_response(response)

    def _handle_response(self, response):
        """处理响应"""
        if response.status_code == 200:
            try:
                return response.json()
            except ValueError:
                return response.text
        elif response.status_code == 429:
            raise APIError('Rate limit exceeded',
                          code=429, response=response)
        elif 400 <= response.status_code < 500:
            raise APIError(f'Client error: {response.status_code}',
                          code=response.status_code, response=response)
        elif 500 <= response.status_code < 600:
            raise APIError(f'Server error: {response.status_code}',
                          code=response.status_code, response=response)
        else:
            raise APIError(f'Unexpected status: {response.status_code}',
                          code=response.status_code, response=response)

    def get(self, path, params=None, **kwargs):
        """GET请求"""
        return self.request('GET', path, params=params, **kwargs)

    def post(self, path, data=None, **kwargs):
        """POST请求"""
        return self.request('POST', path, data=data, **kwargs)

    def put(self, path, data=None, **kwargs):
        """PUT请求"""
        return self.request('PUT', path, data=data, **kwargs)

    def delete(self, path, **kwargs):
        """DELETE请求"""
        return self.request('DELETE', path, **kwargs)

    def close(self):
        """关闭会话"""
        if self._session:
            self._session.close()
            self._session = None


class APIError(Exception):
    """API错误"""

    def __init__(self, message, code=None, response=None):
        super(APIError, self).__init__(message)
        self.code = code
        self.response = response
        self._error_data = None

        if response:
            try:
                self._error_data = response.json()
            except ValueError:
                pass

    def error_response(self):
        """获取错误响应数据"""
        if self._error_data:
            return self._error_data
        return {
            'code': self.code,
            'message': str(self),
        }
```

### 3.6 事件驱动架构

**设计思路**: 实现一个事件驱动系统，用于处理各种交易事件（订单更新、账户更新、数据更新等）。

```python
# backtrader/events.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import enum
import threading
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class EventType(enum.Enum):
    """事件类型"""
    # 连接事件
    CONNECTED = 'connected'
    DISCONNECTED = 'disconnected'
    RECONNECTING = 'reconnecting'

    # 数据事件
    DATA_TICK = 'data_tick'
    DATA_BAR = 'data_bar'
    DATA_GAP = 'data_gap'

    # 订单事件
    ORDER_CREATED = 'order_created'
    ORDER_SUBMITTED = 'order_submitted'
    ORDER_ACCEPTED = 'order_accepted'
    ORDER_REJECTED = 'order_rejected'
    ORDER_PARTIAL = 'order_partial'
    ORDER_FILLED = 'order_filled'
    ORDER_CANCELLED = 'order_cancelled'
    ORDER_EXPIRED = 'order_expired'

    # 账户事件
    ACCOUNT_UPDATE = 'account_update'
    POSITION_UPDATE = 'position_update'
    MARGIN_UPDATE = 'margin_update'

    # 错误事件
    ERROR = 'error'
    WARNING = 'warning'


class Event:
    """事件对象"""

    __slots__ = ('type', 'data', 'timestamp', 'source')

    def __init__(self, event_type, data=None, source=None):
        self.type = event_type
        self.data = data
        self.timestamp = time.time()
        self.source = source

    def __repr__(self):
        return f'Event({self.type}, source={self.source})'


class EventHandler:
    """事件处理器基类"""

    def on_event(self, event):
        """处理事件"""
        method_name = f'on_{event.type.value}'
        method = getattr(self, method_name, None)
        if method and callable(method):
            try:
                method(event)
            except Exception as e:
                logger.error(f'Event handler error: {e}')

    def on_connected(self, event):
        """连接成功"""
        pass

    def on_disconnected(self, event):
        """连接断开"""
        pass

    def on_order_filled(self, event):
        """订单成交"""
        pass

    def on_error(self, event):
        """错误"""
        logger.error(f'Event error: {event.data}')


class EventBus:
    """事件总线

    特性：
    - 发布订阅模式
    - 线程安全
    - 异步事件分发
    """

    def __init__(self):
        # 订阅者: event_type -> [handlers]
        self._subscribers = defaultdict(list)
        self._lock = threading.RLock()

        # 事件队列
        self._event_queue = []
        self._processing = False

    def subscribe(self, event_type, handler):
        """订阅事件

        参数:
            event_type: 事件类型或类型列表
            handler: 事件处理器
        """
        with self._lock:
            if isinstance(event_type, (list, tuple)):
                for et in event_type:
                    self._subscribers[et].append(handler)
            else:
                self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type, handler):
        """取消订阅"""
        with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(handler)
                except ValueError:
                    pass

    def publish(self, event):
        """发布事件（同步）"""
        with self._lock:
            handlers = self._subscribers.get(event.type, [])

        for handler in handlers:
            try:
                handler.on_event(event)
            except Exception as e:
                logger.error(f'Event publish error: {e}')

    def publish_async(self, event):
        """发布事件（异步）"""
        with self._lock:
            self._event_queue.append(event)

        if not self._processing:
            self._process_queue()

    def _process_queue(self):
        """处理事件队列"""
        self._processing = True

        while self._event_queue:
            with self._lock:
                event = self._event_queue.pop(0)

            self.publish(event)

        self._processing = False

    def clear(self):
        """清除所有订阅"""
        with self._lock:
            self._subscribers.clear()


# 全局事件总线
default_event_bus = EventBus()
```

---

## 四、目录结构

基于以上设计，建议的新目录结构：

```
backtrader/
├── __init__.py
├── store.py                      # Store基类
├── wsmanager.py                  # WebSocket管理器
├── events.py                     # 事件系统
│
├── feeds/
│   ├── __init__.py
│   ├── livedata.py               # 实时数据Feed基类
│   └── ...
│
├── brokers/
│   ├── __init__.py
│   ├── api_broker.py             # API Broker基类
│   └── ...
│
├── utils/
│   ├── __init__.py
│   └── api_client.py             # API客户端工具
│
└── connectors/                   # 新增：各交易所连接器
    ├── __init__.py
    ├── alpaca/                   # Alpaca连接器
    │   ├── __init__.py
    │   ├── store.py
    │   ├── broker.py
    │   └── data.py
    └── binance/                  # Binance连接器
        ├── __init__.py
        ├── store.py
        ├── broker.py
        └── data.py
```

---

## 五、实施计划

### 第一阶段（高优先级）

1. **Store基类实现**
   - 实现`StoreBase`抽象类
   - 实现单例模式元类
   - 实现线程管理框架

2. **WebSocket管理器**
   - 实现`WebSocketManager`类
   - 实现自动重连机制
   - 实现心跳保活

3. **API客户端工具**
   - 实现`APIClient`类
   - 实现速率限制器
   - 实现重试装饰器

### 第二阶段（中优先级）

4. **实时DataFeed基类**
   - 实现`LiveDataFeed`状态机
   - 实现历史数据回填
   - 实现实时数据订阅

5. **API Broker基类**
   - 实现`APIBrokerBase`类
   - 实现订单类型映射
   - 实现持仓管理

6. **事件系统**
   - 实现`EventBus`类
   - 实现事件处理器
   - 集成到Broker和DataFeed

### 第三阶段（可选）

7. **示例连接器**
   - Alpaca连接器迁移
   - Binance连接器示例
   - 文档和示例代码

---

## 六、向后兼容性

所有新增功能均为**可选扩展**，不影响现有backtrader代码：

1. Store模式作为新功能引入，现有代码无需修改
2. WebSocket管理器独立使用，不强制依赖
3. API Broker基类作为可选实现
4. 实时DataFeed作为新的数据源类型

用户可按需选择使用新功能，保持原有代码完全兼容。
