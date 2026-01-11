### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/vnpy
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### vnpy项目简介
vnpy是一个基于Python的开源量化交易平台开发框架，它具有以下核心特点：
- **事件驱动架构**: 基于事件引擎的架构设计
- **多交易接口**: 支持国内外多种交易接口（CTP、IB、币安等）
- **实盘交易**: 专注于实盘交易，提供完整的交易解决方案
- **模块化设计**: 插件式的应用模块设计
- **数据管理**: 内置数据库管理和数据服务
- **风控系统**: 内置风险管理模块

### 重点借鉴方向
1. **事件引擎**: vnpy的事件驱动架构设计
2. **交易网关**: 统一的交易接口抽象层
3. **风控模块**: 完善的风险控制系统
4. **数据录制**: 行情数据录制和管理功能
5. **CTA引擎**: CTA策略回测和实盘引擎
6. **组合策略**: 多品种组合策略支持

---

## 一、项目对比分析

### 1.1 vn.py 项目核心特性

| 特性 | 描述 |
|------|------|
| **EventEngine** | 独立的事件驱动引擎，支持事件类型分发和通用处理器 |
| **MainEngine** | 交易平台核心，管理网关、引擎和应用 |
| **BaseGateway** | 统一的交易接口抽象层，支持多交易系统 |
| **BaseDatabase** | 数据库抽象层，支持多种数据库后端 |
| **dataclass 对象** | 使用 dataclass 定义数据对象 |
| **事件类型常量** | 清晰的事件类型命名约定 |
| **OMSEngine** | 订单管理系统引擎 |
| **LogEngine** | 日志引擎 |
| **EmailEngine** | 邮件通知引擎 |
| **模块化设计** | 插件式的功能扩展 |

### 1.2 backtrader 现有能力对比

| 能力 | backtrader | vn.py | 差距 |
|------|-----------|-------|------|
| **事件驱动** | Cerebro 内置引擎 | 独立 EventEngine | vn.py 更灵活 |
| **交易接口** | Broker 抽象 | Gateway 抽象 | 两者类似 |
| **数据管理** | DataFeed | Database + DataFeed | vn.py 支持数据库 |
| **对象定义** | Line 类 | dataclass | vn.py 更现代 |
| **多接口** | 单一 Broker | 多 Gateway | vn.py 支持多系统 |
| **日志系统** | 基础日志 | LogEngine | vn.py 更完善 |
| **通知系统** | 无 | EmailEngine | backtrader 缺少 |

### 1.3 差距分析

| 方面 | vn.py | backtrader | 差距 |
|------|-------|-----------|------|
| **事件架构** | 独立 EventEngine | Cerebro 集成 | backtrader 可提取独立事件引擎 |
| **数据对象** | dataclass @dataclass | Line 类 | backtrader 可使用 dataclass |
| **数据库** | BaseDatabase 抽象 | 无内置支持 | backtrader 缺少数据库抽象 |
| **多系统** | 支持多交易系统 | 单一系统 | backtrader 可扩展 |
| **通知** | EmailEngine | 无 | backtrader 可添加通知 |

---

## 二、需求规格文档

### 2.1 功能需求

#### FR1: 独立事件引擎
创建可复用的事件驱动引擎：

- **FR1.1**: Event 类 - 事件对象封装
- **FR1.2**: EventEngine 类 - 事件处理引擎
- **FR1.3**: 事件类型注册/注销
- **FR1.4**: 通用事件处理器
- **FR1.5**: 定时器事件

#### FR2: 数据对象现代化
使用 dataclass 定义数据对象：

- **FR2.1**: BaseData 基类
- **FR2.2**: TickData - Tick 数据对象
- **FR2.3**: BarData - K线数据对象
- **FR2.4**: OrderData - 订单数据对象
- **FR2.5**: TradeData - 成交数据对象
- **FR2.6**: PositionData - 持仓数据对象

#### FR3: 数据库抽象层
统一的数据库访问接口：

- **FR3.1**: BaseDatabase 抽象基类
- **FR3.2**: save_bar_data() - 保存K线数据
- **FR3.3**: load_bar_data() - 加载K线数据
- **FR3.4**: delete_bar_data() - 删除数据
- **FR3.5**: get_bar_overview() - 数据概览

#### FR4: 通知系统
事件通知功能：

- **FR4.1**: 邮件通知
- **FR4.2**: 交易完成通知
- **FR4.3**: 异常告警通知
- **FR4.4**: 自定义通知模板

