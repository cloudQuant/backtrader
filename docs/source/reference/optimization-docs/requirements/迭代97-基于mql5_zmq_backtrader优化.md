### 背景

backtrader 已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化 backtrader。

### 任务

1. 阅读研究分析 backtrader 这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/mql5_zmq_backtrader
3. 借鉴这个新项目的优点和功能，给 backtrader 优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### mql5_zmq_backtrader 项目简介

mql5_zmq_backtrader 是 MT5 与 backtrader 通过 ZMQ 连接的桥接项目，具有以下核心特点：

- **MT5 集成**: 与 MetaTrader 5 集成
- **ZMQ 通信**: 使用 ZeroMQ 通信
- **外汇交易**: 支持外汇市场
- **实时数据**: 实时行情传输
- **跨平台**: 跨平台通信
- **双向通信**: 双向数据和指令传输

### 重点借鉴方向

1. **ZMQ 通信**: ZeroMQ 通信模式
2. **MT5 集成**: MT5 平台集成
3. **桥接设计**: 跨平台桥接设计
4. **消息协议**: 消息协议设计
5. **外汇特性**: 外汇市场特性
6. **实时同步**: 数据实时同步

---
## 研究分析

### mql5_zmq_backtrader 架构特点总结

通过对 mql5_zmq_backtrader 项目的深入研究，总结出以下核心架构特点：

#### 1. 四端口分离的 ZMQ 通信架构

```bash
SYS_PORT (15555)    → REQ/REP 模式 → 系统命令（账户信息、订单操作）
DATA_PORT (15556)   → PUSH/PULL 模式 → 历史数据请求
LIVE_PORT (15557)   → PUSH/PULL 模式 → 实时数据流
EVENTS_PORT (15558) → PUSH/PULL 模式 → 事件通知

```

#### 2. Store-Broker-Data 三层架构

```bash
MTraderStore (单例)
    ├── MTraderBroker (订单执行、持仓管理)
    └── MT5Data (历史数据、实时数据流)

```

#### 3. 多线程并发处理

- `_t_livedata()`: 实时数据接收线程
- `_t_streaming_events()`: 事件流处理线程
- `_t_order_create()`: 订单创建处理线程
- `_t_order_cancel()`: 订单取消处理线程

#### 4. JSON 消息协议

统一的请求/响应格式：

```python
request = {
    "action": "get_data",      # 操作类型
    "actionType": "history",   # 操作子类型
    "symbol": "EURUSD",        # 交易品种
    "chartTF": "M1",           # 时间周期
    "fromDate": "2024-01-01",  # 开始日期
    "toDate": "2024-12-31"     # 结束日期

}

```

#### 5. 状态机驱动的数据流

```bash
_ST_FROM → _ST_START → _ST_LIVE → _ST_HISTORBACK → _ST_OVER

```

#### 6. 适配器模式

- `PositionAdapter`: 持仓数据适配
- `OrderAdapter`: 订单数据适配
- `BalanceAdapter`: 余额数据适配

### Backtrader 当前架构特点

#### 优势

- 成熟的数据源抽象层（60+指标）
- 灵活的佣金和经纪商系统
- 支持多种数据源（CSV、Pandas、CCXT、IB 等）
- 良好的中国市场支持（CTP、VC）
- 强大的性能分析器

#### 局限性（针对 ZMQ/MT5 集成）

1. **无 ZeroMQ 支持**: 无法实现高效的分布式架构
2. **无 MT5 原生集成**: 缺乏 MetaTrader 5 的直接接入
3. **单一 Store 模式**: 现有 Store（如 CCXTStore）功能相对简单
4. **实时数据延迟**: WebSocket/REST API 的延迟较高
5. **消息协议不统一**: 各数据源协议不一致

---
## 需求规格文档

### 1. ZeroMQ 通信模块

#### 1.1 功能描述

提供统一的 ZeroMQ 通信层，支持多种通信模式，实现高性能的消息传递。

#### 1.2 需求规格

| 需求 ID | 需求描述 | 优先级 |

|--------|----------|--------|

| ZMQ-001 | 定义 ZMQ 通信抽象基类 | P0 |

