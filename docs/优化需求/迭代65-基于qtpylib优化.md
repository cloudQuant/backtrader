### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/qtpylib
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### qtpylib项目简介
qtpylib是一个Pythonic的算法交易库，具有以下核心特点：
- **简洁API**: 非常简洁的策略编写接口
- **实时交易**: 专注于实时交易功能
- **IB集成**: 与Interactive Brokers深度集成
- **Blotter**: 独立的Blotter进程管理订单
- **SMS通知**: 支持SMS交易通知
- **MySQL存储**: 使用MySQL存储交易数据

### 重点借鉴方向
1. **简洁API**: 策略编写的简洁接口
2. **Blotter架构**: 独立Blotter进程设计
3. **数据流**: 实时数据流处理
4. **通知系统**: 交易通知和报警
5. **报表生成**: 交易报表生成
6. **历史数据**: 历史数据管理

---

## 研究分析

### QTPyLib架构特点总结

通过对QTPyLib项目的深入研究，总结出以下核心架构特点：

#### 1. 极简的事件驱动API
```python
class MyStrategy(Algo):
    def on_tick(self, instrument):
        tick = instrument.get_ticks(lookback=1)
        if self.condition(tick):
            instrument.buy(1, target=100, stop=90)

    def on_fill(self, instrument, order):
        self.sms(f"Order filled: {order}")
```
- 6个核心回调：`on_start`, `on_tick`, `on_bar`, `on_quote`, `on_orderbook`, `on_fill`
- Instrument对象封装了数据和交易方法
- 策略代码极度简洁，专注于交易逻辑

#### 2. Blotter-独立数据服务架构
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   IB TWS    │ →   │   Blotter   │ →   │   ZeroMQ    │
│  (数据源)   │     │ (数据处理)  │     │  (广播)     │
└─────────────┘     └─────────────┘     └─────────────┘
                           ↓
                    ┌─────────────┐
                    │   MySQL     │
                    │  (持久化)   │
                    └─────────────┘
```
- Blotter作为独立进程运行
- 负责数据采集、清洗、重采样、存储、广播
- 通过ZeroMQ向多个策略实例广播数据
- 策略与数据服务解耦，可独立扩展

#### 3. 数据流处理特点
- **多粒度支持**: Ticks → Bars (秒/分/时)
- **连续合约**: 期货合约自动滚动
- **自动回填**: 检测并填补历史数据缺口
- **幂等写入**: 重复数据不会重复存储

#### 4. 订单管理创新
- **Bracket订单**: 一键设置入场+止盈+止损
- **Trailing Stop**: 内置移动止损
- **Trade生命周期**: 从入场到出场自动跟踪
- **订单过期**: 未成交订单自动取消

#### 5. Instrument包装器
- 继承自`str`，可作为字符串使用
- 封装数据访问和交易方法
- 支持方法链式调用
- 期货保证金计算

### Backtrader当前架构特点

#### 优势
- **丰富的指标库**: 60+技术指标
- **多市场支持**: 股票、期货、外汇、加密货币
- **灵活的经纪人系统**: 支持多种实盘接口
- **完善的回测引擎**: 支持多种优化模式
- **PyFolio集成**: 专业的性能分析

#### 局限性（对比QTPyLib）
1. **API复杂度**: 策略编写需要理解较多概念
2. **数据服务**: 无独立的数据服务进程
3. **通知系统**: 仅有基础回调，无外部通知集成
4. **数据持久化**: 无数据库集成，仅文件存储
5. **报表系统**: 缺少实时监控仪表板
6. **期货合约**: 无自动滚动功能
7. **Bracket订单**: 需要手动实现

---

## 需求规格文档

### 1. 简化策略API (Simplified Strategy API)

#### 1.1 功能描述
提供更简洁的策略编写接口，隐藏复杂性，让开发者专注交易逻辑。

#### 1.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| API-001 | 创建简化的Strategy基类 | P0 |
| API-002 | 提供Instrument包装器 | P0 |
| API-003 | 支持链式订单方法 | P1 |
| API-004 | 简化数据访问接口 | P1 |
| API-005 | 内置信号记录功能 | P2 |

#### 1.3 接口设计
```python
class SimpleStrategy(bt.Strategy):
    """简化的策略基类"""

    # 事件回调
    def on_tick(self): pass      # 每个tick触发
    def on_bar(self): pass       # 每个bar触发
    def on_fill(self, order): pass  # 订单成交触发

    # 数据访问（通过instrument）
    def instrument(self, data):
        return InstrumentWrapper(data, self)