### 2.2 非功能需求

- **NFR1**: 性能 - 事件引擎不能成为性能瓶颈
- **NFR2**: 兼容性 - 与现有 backtrader API 兼容
- **NFR3**: 可扩展性 - 易于添加新的事件类型和处理器
- **NFR4**: 线程安全 - 事件引擎需要线程安全

### 2.3 用户故事

| ID | 故事描述 | 优先级 |
|----|---------|--------|
| US1 | 作为实盘交易者，我想收到交易完成邮件，及时了解交易状态 | P0 |
| US2 | 作为策略开发者，我想使用现代的 dataclass 定义数据对象 | P1 |
| US3 | 作为数据分析师，我想将回测数据保存到数据库，便于分析 | P1 |
| US4 | 作为系统管理员，我想通过事件系统监控平台运行状态 | P1 |

---

## 三、设计文档

### 3.1 模块结构设计

```
backtrader/
├── event/                     # 新增事件模块
│   ├── __init__.py
│   ├── engine.py              # 事件引擎
│   └── event.py               # 事件类
├── database/                  # 新增数据库模块
│   ├── __init__.py
│   ├── base.py                # 数据库基类
│   └── sqlite.py              # SQLite 实现
├── notify/                    # 新增通知模块
│   ├── __init__.py
│   ├── email.py               # 邮件通知
│   └── template.py            # 通知模板
└── objects/                   # 新增数据对象模块
    ├── __init__.py
    ├── tick.py                # Tick 数据
    ├── bar.py                 # K线数据
    ├── order.py               # 订单数据
    ├── trade.py               # 成交数据
    └── position.py            # 持仓数据
```

### 3.2 核心类设计

#### 3.2.1 事件引擎

```python
"""
事件驱动引擎

参考：vnpy/event/engine.py
"""
from collections import defaultdict
from queue import Empty, Queue
from threading import Thread
from time import sleep
from typing import Any, Callable


EVENT_TIMER = "eTimer"


class Event:
    """事件对象"""

    def __init__(self, type: str, data: Any = None):
        """
        Args:
            type: 事件类型
            data: 事件数据
        """
        self.type: str = type
        self.data: Any = data


# 事件处理器类型
HandlerType = Callable[[Event], None]


class EventEngine:
    """事件引擎

    负责事件的分发和处理，支持：
    - 按类型分发事件
    - 通用事件处理
    - 定时器事件
    """

    def __init__(self, interval: int = 1):
        """
        Args:
            interval: 定时器事件间隔（秒）
        """
        self._interval: int = interval
        self._queue: Queue = Queue()
        self._active: bool = False
        self._thread: Thread = Thread(target=self._run)
        self._timer: Thread = Thread(target=self._run_timer)
        self._handlers: defaultdict = defaultdict(list)
        self._general_handlers: list = []

    def _run(self) -> None:
        """事件处理主循环"""
        while self._active:
            try:
                event: Event = self._queue.get(block=True, timeout=1)
                self._process(event)
            except Empty:
                pass

    def _process(self, event: Event) -> None:
        """处理事件

        先分发到特定类型的处理器，再分发到通用处理器
        """
        if event.type in self._handlers:
            [handler(event) for handler in self._handlers[event.type]]

        if self._general_handlers:
            [handler(event) for handler in self._general_handlers]

    def _run_timer(self) -> None:
        """定时器线程"""
        while self._active:
            sleep(self._interval)
            event: Event = Event(EVENT_TIMER)
            self.put(event)

    def start(self) -> None:
        """启动事件引擎"""
        self._active = True
        self._thread.start()
        self._timer.start()

    def stop(self) -> None:
        """停止事件引擎"""
        self._active = False
        self._timer.join()
        self._thread.join()

    def put(self, event: Event) -> None:
        """将事件放入队列"""
        self._queue.put(event)

    def register(self, type: str, handler: HandlerType) -> None:
        """注册特定类型的处理器"""
        handler_list: list = self._handlers[type]
        if handler not in handler_list:
            handler_list.append(handler)

    def unregister(self, type: str, handler: HandlerType) -> None:
        """注销处理器"""
        handler_list: list = self._handlers[type]

        if handler in handler_list:
            handler_list.remove(handler)

        if not handler_list:
            self._handlers.pop(type)

    def register_general(self, handler: HandlerType) -> None:
        """注册通用处理器（接收所有事件）"""
        if handler not in self._general_handlers:
            self._general_handlers.append(handler)

    def unregister_general(self, handler: HandlerType) -> None:
        """注销通用处理器"""
        if handler in self._general_handlers:
            self._general_handlers.remove(handler)
```