| ZMQ-002 | 支持 REQ/REP 通信模式 | P0 |

| ZMQ-003 | 支持 PUSH/PULL 通信模式 | P0 |

| ZMQ-004 | 支持 PUB/SUB 通信模式 | P1 |

| ZMQ-005 | 支持多端口分离架构 | P0 |

| ZMQ-006 | 支持 JSON 消息序列化 | P0 |

| ZMQ-007 | 支持消息重试机制（Lazy Pirate） | P1 |

| ZMQ-008 | 支持心跳检测和断线重连 | P1 |

| ZMQ-009 | 支持消息压缩 | P2 |

| ZMQ-010 | 支持 Protocol Buffers 序列化 | P2 |

#### 1.3 接口设计

```python
class ZMQConnection(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def connect(self, host: str, port: int):
        """建立连接"""
        pass

    @abc.abstractmethod
    def send(self, data: dict) -> dict:
        """发送消息并返回响应"""
        pass

    @abc.abstractmethod
    def close(self):
        """关闭连接"""
        pass

class ZMQClient(ZMQConnection):
    """ZMQ 客户端基类"""
    pass

class ZMQServer(ZMQConnection):
    """ZMQ 服务端基类"""
    pass

```

### 2. MT5 Store 模块

#### 2.1 功能描述

提供 MT5 平台的统一接入接口，管理账户、订单、持仓和数据。

#### 2.2 需求规格

| 需求 ID | 需求描述 | 优先级 |

|--------|----------|--------|

| MT5-001 | 定义 MT5Store 单例类 | P0 |

| MT5-002 | 支持账户信息查询 | P0 |

| MT5-003 | 支持持仓查询 | P0 |

| MT5-004 | 支持订单历史查询 | P0 |

| MT5-005 | 支持多时间周期数据 | P0 |

| MT5-006 | 支持 Tick 数据 | P1 |

| MT5-007 | 支持多账户管理 | P2 |

| MT5-008 | 支持 EA 集成 | P2 |

#### 2.3 接口设计

```python
class MT5Store:
    """MT5 存储和 API 管理类"""

# ZMQ 端口配置
    SYS_PORT = 15555    # 系统命令端口
    DATA_PORT = 15556   # 历史数据端口
    LIVE_PORT = 15557   # 实时数据端口
    EVENTS_PORT = 15558 # 事件端口

    def __init__(self, host: str = 'localhost', timeout: int = 5000):
        """初始化 MT5 连接

        Args:
            host: MT5 服务器地址
            timeout: 连接超时时间（毫秒）
        """

    def getaccount(self) -> dict:
        """获取账户信息"""
        pass

    def getpositions(self) -> list:
        """获取当前持仓"""
        pass

    def gethistory(self, symbol: str, timeframe: str,
                   from_date: datetime, to_date: datetime) -> list:
        """获取历史数据"""
        pass

```

### 3. MT5 Broker 模块

#### 3.1 功能描述

实现 MT5 订单执行和仓位管理，与 backtrader 的 BrokerBase 接口兼容。

#### 3.2 需求规格

| 需求 ID | 需求描述 | 优先级 |

|--------|----------|--------|

| BRK-001 | 实现 BrokerBase 接口 | P0 |

| BRK-002 | 支持市价单 | P0 |

| BRK-003 | 支持限价单 | P0 |

| BRK-004 | 支持止损单 | P0 |

| BRK-005 | 支持止盈单 | P0 |

| BRK-006 | 支持订单取消 | P0 |

| BRK-007 | 支持订单修改 | P1 |

| BRK-008 | 支持 OCO 订单 | P1 |

| BRK-009 | 支持外部订单同步 | P1 |

#### 3.3 接口设计

```python
class MT5Broker(broker.BrokerBase):
    """MT5 经纪商实现"""

    def __init__(self, store: MT5Store):
        """初始化 Broker

        Args:
            store: MT5Store 实例
        """

    def _submit(self, order: Order) -> None:
        """提交订单到 MT5"""
        pass

    def _cancel(self, order: Order) -> None:
        """取消订单"""
        pass

    def _fill(self, order: Order, size: float,
              price: float, reason: str) -> None:
        """订单成交处理"""
        pass

    def getposition(self, data) -> Position:
        """获取持仓信息"""
        pass

```