```

### 2. Blotter数据服务架构

#### 2.1 功能描述
创建独立的数据服务进程，负责数据采集、处理、存储和广播。

#### 2.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| BLT-001 | 创建Blotter独立进程 | P0 |
| BLT-002 | 实现ZeroMQ数据广播 | P0 |
| BLT-003 | 支持多策略数据订阅 | P1 |
| BLT-004 | 实现数据回填功能 | P1 |
| BLT-005 | 支持期货连续合约 | P2 |

#### 2.3 接口设计
```python
class Blotter:
    """数据服务进程"""

    def run(self):
        """启动blotter服务"""

    def stream(self, symbols, callback):
        """订阅数据流"""

    def history(self, symbols, start, end, resolution):
        """查询历史数据"""
```

### 3. 通知系统 (Notification System)

#### 3.1 功能描述
扩展现有的通知回调，支持多种外部通知渠道。

#### 3.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| NOTIF-001 | 定义通知提供者接口 | P0 |
| NOTIF-002 | 实现邮件通知 | P0 |
| NOTIF-003 | 实现SMS通知 (Twilio/Nexmo) | P1 |
| NOTIF-004 | 实现Webhook通知 | P1 |
| NOTIF-005 | 实现企业微信/钉钉通知 | P2 |
| NOTIF-006 | 实现Telegram/Discord通知 | P2 |
| NOTIF-007 | 支持通知级别和过滤 | P2 |

#### 3.3 接口设计
```python
class NotificationProvider(ABC):
    @abstractmethod
    def send(self, message: str, **kwargs):
        """发送通知"""

class NotificationManager:
    def __init__(self):
        self.providers = []

    def add_provider(self, provider: NotificationProvider):
        self.providers.append(provider)

    def notify(self, message: str, level: str = "INFO"):
        for provider in self.providers:
            provider.send(message, level=level)
```

### 4. 数据持久化增强 (Data Persistence)

#### 4.1 功能描述
添加数据库支持，实现交易数据的持久化存储。

#### 4.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| DB-001 | 定义数据库存储接口 | P0 |
| DB-002 | 实现MySQL存储 | P0 |
| DB-003 | 实现SQLite存储 | P0 |
| DB-004 | 实现PostgreSQL存储 | P1 |
| DB-005 | 实现InfluxDB时序存储 | P2 |
| DB-006 | 支持数据回填和更新 | P1 |
| DB-007 | 支持数据压缩和归档 | P2 |

#### 4.3 接口设计
```python
class DatabaseStore(ABC):
    @abstractmethod
    def save_bar(self, data, bar): pass

    @abstractmethod
    def save_trade(self, trade): pass

    @abstractmethod
    def load_bars(self, symbol, start, end): pass

class MySQLStore(DatabaseStore):
    """MySQL存储实现"""
```

### 5. 报表和仪表板 (Reports & Dashboard)

#### 5.1 功能描述
提供Web-based实时监控仪表板和REST API。

#### 5.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| RPT-001 | 创建Web仪表板 | P0 |
| RPT-002 | 实现REST API | P0 |
| RPT-003 | 实时P&L显示 | P1 |
| RPT-004 | 持仓监控 | P1 |
| RPT-005 | 交易历史查询 | P1 |
| RPT-006 | 性能指标可视化 | P2 |
| RPT-007 | 多策略支持 | P2 |

#### 5.3 接口设计
```python
class Dashboard:
    """Web仪表板"""

    def __init__(self, port=5000):
        self.app = Flask(__name__)

    def run(self):
        """启动仪表板服务"""

    def add_endpoint(self, path, handler):
        """添加自定义API端点"""
```

### 6. 订单管理增强 (Order Management)

#### 6.1 功能描述
增强订单功能，支持Bracket订单和高级订单类型。

#### 6.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| ORD-001 | 实现Bracket订单 | P0 |
| ORD-002 | 实现Trailing Stop | P1 |
| ORD-003 | 实现订单过期功能 | P1 |
| ORD-004 | OCO订单支持 | P1 |
| ORD-005 | 订单组管理 | P2 |

#### 6.3 接口设计
```python
class BracketOrder:
    """Bracket订单：入场 + 止盈 + 止损"""

    def __init__(self, entry, target, stop, quantity):
        self.entry = entry
        self.target = target
        self.stop = stop
        self.quantity = quantity