#### 3.2.2 数据对象（使用 dataclass）

```python
"""
数据对象定义

参考：vnpy/trader/object.py
"""
from dataclasses import dataclass, field
from datetime import datetime as Datetime
from enum import Enum


class Direction(Enum):
    """方向"""
    LONG = "多"
    SHORT = "空"


class Exchange(Enum):
    """交易所"""
    SSE = "上交所"
    SZSE = "深交所"
    SHFE = "上期所"
    DCE = "大商所"
    CZCE = "郑商所"
    CFFEX = "中金所"


class Status(Enum):
    """订单状态"""
    SUBMITTING = "提交中"
    NOTTRADED = "未成交"
    PARTTRADED = "部分成交"
    ALLTRADED = "全部成交"
    CANCELLED = "已撤销"
    REJECTED = "已拒绝"


@dataclass
class BaseData:
    """数据基类"""
    gateway_name: str
    extra: dict | None = field(default=None, init=False)


@dataclass
class TickData(BaseData):
    """Tick 数据"""
    symbol: str
    exchange: Exchange
    datetime: Datetime

    name: str = ""
    volume: float = 0
    turnover: float = 0
    open_interest: float = 0
    last_price: float = 0
    last_volume: float = 0
    limit_up: float = 0
    limit_down: float = 0

    open_price: float = 0
    high_price: float = 0
    low_price: float = 0
    pre_close: float = 0

    bid_price_1: float = 0
    bid_price_2: float = 0
    bid_price_3: float = 0
    bid_price_4: float = 0
    bid_price_5: float = 0

    ask_price_1: float = 0
    ask_price_2: float = 0
    ask_price_3: float = 0
    ask_price_4: float = 0
    ask_price_5: float = 0

    bid_volume_1: float = 0
    bid_volume_2: float = 0
    bid_volume_3: float = 0
    bid_volume_4: float = 0
    bid_volume_5: float = 0

    ask_volume_1: float = 0
    ask_volume_2: float = 0
    ask_volume_3: float = 0
    ask_volume_4: float = 0
    ask_volume_5: float = 0

    def __post_init__(self):
        self.vt_symbol: str = f"{self.symbol}.{self.exchange.value}"


@dataclass
class BarData(BaseData):
    """K线数据"""
    symbol: str
    exchange: Exchange
    datetime: Datetime

    interval: str | None = None
    volume: float = 0
    turnover: float = 0
    open_interest: float = 0
    open_price: float = 0
    high_price: float = 0
    low_price: float = 0
    close_price: float = 0

    def __post_init__(self):
        self.vt_symbol: str = f"{self.symbol}.{self.exchange.value}"


@dataclass
class OrderData(BaseData):
    """订单数据"""
    symbol: str
    exchange: Exchange
    orderid: str

    direction: Direction | None = None
    price: float = 0
    volume: float = 0
    traded: float = 0
    status: Status = Status.SUBMITTING
    datetime: Datetime | None = None
    reference: str = ""

    def __post_init__(self):
        self.vt_symbol: str = f"{self.symbol}.{self.exchange.value}"
        self.vt_orderid: str = f"{self.gateway_name}.{self.orderid}"

    def is_active(self) -> bool:
        """检查订单是否活跃"""
        return self.status in [Status.SUBMITTING, Status.NOTTRADED, Status.PARTTRADED]


@dataclass
class TradeData(BaseData):
    """成交数据"""
    symbol: str
    exchange: Exchange
    orderid: str
    tradeid: str
    direction: Direction | None = None

    price: float = 0
    volume: float = 0
    datetime: Datetime | None = None

    def __post_init__(self):
        self.vt_symbol: str = f"{self.symbol}.{self.exchange.value}"
        self.vt_orderid: str = f"{self.gateway_name}.{self.orderid}"
        self.vt_tradeid: str = f"{self.gateway_name}.{self.tradeid}"


@dataclass
class PositionData(BaseData):
    """持仓数据"""
    symbol: str
    exchange: Exchange
    direction: Direction

    volume: float = 0
    frozen: float = 0
    price: float = 0
    pnl: float = 0
    yd_volume: float = 0

    def __post_init__(self):
        self.vt_symbol: str = f"{self.symbol}.{self.exchange.value}"
        self.vt_positionid: str = f"{self.gateway_name}.{self.vt_symbol}.{self.direction.value}"


@dataclass
class AccountData(BaseData):
    """账户数据"""
    accountid: str

    balance: float = 0
    frozen: float = 0
    available: float = 0

    def __post_init__(self):
        self.vt_accountid: str = f"{self.gateway_name}.{self.accountid}"
```