### 4. MT5 Data Feed 模块

#### 4.1 功能描述

提供 MT5 历史数据和实时数据的访问接口。

#### 4.2 需求规格

| 需求 ID | 需求描述 | 优先级 |

|--------|----------|--------|

| DATA-001 | 实现 DataBase 接口 | P0 |

| DATA-002 | 支持历史数据加载 | P0 |

| DATA-003 | 支持实时数据流 | P0 |

| DATA-004 | 支持多时间周期 | P0 |

| DATA-005 | 支持实时/回测模式切换 | P1 |

| DATA-006 | 支持断线重连和数据回填 | P1 |

| DATA-007 | 支持多品种订阅 | P1 |

#### 4.3 接口设计

```python
class MT5Data(feed.DataBase):
    """MT5 数据源实现"""

    def __init__(self, store: MT5Store, dataname: str,
                 timeframe: TimeFrame, compression: int = 1,
                 historical: bool = True):
        """初始化数据源

        Args:
            store: MT5Store 实例
            dataname: 交易品种名称
            timeframe: 时间周期
            compression: 周期压缩倍数
            historical: 是否加载历史数据
        """

    def start(self):
        """启动数据源"""
        pass

    def stop(self):
        """停止数据源"""
        pass

```

### 5. 时间周期映射模块

#### 5.1 功能描述

支持 MT5 与 backtrader 时间周期的双向映射。

#### 5.2 需求规格

| 需求 ID | 需求描述 | 优先级 |

|--------|----------|--------|

| TF-001 | 定义时间周期映射表 | P0 |

| TF-002 | 支持从 M1 到 MN1 的所有周期 | P0 |

| TF-003 | 支持双向转换 | P0 |

#### 5.3 设计

```python
_TIMEFRAME_MAP = {
    (TimeFrame.Minutes, 1): 'M1',
    (TimeFrame.Minutes, 5): 'M5',
    (TimeFrame.Minutes, 15): 'M15',
    (TimeFrame.Minutes, 30): 'M30',
    (TimeFrame.Minutes, 60): 'H1',
    (TimeFrame.Minutes, 240): 'H4',
    (TimeFrame.Days, 1): 'D1',
    (TimeFrame.Weeks, 1): 'W1',
    (TimeFrame.Months, 1): 'MN1',
}

```

### 6. 消息协议模块

#### 6.1 功能描述

定义统一的 JSON 消息格式，用于与 MT5 服务器通信。

#### 6.2 需求规格

| 需求 ID | 需求描述 | 优先级 |

|--------|----------|--------|

| MSG-001 | 定义标准消息格式 | P0 |

| MSG-002 | 支持请求/响应消息 | P0 |

| MSG-003 | 支持事件通知消息 | P0 |

| MSG-004 | 支持数据推送消息 | P0 |

| MSG-005 | 支持错误消息 | P0 |

#### 6.3 消息格式设计

```python

# 标准请求格式

REQUEST_MSG = {
    "action": str,           # 操作类型
    "actionType": str,       # 操作子类型
    "symbol": str,           # 交易品种
    "chartTF": str,          # 时间周期
    "fromDate": str,         # 开始日期（ISO 格式）
    "toDate": str,           # 结束日期（ISO 格式）
    "volume": float,         # 交易量
    "price": float,          # 价格
    "sl": float,             # 止损
    "tp": float,             # 止盈
    "deviation": int,        # 滑点容忍
    "magic": int,            # EA 魔法号
    "comment": str,          # 订单注释
    "ticket": int,           # 订单票据

}

# 标准响应格式

RESPONSE_MSG = {
    "error": bool,           # 是否有错误
    "errorCode": int,        # 错误代码
    "errorMessage": str,     # 错误信息
    "data": dict,            # 响应数据

}

```

### 7. 数据适配器模块

#### 7.1 功能描述

提供数据格式适配功能，将 MT5 数据转换为 backtrader 格式。

#### 7.2 需求规格

| 需求 ID | 需求描述 | 优先级 |

|--------|----------|--------|