# 使用方式
self.buy_bracket(size=100, target=105, stop=95)
```

### 7. 期货连续合约 (Futures Continuous Contract)

#### 7.1 功能描述
支持期货合约的自动滚动和连续合约构建。

#### 7.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| FUT-001 | 检测活跃合约 | P0 |
| FUT-002 | 实现合约滚动逻辑 | P0 |
| FUT-003 | 构建连续合约数据 | P1 |
| FUT-004 | 支持多种滚动规则 | P2 |

---

## 设计文档

### 整体架构设计

#### 1. 目录结构
```
backtrader/
├── utils/
│   └── notifications/         # 通知系统
│       ├── __init__.py
│       ├── base.py            # 抽象基类
│       ├── email.py           # 邮件通知
│       ├── sms.py             # SMS通知
│       ├── webhook.py         # Webhook通知
│       └── managers.py        # 通知管理器
│
├── store/
│   ├── database/              # 数据库存储
│   │   ├── __init__.py
│   │   ├── base.py            # 抽象基类
│   │   ├── mysql.py           # MySQL实现
│   │   ├── sqlite.py          # SQLite实现
│   │   └── schema.py          # 数据库模式
│   └── blotter/               # Blotter数据服务
│       ├── __init__.py
│       ├── blotter.py         # Blotter主进程
│       ├── zmq_pub.py         # ZeroMQ发布者
│       └── data_sub.py        # 数据订阅者
│
├── orders/                    # 订单增强
│   ├── __init__.py
│   ├── bracket.py             # Bracket订单
│   ├── trailing_stop.py       # 移动止损
│   └── order_group.py         # 订单组管理
│
├── futures/                   # 期货增强
│   ├── __init__.py
│   ├── continuous.py          # 连续合约
│   └── roller.py              # 合约滚动
│
├── strategy/                  # 策略增强
│   ├── __init__.py
│   ├── simple.py              # 简化策略基类
│   └── instrument.py          # Instrument包装器
│
└── dashboard/                 # Web仪表板
    ├── __init__.py
    ├── app.py                 # Flask应用
    ├── api/                   # API端点
    └── templates/             # HTML模板
```

### 详细设计

#### 1. 通知系统设计

```python
# utils/notifications/base.py
from abc import ABC, abstractmethod

class NotificationProvider(ABC):
    """通知提供者抽象基类"""

    @abstractmethod
    def send(self, message: str, **kwargs):
        """发送通知

        Args:
            message: 通知消息
            **kwargs: 额外参数 (level, subject, recipients等)
        """
        pass
```

```python
# utils/notifications/email.py
import smtplib
from email.mime.text import MIMEText

class EmailNotification(NotificationProvider):
    """邮件通知实现"""

    def __init__(self, smtp_host, smtp_port, username, password,
                 from_addr=None):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr or username

    def send(self, message: str, subject="Backtrader Notification",
             recipients=None, level="INFO", **kwargs):
        """发送邮件通知"""
        if not recipients:
            return

        msg = MIMEText(message)
        msg['Subject'] = f"[{level}] {subject}"
        msg['From'] = self.from_addr
        msg['To'] = ', '.join(recipients)

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            server.login(self.username, self.password)
            server.send_message(msg)
```

```python
# utils/notifications/sms.py
class SMSNotification(NotificationProvider):
    """SMS通知实现（支持Twilio和Nexmo）"""

    def __init__(self, provider='twilio', **config):
        self.provider = provider
        self.config = config

    def send(self, message: str, recipients=None, **kwargs):
        """发送SMS通知"""
        if self.provider == 'twilio':
            self._send_twilio(message, recipients)
        elif self.provider == 'nexmo':
            self._send_nexmo(message, recipients)
```

```python
# utils/notifications/managers.py
class NotificationManager:
    """通知管理器"""

    LEVELS = {
        'DEBUG': 0,
        'INFO': 1,
        'WARNING': 2,
        'ERROR': 3,
        'CRITICAL': 4
    }

    def __init__(self, min_level='INFO'):
        self.providers = []
        self.min_level = self.LEVELS.get(min_level, 1)

    def add_provider(self, provider: NotificationProvider):
        """添加通知提供者"""
        self.providers.append(provider)

    def notify(self, message: str, level='INFO', **kwargs):
        """发送通知到所有提供者"""
        if self.LEVELS.get(level, 1) < self.min_level:
            return

        for provider in self.providers:
            try:
                provider.send(message, level=level, **kwargs)
            except Exception as e:
                print(f"Notification failed: {e}")