#### 3.2.3 数据库抽象层

```python
"""
数据库抽象层

参考：vnpy/trader/database.py
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from .objects import BarData, TickData
from .constant import Interval, Exchange


@dataclass
class BarOverview:
    """K线数据概览"""
    symbol: str = ""
    exchange: Exchange | None = None
    interval: Interval | None = None
    count: int = 0
    start: datetime | None = None
    end: datetime | None = None


@dataclass
class TickOverview:
    """Tick 数据概览"""
    symbol: str = ""
    exchange: Exchange | None = None
    count: int = 0
    start: datetime | None = None
    end: datetime | None = None


class BaseDatabase(ABC):
    """数据库抽象基类"""

    @abstractmethod
    def save_bar_data(self, bars: list[BarData], stream: bool = False) -> bool:
        """保存K线数据"""
        pass

    @abstractmethod
    def save_tick_data(self, ticks: list[TickData], stream: bool = False) -> bool:
        """保存Tick数据"""
        pass

    @abstractmethod
    def load_bar_data(
        self,
        symbol: str,
        exchange: Exchange,
        interval: Interval,
        start: datetime,
        end: datetime
    ) -> list[BarData]:
        """加载K线数据"""
        pass

    @abstractmethod
    def load_tick_data(
        self,
        symbol: str,
        exchange: Exchange,
        start: datetime,
        end: datetime
    ) -> list[TickData]:
        """加载Tick数据"""
        pass

    @abstractmethod
    def delete_bar_data(
        self,
        symbol: str,
        exchange: Exchange,
        interval: Interval
    ) -> int:
        """删除K线数据"""
        pass

    @abstractmethod
    def delete_tick_data(
        self,
        symbol: str,
        exchange: Exchange
    ) -> int:
        """删除Tick数据"""
        pass

    @abstractmethod
    def get_bar_overview(self) -> list[BarOverview]:
        """获取K线数据概览"""
        pass

    @abstractmethod
    def get_tick_overview(self) -> list[TickOverview]:
        """获取Tick数据概览"""
        pass


class SQLiteDatabase(BaseDatabase):
    """SQLite 数据库实现"""

    def __init__(self, db_path: str = "backtrader.db"):
        import sqlite3
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        """初始化数据表"""
        cursor = self.conn.cursor()

        # K线数据表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bar_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            exchange TEXT NOT NULL,
            interval TEXT NOT NULL,
            datetime TEXT NOT NULL,
            open_price REAL,
            high_price REAL,
            low_price REAL,
            close_price REAL,
            volume REAL,
            turnover REAL,
            open_interest REAL,
            UNIQUE(symbol, exchange, interval, datetime)
        )
        """)

        # Tick 数据表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tick_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            exchange TEXT NOT NULL,
            datetime TEXT NOT NULL,
            last_price REAL,
            volume REAL,
            UNIQUE(symbol, exchange, datetime)
        )
        """)

        self.conn.commit()

    def save_bar_data(self, bars: list[BarData], stream: bool = False) -> bool:
        """保存K线数据"""
        cursor = self.conn.cursor()
        for bar in bars:
            try:
                cursor.execute("""
                INSERT OR REPLACE INTO bar_data
                (symbol, exchange, interval, datetime, open_price, high_price, low_price, close_price, volume, turnover, open_interest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    bar.symbol,
                    bar.exchange.value,
                    bar.interval,
                    bar.datetime.isoformat(),
                    bar.open_price,
                    bar.high_price,
                    bar.low_price,
                    bar.close_price,
                    bar.volume,
                    bar.turnover,
                    bar.open_interest
                ))
            except Exception as e:
                print(f"保存失败: {e}")
                return False

        self.conn.commit()
        return True

    def load_bar_data(
        self,
        symbol: str,
        exchange: Exchange,
        interval: Interval,
        start: datetime,
        end: datetime
    ) -> list[BarData]:
        """加载K线数据"""
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT symbol, exchange, interval, datetime, open_price, high_price, low_price, close_price, volume, turnover, open_interest
        FROM bar_data
        WHERE symbol = ? AND exchange = ? AND interval = ? AND datetime >= ? AND datetime <= ?
        ORDER BY datetime
        """, (symbol, exchange.value, interval.value, start.isoformat(), end.isoformat()))

        from .objects import BarData
        bars = []
        for row in cursor.fetchall():
            bar = BarData(
                symbol=row[0],
                exchange=Exchange(row[1]),
                interval=row[2],
                datetime=datetime.fromisoformat(row[3]),
                open_price=row[4],
                high_price=row[5],
                low_price=row[6],
                close_price=row[7],
                volume=row[8],
                turnover=row[9],
                open_interest=row[10],
                gateway_name="database"
            )
            bars.append(bar)
        return bars

    # ... 其他方法实现
```