| ADP-001 | 定义适配器基类 | P0 |

| ADP-002 | 实现持仓适配器 | P0 |

| ADP-003 | 实现订单适配器 | P0 |

| ADP-004 | 实现余额适配器 | P0 |

| ADP-005 | 支持时间戳转换 | P0 |

#### 7.3 接口设计

```python
class Adapter(metaclass=abc.ABCMeta):
    """数据适配器基类"""

    @abc.abstractmethod
    def adapt(self, raw_data: dict) -> dict:
        """适配数据格式"""
        pass

class PositionAdapter(Adapter):
    """持仓数据适配器"""
    pass

class OrderAdapter(Adapter):
    """订单数据适配器"""
    pass

```

---
## 设计文档

### 整体架构设计

#### 1. 目录结构

```bash
backtrader/
├── zmq/                     # ZeroMQ 通信模块

│   ├── __init__.py
│   ├── base.py              # ZMQ 抽象基类

│   ├── client.py            # ZMQ 客户端

│   ├── server.py            # ZMQ 服务端

│   ├── message.py           # 消息协议

│   └── retry.py             # 重试机制

│
├── mt5/                     # MT5 集成模块

│   ├── __init__.py
│   ├── store.py             # MT5Store 核心类

│   ├── broker.py            # MT5Broker 实现

│   ├── data.py              # MT5Data 实现

│   ├── adapter.py           # 数据适配器

│   ├── timeframe.py         # 时间周期映射

│   └── messages.py          # MT5 消息定义

│
└── utils/                   # 工具模块
    ├── __init__.py
    └── mt5_helpers.py       # MT5 辅助函数

```

### 详细设计

#### 1. ZMQ 基础模块设计

```python

# zmq/base.py

from abc import ABC, abstractmethod
import zmq
from typing import Dict, Any

class ZMQBase(ABC):
    """ZMQ 基础抽象类"""

    def __init__(self, timeout: int = 5000):
        self._context = zmq.Context()
        self._socket = None
        self._timeout = timeout
        self._connected = False

    @abstractmethod
    def connect(self, host: str, port: int):
        """建立连接"""
        pass

    @abstractmethod
    def send(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """发送消息"""
        pass

    def close(self):
        """关闭连接"""
        if self._socket:
            self._socket.close()
        self._context.term()
        self._connected = False

```

#### 2. ZMQ 客户端设计

```python

# zmq/client.py

class ZMQReqClient(ZMQBase):
    """ZMQ 请求-响应客户端"""

    def connect(self, host: str, port: int):
        """连接到 ZMQ REP 服务器"""
        self._socket = self._context.socket(zmq.REQ)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.connect(f"tcp://{host}:{port}")
        self._connected = True

    def send(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """发送请求并等待响应"""
        import json
        message = json.dumps(data).encode('utf-8')
        self._socket.send(message)
        response = self._socket.recv_json()
        return response

```

#### 3. MT5Store 核心设计