```

#### 2. 策略集成通知

```python
# strategy/simple.py
import backtrader as bt
from ..utils.notifications import NotificationManager

class NotifiedStrategy(bt.Strategy):
    """支持通知的策略基类"""

    params = (
        ('notification_manager', None),
        ('notify_on_order', True),
        ('notify_on_trade', True),
        ('notify_level', 'INFO'),
    )

    def __init__(self):
        self.notifier = self.p.notification_manager or NotificationManager()

    def notify_order(self, order):
        """订单状态变更通知"""
        if not self.p.notify_on_order:
            return

        if order.status in [order.Completed]:
            msg = f"Order completed: {order.data._name} " \
                  f"{order.getordertype()} {order.size} @ {order.price}"

            if order.isbuy():
                direction = "BUY"
            else:
                direction = "SELL"

            msg = f"ORDER {direction}: {order.data._name} " \
                  f"Qty={order.executed.size} Price={order.executed.price}"

            self.notifier.notify(msg, level=self.p.notify_level)

    def notify_trade(self, trade):
        """交易完成通知"""
        if not self.p.notify_on_trade:
            return

        if trade.isclosed:
            pnl = trade.pnl
            msg = f"TRADE CLOSED: {trade.data._name} " \
                  f"PnL={pnl:.2f} Comm={trade.commission:.2f}"

            level = 'INFO' if pnl > 0 else 'WARNING'
            self.notifier.notify(msg, level=level)
```

#### 3. Bracket订单设计

```python
# orders/bracket.py
import backtrader as bt

class BracketOrder:
    """Bracket订单管理器

    Bracket订单包含三个部分：
    1. 入场订单 (Entry Order)
    2. 止盈订单 (Take Profit Order)
    3. 止损订单 (Stop Loss Order)
    """

    def __init__(self, strategy, data, size,
                 entry_price=None, target_price=None, stop_price=None,
                 limit_price=None, oco=True):

        self.strategy = strategy
        self.data = data
        self.size = size
        self.entry_price = entry_price
        self.target_price = target_price
        self.stop_price = stop_price
        self.limit_price = limit_price
        self.oco = oco  # One-Cancels-Other

        self.entry_order = None
        self.target_order = None
        self.stop_order = None
        self.is_active = True

    def execute(self):
        """执行Bracket订单"""
        # 1. 创建入场订单
        if self.entry_price:
            self.entry_order = self.strategy.buy(
                self.data, size=self.size, price=self.entry_price,
                exectype=bt.Order.Limit)
        else:
            self.entry_order = self.strategy.buy(
                self.data, size=self.size, exectype=bt.Order.Market)

        # 2. 创建止盈订单
        if self.target_price:
            self.target_order = self.strategy.sell(
                self.data, size=self.size, price=self.target_price,
                exectype=bt.Order.Limit)

        # 3. 创建止损订单
        if self.stop_price:
            self.stop_order = self.strategy.sell(
                self.data, size=self.size, price=self.stop_price,
                exectype=bt.Order.Stop)

        return self.entry_order

    def cancel_children(self):
        """取消子订单（OCO逻辑）"""
        if self.target_order and self.target_order.alive:
            self.strategy.cancel(self.target_order)
        if self.stop_order and self.stop_order.alive:
            self.strategy.cancel(self.stop_order)

    def on_entry_filled(self):
        """入场订单成交后的处理"""
        if not self.oco:
            return

        # 如果使用OCO，一个子订单成交则取消另一个
        # 这需要在策略的notify_order中调用


# 在Strategy中使用
class BracketStrategy(bt.Strategy):

    def buy_bracket(self, data, size, target=None, stop=None,
                    limit=None, oco=True):
        """买入Bracket订单"""
        bracket = BracketOrder(
            self, data, size,
            target_price=target,
            stop_price=stop,
            limit_price=limit,
            oco=oco
        )
        return bracket.execute()
```

#### 4. 数据库存储设计

```python
# store/database/base.py
from abc import ABC, abstractmethod