#### 3.2.4 邮件通知引擎

```python
"""
邮件通知引擎

参考：vnpy/trader/engine.py 中的 EmailEngine
"""
import smtplib
from email.message import EmailMessage
from typing import Optional


class EmailEngine:
    """邮件通知引擎"""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_username: str,
        smtp_password: str,
        sender: str
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.sender = sender

    def send_email(
        self,
        subject: str,
        content: str,
        receiver: str | None = None
    ) -> None:
        """发送邮件

        Args:
            subject: 邮件主题
            content: 邮件内容
            receiver: 收件人（如果为 None，使用默认收件人）
        """
        if not receiver:
            return

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = receiver
        message.set_content(content)

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(message)
        except Exception as e:
            print(f"发送邮件失败: {e}")
```

### 3.3 事件类型定义

```python
"""
事件类型常量

参考：vnpy/trader/event.py
"""
from backtrader.event import EVENT_TIMER

# 定义事件类型
EVENT_TICK = "eTick."
EVENT_TRADE = "eTrade."
EVENT_ORDER = "eOrder."
EVENT_POSITION = "ePosition."
EVENT_ACCOUNT = "eAccount."
EVENT_CONTRACT = "eContract."
EVENT_LOG = "eLog"
EVENT_STRATEGY = "eStrategy."
EVENT_BACKTEST = "eBacktest."
```

### 3.4 Cerebro 与事件引擎集成

```python
# 在 Cerebro 中集成事件引擎

class Cerebro:
    # ... 现有代码 ...

    def __init__(self):
        # ... 现有代码 ...
        from backtrader.event import EventEngine
        self._event_engine = EventEngine()
        self._event_engine.start()

        # 注册默认事件处理器
        self._register_event_handlers()

    def _register_event_handlers(self):
        """注册默认事件处理器"""
        from backtrader.trader.event import (
            EVENT_TICK, EVENT_TRADE, EVENT_ORDER, EVENT_LOG
        )

        self._event_engine.register(EVENT_LOG, self._on_log_event)
        self._event_engine.register(EVENT_TRADE, self._on_trade_event)
        self._event_engine.register(EVENT_ORDER, self._on_order_event)

    def _on_log_event(self, event):
        """处理日志事件"""
        log_data = event.data
        print(f"[LOG] {log_data.msg}")

    def _on_trade_event(self, event):
        """处理成交事件"""
        trade_data = event.data
        # 处理成交事件...

    def _on_order_event(self, event):
        """处理订单事件"""
        order_data = event.data
        # 处理订单事件...

    def get_event_engine(self):
        """获取事件引擎"""
        return self._event_engine

    def stop(self):
        """停止回测"""
        # ... 现有代码 ...
        self._event_engine.stop()
```

### 3.5 API 设计

```python
import backtrader as bt
from backtrader.event import Event, EventEngine
from backtrader.database import SQLiteDatabase
from backtrader.objects import BarData
from backtrader.notify import EmailEngine

# 1. 使用事件引擎
event_engine = EventEngine()

def on_timer_event(event):
    print(f"定时器事件触发: {event.data}")

event_engine.register(EVENT_TIMER, on_timer_event)
event_engine.start()

# 2. 使用数据库
db = SQLiteDatabase("my_data.db")

# 保存数据
bars = [
    BarData(
        symbol="AAPL",
        exchange=Exchange.SSE,
        datetime=datetime.now(),
        open_price=100.0,
        high_price=105.0,
        low_price=99.0,
        close_price=104.0,
        volume=1000000,
        gateway_name="test"
    )
]
db.save_bar_data(bars)

# 加载数据
loaded_bars = db.load_bar_data(
    symbol="AAPL",
    exchange=Exchange.SSE,
    interval=Interval.DAILY,
    start=datetime(2020, 1, 1),
    end=datetime(2024, 12, 31)
)

# 3. 使用邮件通知
email_engine = EmailEngine(
    smtp_host="smtp.gmail.com",
    smtp_port=587,
    smtp_username="your_email@gmail.com",
    smtp_password="your_password",
    sender="your_email@gmail.com"
)

email_engine.send_email(
    subject="交易完成",
    content="策略已完成回测，收益率：15%",
    receiver="recipient@example.com"
)

# 4. Cerebro 集成
cerebro = bt.Cerebro()

# 获取事件引擎
event_engine = cerebro.get_event_engine()

# 注册自定义事件处理器
def my_trade_handler(event):
    print(f"交易事件: {event.data}")

event_engine.register(EVENT_TRADE, my_trade_handler)
```