```python

# mt5/store.py

import threading
import queue
from backtrader.utils.py3 import OrderedDict

class MT5Store:
    """MT5 存储和 API 管理类（单例模式）"""

    _instances = OrderedDict()
    _lock = threading.Lock()

# ZMQ 端口配置
    SYS_PORT = 15555
    DATA_PORT = 15556
    LIVE_PORT = 15557
    EVENTS_PORT = 15558

    def __new__(cls, *args, **kwargs):
        """单例模式实现"""
        key = (cls, args, tuple(sorted(kwargs.items())))
        with cls._lock:
            if key not in cls._instances:
                cls._instances[key] = super().__new__(cls)
            return cls._instances[key]

    def __init__(self, host='localhost', timeout=5000):
        """初始化 MT5 连接

        Args:
            host: MT5 ZMQ 服务器地址
            timeout: 连接超时（毫秒）
        """
        if hasattr(self, '_initialized'):
            return

        self._host = host
        self._timeout = timeout
        self._queues = {
            'livedata': queue.Queue(),
            'events': queue.Queue(),
            'orders': queue.Queue(),
        }

# ZMQ 客户端
        self._sys_client = ZMQReqClient(timeout=timeout)
        self._data_client = ZMQPullClient(timeout=timeout)
        self._live_client = ZMQPullClient(timeout=timeout)
        self._events_client = ZMQPullClient(timeout=timeout)

# 线程管理
        self._threads = []
        self._running = False

        self._initialized = True

    def connect(self):
        """建立所有 ZMQ 连接"""
        self._sys_client.connect(self._host, self.SYS_PORT)
        self._data_client.connect(self._host, self.DATA_PORT)
        self._live_client.connect(self._host, self.LIVE_PORT)
        self._events_client.connect(self._host, self.EVENTS_PORT)
        self._running = True
        self._start_threads()

    def _start_threads(self):
        """启动数据处理线程"""

# 实时数据线程
        t = threading.Thread(target=self._t_livedata, daemon=True)
        t.start()
        self._threads.append(t)

# 事件流线程
        t = threading.Thread(target=self._t_streaming_events, daemon=True)
        t.start()
        self._threads.append(t)

    def _t_livedata(self):
        """实时数据接收线程"""
        while self._running:
            try:
                data = self._live_client.receive()
                self._queues['livedata'].put(data)
            except Exception:
                continue

    def _t_streaming_events(self):
        """事件流处理线程"""
        while self._running:
            try:
                event = self._events_client.receive()
                self._queues['events'].put(event)
            except Exception:
                continue

    def getbroker(self):
        """获取 Broker 实例"""
        from backtrader.mt5.broker import MT5Broker
        return MT5Broker(store=self)

    def getdata(self, **kwargs):
        """获取数据源实例"""
        from backtrader.mt5.data import MT5Data
        return MT5Data(store=self, **kwargs)

```

#### 4. MT5Broker 设计

```python

# mt5/broker.py

from backtrader import broker
from backtrader.utils.py3 import OrderedDict

class MT5Broker(broker.BrokerBase):
    """MT5 经纪商实现"""

    order_types = {
        broker.Order.Limit: 'ORDER_TYPE_LIMIT',
        broker.Order.Stop: 'ORDER_TYPE_STOP',
        broker.Order.StopLimit: 'ORDER_TYPE_STOP_LIMIT',
    }

    def __init__(self, store):
        """初始化 Broker

        Args:
            store: MT5Store 实例
        """
        super().__init__()

        self.store = store
        self._orders = OrderedDict()  # 订单追踪
        self._positions = OrderedDict()  # 持仓追踪

# 启动时同步 MT5 持仓
        self._sync_positions()

    def _sync_positions(self):
        """同步 MT5 现有持仓"""
        positions = self.store.getpositions()
        for pos in positions:
            self._positions[pos['symbol']] = pos

    def starting(self):
        """开始交易前准备"""
        super().starting()
        self.notifs = queue.Queue()

    def stopping(self):
        """停止交易"""
        super().stopping()

    def _submit(self, order):
        """提交订单到 MT5"""
        order_data = {
            'action': 'order',
            'actionType': 'create',
            'symbol': order.data._name,
            'volume': abs(order.created.size),
            'price': order.created.price,
            'type': self._get_order_type(order),
            'direction': 'buy' if order.isbuy() else 'sell',
        }

# 添加止损止盈
        if order.exectype == broker.Order.StopLimit:
            order_data['sl'] = order.created.pricelimit
            order_data['tp'] = order.created.price

        response = self.store._sys_client.send(order_data)

        if response.get('error'):
            self._reject(order)
        else:
            order.ticket = response.get('ticket')
            self._orders[order.ticket] = order

    def _cancel(self, order):
        """取消订单"""
        if not hasattr(order, 'ticket') or order.ticket is None:
            return

        cancel_data = {
            'action': 'order',
            'actionType': 'cancel',
            'ticket': order.ticket,
        }

        response = self.store._sys_client.send(cancel_data)

        if not response.get('error'):
            self._cancel_order(order)

    def _get_order_type(self, order):
        """获取 MT5 订单类型"""
        if order.exectype == broker.Order.Limit:
            return 'ORDER_TYPE_LIMIT'
        elif order.exectype == broker.Order.Stop:
            return 'ORDER_TYPE_STOP'
        elif order.exectype == broker.Order.StopLimit:
            return 'ORDER_TYPE_STOP_LIMIT'
        return 'ORDER_TYPE_MARKET'

    def getposition(self, data):
        """获取持仓信息"""
        symbol = data._name
        if symbol in self._positions:
            pos = self._positions[symbol]

# 创建 Position 对象
            position = broker.Position()
            position.update(size=pos['volume'], price=pos['price'])
            return position
        return broker.Position()

```