class DatabaseStore(ABC):
    """数据库存储抽象基类"""

    @abstractmethod
    def connect(self): pass

    @abstractmethod
    def disconnect(self): pass

    @abstractmethod
    def save_bar(self, symbol, timestamp, ohlcv): pass

    @abstractmethod
    def save_trade(self, trade): pass

    @abstractmethod
    def load_bars(self, symbol, start, end, resolution='1D'): pass

    @abstractmethod
    def save_order(self, order): pass
```

```python
# store/database/mysql.py
import mysql.connector
from .base import DatabaseStore

class MySQLStore(DatabaseStore):
    """MySQL存储实现"""

    def __init__(self, host, database, user, password,
                 port=3306, charset='utf8mb4'):
        self.config = {
            'host': host,
            'database': database,
            'user': user,
            'password': password,
            'port': port,
            'charset': charset
        }
        self.connection = None

    def connect(self):
        """建立数据库连接"""
        self.connection = mysql.connector.connect(**self.config)

    def save_bar(self, symbol, timestamp, ohlcv):
        """保存bar数据"""
        query = """
        INSERT INTO bars (symbol, datetime, open, high, low, close, volume)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            open = VALUES(open),
            high = VALUES(high),
            low = VALUES(low),
            close = VALUES(close),
            volume = VALUES(volume)
        """
        cursor = self.connection.cursor()
        cursor.execute(query, (
            symbol, timestamp,
            ohlcv['open'], ohlcv['high'], ohlcv['low'],
            ohlcv['close'], ohlcv['volume']
        ))
        self.connection.commit()
```

#### 5. Web仪表板设计

```python
# dashboard/app.py
from flask import Flask, jsonify, render_template
import backtrader as bt

class Dashboard:
    """Backtrader Web仪表板"""

    def __init__(self, host='0.0.0.0', port=5000, password=None):
        self.app = Flask(__name__)
        self.host = host
        self.port = port
        self.password = password
        self.strategies = {}

        self._setup_routes()

    def _setup_routes(self):
        """设置路由"""

        @self.app.route('/')
        def index():
            """主页"""
            return render_template('dashboard.html',
                                   strategies=self.strategies)

        @self.app.route('/api/strategies')
        def list_strategies():
            """列出所有策略"""
            return jsonify(list(self.strategies.keys()))

        @self.app.route('/api/strategy/<name>/positions')
        def get_positions(name):
            """获取策略持仓"""
            if name not in self.strategies:
                return jsonify({'error': 'Strategy not found'}), 404

            strategy = self.strategies[name]
            positions = {}

            for data in strategy.datas:
                pos = strategy.getposition(data)
                if pos.size != 0:
                    positions[data._name] = {
                        'size': pos.size,
                        'price': pos.price,
                        'value': pos.size * data.close[0]
                    }

            return jsonify(positions)

        @self.app.route('/api/strategy/<name>/pnl')
        def get_pnl(name):
            """获取策略P&L"""
            if name not in self.strategies:
                return jsonify({'error': 'Strategy not found'}), 404

            strategy = self.strategies[name]

            # 计算总P&L
            total_pnl = 0
            for trade in strategy.trades:
                if trade.isclosed:
                    total_pnl += trade.pnl

            return jsonify({
                'total_pnl': total_pnl,
                'cash': strategy.broker.get_cash(),
                'value': strategy.broker.get_value()
            })

    def register_strategy(self, name, strategy):
        """注册策略"""
        self.strategies[name] = strategy

    def run(self):
        """启动仪表板"""
        self.app.run(host=self.host, port=self.port, debug=False)
```

#### 6. Blotter数据服务设计

```python
# store/blotter/blotter.py
import zmq
import threading
from queue import Queue