### 3.6 组件化架构

```
┌────────────────────────────────────────────────────────────┐
│                    Backtrader Enhanced Components            │
├────────────────────────────────────────────────────────────┤
│  Event Engine                                              │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  EventEngine                                        │ │
│  │  - Event(type, data)                               │ │
│  │  - register(type, handler)                         │ │
│  │  - register_general(handler)                       │ │
│  │  - put(event) / start() / stop()                   │ │
│  │  - 定时器事件 (EVENT_TIMER)                        │ │
│  └──────────────────────────────────────────────────────┘ │
│           ↓ 事件分发
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Event Handlers                                     │ │
│  │  - on_tick()    - on_trade()                       │ │
│  │  - on_order()   - on_position()                    │ │
│  │  - on_log()     - on_account()                      │ │
│  └──────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────┤
│  Data Objects (dataclass)                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │ TickData │ │ BarData  │ │OrderData │ │TradeData │    │
│  │Position  │ │ Account  │ │Contract  │ │ LogData  │    │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
├────────────────────────────────────────────────────────────┤
│  Database Layer                                            │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  BaseDatabase (抽象)                                │ │
│  │  - save_bar_data() / load_bar_data()               │ │
│  │  - delete_bar_data() / get_bar_overview()           │ │
│  └──────────────────────────────────────────────────────┘ │
│           ↓ 实现
│  ┌──────────────────────────────────────────────────────┐ │
│  │  SQLiteDatabase (SQLite 实现)                       │ │
│  │  MySQLDatabase (MySQL 实现)                         │ │
│  │  MongoDBDatabase (MongoDB 实现)                     │ │
│  └──────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────┤
│  Notification System                                       │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  EmailEngine                                        │ │
│  │  - send_email(subject, content, receiver)           │ │
│  │  - 交易通知 / 异常告警 / 自定义模板                 │ │
│  └──────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
```

---

## 四、实施计划

### 4.1 实施阶段

| 阶段 | 任务 | 预计工作量 |
|------|------|-----------|
| Phase 1 | 创建 event 目录，实现 EventEngine | 1天 |
| Phase 2 | 创建 objects 目录，使用 dataclass 定义数据对象 | 1天 |
| Phase 3 | 创建 database 目录，实现 BaseDatabase 和 SQLite | 2天 |
| Phase 4 | 创建 notify 目录，实现 EmailEngine | 1天 |
| Phase 5 | Cerebro 集成和测试 | 1.5天 |
| Phase 6 | 文档和示例 | 0.5天 |

### 4.2 优先级

1. **P0**: EventEngine - 事件驱动引擎
2. **P0**: dataclass 数据对象 - 现代化数据结构
3. **P1**: BaseDatabase - 数据库抽象层
4. **P1**: SQLiteDatabase - SQLite 实现
5. **P2**: EmailEngine - 邮件通知
6. **P2**: 其他数据库实现（MySQL, MongoDB）

---

## 五、参考资料

### 5.1 关键参考代码

- vnpy/event/engine.py - EventEngine 事件引擎
- vnpy/trader/engine.py - MainEngine 主引擎
- vnpy/trader/gateway.py - BaseGateway 网关抽象
- vnpy/trader/object.py - 数据对象定义
- vnpy/trader/event.py - 事件类型常量
- vnpy/trader/database.py - 数据库抽象层

### 5.2 关键设计模式

1. **事件驱动模式** - EventEngine + Event
2. **抽象工厂模式** - BaseDatabase 支持多种数据库
3. **策略模式** - Gateway 支持多种交易系统
4. **观察者模式** - 事件处理器注册机制

### 5.3 backtrader 可复用组件

- `backtrader/cerebro.py` - 引擎基类
- `backtrader/lineseries.py` - 数据访问
- `backtrader/broker.py` - 订单管理
- `backtrader/feeds.py` - 数据源