#### 5. MT5Data 设计

```python

# mt5/data.py

from backtrader import feed
from backtrader.utils.py3 import OrderedDict

class MT5Data(feed.DataBase):
    """MT5 数据源实现"""

# 数据状态
    _ST_FROM, _ST_START, _ST_LIVE, _ST_HISTORBACK, _ST_OVER = range(5)

# 时间周期映射
    _TIMEFRAMES = {
        (feed.TimeFrame.Minutes, 1): 'M1',
        (feed.TimeFrame.Minutes, 5): 'M5',
        (feed.TimeFrame.Minutes, 15): 'M15',
        (feed.TimeFrame.Minutes, 30): 'M30',
        (feed.TimeFrame.Minutes, 60): 'H1',
        (feed.TimeFrame.Minutes, 240): 'H4',
        (feed.TimeFrame.Days, 1): 'D1',
        (feed.TimeFrame.Weeks, 1): 'W1',
        (feed.TimeFrame.Months, 1): 'MN1',
    }

    params = (
        ('historical', True),      # 是否加载历史数据
        ('fromdate', None),        # 开始日期
        ('todate', None),          # 结束日期
        ('live', False),           # 实时模式
    )

    def __init__(self, store, **kwargs):
        """初始化数据源

        Args:
            store: MT5Store 实例
        """
        super().__init__()
        self.store = store
        self._state = self._ST_FROM
        self._hist_data = []
        self._live_queue = store._queues['livedata']

    def start(self):
        """启动数据源"""
        super().start()
        self._state = self._ST_START

        if self.p.historical:
            self._load_historical()

        if self.p.live:
            self._state = self._ST_LIVE
        else:
            self._state = self._ST_OVER

    def _load_historical(self):
        """加载历史数据"""
        tf = self._get_timeframe()
        from_date = self.p.fromdate or datetime(1970, 1, 1)
        to_date = self.p.todate or datetime.now()

        request = {
            'action': 'get_data',
            'actionType': 'history',
            'symbol': self.p.dataname,
            'chartTF': tf,
            'fromDate': from_date.isoformat(),
            'toDate': to_date.isoformat(),
        }

        response = self.store._sys_client.send(request)

        if not response.get('error'):
            self._hist_data = response.get('data', [])

    def _get_timeframe(self):
        """获取 MT5 时间周期字符串"""
        key = (self._timeframe, self._compression)
        return self._TIMEFRAMES.get(key, 'M1')

    def _load(self):
        """加载数据条"""
        if self._state == self._ST_LIVE:

# 实时数据模式
            try:
                bar = self._live_queue.get_nowait()
                return self._parse_bar(bar)
            except queue.Empty:
                return None
        elif self._hist_data:

# 历史数据模式
            return self._parse_bar(self._hist_data.pop(0))
        return None

    def _parse_bar(self, raw_bar):
        """解析 K 线数据"""
        self.lines.datetime[0] = date2num(raw_bar['time'])
        self.lines.open[0] = raw_bar['open']
        self.lines.high[0] = raw_bar['high']
        self.lines.low[0] = raw_bar['low']
        self.lines.close[0] = raw_bar['close']
        self.lines.volume[0] = raw_bar.get('volume', 0)
        return True

    def haslivedata(self):
        """是否有实时数据"""
        return self._state == self._ST_LIVE

    def islive(self):
        """是否为实时数据源"""
        return self.p.live

```

#### 6. 适配器设计