class Blotter:
    """数据服务进程

    负责从数据源采集数据，处理后广播给订阅者
    """

    def __init__(self, zmq_port=5555):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind(f"tcp://*:{zmq_port}")

        self.subscribers = {}
        self.running = False

    def add_data_source(self, name, data_feed):
        """添加数据源"""
        self.subscribers[name] = data_feed

    def start(self):
        """启动Blotter服务"""
        self.running = True

        # 数据广播线程
        broadcast_thread = threading.Thread(target=self._broadcast_loop)
        broadcast_thread.start()

    def _broadcast_loop(self):
        """数据广播循环"""
        while self.running:
            for name, feed in self.subscribers.items():
                # 获取最新数据
                if hasattr(feed, 'next'):
                    try:
                        feed.next()

                        # 构造消息
                        message = {
                            'symbol': name,
                            'datetime': feed.datetime.datetime(0),
                            'open': feed.open[0],
                            'high': feed.high[0],
                            'low': feed.low[0],
                            'close': feed.close[0],
                            'volume': feed.volume[0] if hasattr(feed, 'volume') else 0
                        }

                        # 广播
                        topic = f"{name}".encode()
                        self.socket.send_multipart([topic, str(message).encode()])

                    except:
                        pass


class BlotterSubscriber:
    """Blotter数据订阅者"""

    def __init__(self, zmq_host='localhost', zmq_port=5555):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.connect(f"tcp://{zmq_host}:{zmq_port}")

        self.callbacks = {}

    def subscribe(self, symbol, callback):
        """订阅数据"""
        self.socket.setsockopt_string(zmq.SUBSCRIBE, symbol)
        self.callbacks[symbol] = callback

    def start(self):
        """开始接收数据"""
        while True:
            topic, message = self.socket.recv_multipart()
            symbol = topic.decode()
            data = eval(message.decode())

            if symbol in self.callbacks:
                self.callbacks[symbol](data)
```

### 使用示例

#### 示例1: 带通知的策略

```python
import backtrader as bt
from backtrader.utils.notifications import (
    NotificationManager, EmailNotification
)

# 配置通知
notifier = NotificationManager(min_level='INFO')
notifier.add_provider(EmailNotification(
    smtp_host='smtp.gmail.com',
    smtp_port=587,
    username='your@email.com',
    password='your-password'
))

class MyStrategy(NotifiedStrategy):
    params = (
        ('notification_manager', notifier),
    )

    def __init__(self):
        super().__init__()
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):
        if not self.position:
            if self.data.close[0] > self.sma[0]:
                self.buy(size=100)
        else:
            if self.data.close[0] < self.sma[0]:
                self.sell(size=self.position.size)
```

#### 示例2: Bracket订单

```python
class BracketStrategy(bt.Strategy):

    def next(self):
        if not self.position and self.data.close[0] > self.data.close[-1]:
            # 使用Bracket订单
            self.buy_bracket(
                data=self.data,
                size=100,
                limit=self.data.close[0],  # 限价入场
                target=self.data.close[0] * 1.05,  # 止盈5%
                stop=self.data.close[0] * 0.95,    # 止损5%
                oco=True
            )
```

#### 示例3: 使用仪表板

```python
import backtrader as bt
from backtrader.dashboard import Dashboard

# 创建并启动仪表板
dashboard = Dashboard(port=5000)

# 运行策略
cerebro = bt.Cerebro()
cerebro.addstrategy(MyStrategy)
strats = cerebro.run()

# 注册策略到仪表板
for i, strat in enumerate(strats):
    dashboard.register_strategy(f"strategy_{i}", strat)

# 启动仪表板
dashboard.run()
```

### 实施计划

#### 第一阶段 (P0功能)
1. 通知系统基础架构和邮件实现
2. 数据库存储抽象层和MySQL/SQLite实现
3. Bracket订单功能
4. 简化策略基类

#### 第二阶段 (P1功能)
1. SMS和Webhook通知
2. Web仪表板基础功能
3. Blotter数据服务基础架构
4. Trailing Stop订单

#### 第三阶段 (P2功能)
1. 期货连续合约
2. 高级通知渠道（企业微信、钉钉、Telegram）
3. 时序数据库支持
4. 完整的Blotter服务

---

## 总结

通过借鉴QTPyLib的设计理念，Backtrader可以扩展以下能力：

1. **极简API**: 降低策略编写复杂度，提高开发效率
2. **独立数据服务**: Blotter架构实现数据与策略解耦
3. **完整通知系统**: 支持多种通知渠道，及时获取交易状态
4. **数据持久化**: 数据库存储支持，便于历史分析
5. **实时监控**: Web仪表板提供实时P&L和持仓监控
6. **高级订单**: Bracket订单和移动止损简化交易逻辑

这些增强功能将使Backtrader在保持原有强大回测能力的同时，更好地支持实时交易场景，提供更完整的生产级量化交易解决方案。