```python

# mt5/adapter.py

from abc import ABC, abstractmethod
from datetime import datetime

class Adapter(ABC):
    """数据适配器基类"""

    @abstractmethod
    def adapt(self, raw_data: dict) -> dict:
        """适配数据格式"""
        pass

class PositionAdapter(Adapter):
    """持仓数据适配器"""

    def adapt(self, raw_data: dict) -> dict:
        """将 MT5 持仓格式转换为 backtrader 格式"""
        return {
            'symbol': raw_data.get('symbol'),
            'volume': raw_data.get('volume'),
            'price': raw_data.get('price_open'),
            'current_price': raw_data.get('price_current'),
            'profit': raw_data.get('profit'),
            'type': 'buy' if raw_data.get('type') == 0 else 'sell',
            'ticket': raw_data.get('ticket'),
        }

class OrderAdapter(Adapter):
    """订单数据适配器"""

    def adapt(self, raw_data: dict) -> dict:
        """将 MT5 订单格式转换为 backtrader 格式"""
        return {
            'ticket': raw_data.get('ticket'),
            'symbol': raw_data.get('symbol'),
            'volume': raw_data.get('volume'),
            'price': raw_data.get('price'),
            'type': self._order_type(raw_data.get('type')),
            'state': self._order_state(raw_data.get('state')),
            'time': datetime.fromtimestamp(raw_data.get('time_setup', 0)),
        }

    @staticmethod
    def _order_type(mt5_type):
        """转换订单类型"""
        types = {
            0: 'buy',
            1: 'sell',
            2: 'buy_limit',
            3: 'sell_limit',
            4: 'buy_stop',
            5: 'sell_stop',
        }
        return types.get(mt5_type, 'unknown')

    @staticmethod
    def _order_state(mt5_state):
        """转换订单状态"""
        states = {
            0: 'started',
            1: 'placed',
            2: 'filled',
            3: 'canceled',
            4: 'rejected',
        }
        return states.get(mt5_state, 'unknown')

```

### 与现有 Backtrader 集成方案

#### 使用示例

```python
import backtrader as bt

# 1. 创建 MT5 Store

store = bt.store.MT5Store(host='192.168.1.100')

# 2. 获取 Broker

cerebro = bt.Cerebro()
cerebro.setbroker(store.getbroker())

# 3. 添加数据源

data = store.getdata(
    dataname='EURUSD',
    timeframe=bt.TimeFrame.Minutes,
    compression=15,
    historical=True,
    live=True
)
cerebro.adddata(data, name='EURUSD')

# 4. 添加策略并运行

cerebro.addstrategy(MyStrategy)
result = cerebro.run()

```

### 实施计划

#### 第一阶段 (P0 功能)

1. 实现 ZMQ 基础通信模块（REQ/REP, PUSH/PULL）
2. 实现 MT5Store 核心类
3. 实现 MT5Broker 基础功能（市价单、限价单、止损单）
4. 实现 MT5Data 基础功能（历史数据、实时数据）
5. 实现时间周期映射

#### 第二阶段 (P1 功能)

1. 实现消息重试机制（Lazy Pirate）
2. 实现心跳检测和断线重连
3. 支持订单取消和修改
4. 支持 OCO 订单
5. 支持外部订单同步
6. 实现数据适配器
7. 支持 Tick 数据

#### 第三阶段 (P2 功能)

1. 实现 PUB/SUB 通信模式
2. 支持消息压缩
3. 支持 Protocol Buffers 序列化
4. 支持多账户管理
5. 支持 EA 集成

---
## 总结

通过借鉴 mql5_zmq_backtrader 的设计理念，Backtrader 可以扩展以下能力：

1. **ZeroMQ 高性能通信**: 支持分布式架构和低延迟消息传递
2. **MT5 平台集成**: 直接接入 MetaTrader 5 生态系统
3. **四端口分离架构**: 系统命令、历史数据、实时数据、事件流独立处理
4. **多线程并发**: 实时数据和事件并行处理
5. **统一消息协议**: JSON 格式的标准化消息接口
6. **完整的外汇交易支持**: 订单类型、持仓管理、账户功能

这些增强功能将使 Backtrader 能够：

- 支持外汇和 CFD 市场交易
- 实现与 MT5 平台的无缝集成
- 提供更好的实时数据性能
- 支持分布式部署架构

该模块设计遵循 backtrader 现有的 Store-Broker-Data 三层架构模式，可以无缝集成到现有框架中。
