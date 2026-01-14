### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/xtp-backtrader-api
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### xtp-backtrader-api项目简介
xtp-backtrader-api是中泰XTP与backtrader的集成API，具有以下核心特点：
- **XTP集成**: 集成中泰XTP接口
- **A股交易**: 支持A股交易
- **实时行情**: 实时Level2行情
- **快速交易**: 低延迟交易
- **订单管理**: 完整订单管理
- **资金查询**: 资金持仓查询

### 重点借鉴方向
1. **XTP集成**: XTP接口集成
2. **A股特性**: A股市场特性
3. **Level2行情**: Level2行情处理
4. **低延迟**: 低延迟交易
5. **接口封装**: 交易接口封装
6. **回调处理**: 回调事件处理

---

## 架构对比分析

### Backtrader 核心特点

**优势:**
1. **成熟的回测引擎**: Cerebro统一管理策略、数据、经纪商、分析器
2. **灵活的策略系统**: 支持多种策略编写方式
3. **丰富的指标库**: 60+内置技术指标
4. **多数据源支持**: 支持多种数据格式

**局限:**
1. **实盘交易支持弱**: 主要面向回测，实盘需要额外配置
2. **缺少A股支持**: 没有针对A股市场的特性支持
3. **低延迟优化不足**: 回测架构不适合高频交易
4. **订单管理简陋**: 缺少完整的订单状态跟踪
5. **行情订阅单一**: 不支持Level2行情

### XTP-Backtrader-API 核心特点

**优势:**
1. **单例Store架构**: MetaSingleton确保全局唯一连接
2. **完整A股支持**: 支持A股交易规则和特性
3. **Level2行情**: 实时Level2深度行情数据
4. **低延迟交易**: 直接对接XTP API，最小化延迟
5. **事件驱动回调**: 完整的订单、成交、持仓回调机制
6. **断线重连**: 自动重连和错误恢复机制
7. **时间同步**: 自动时间戳偏移校正
8. **内存优化**: 使用deque高效管理数据流
9. **订单状态跟踪**: 实时订单状态更新
10. **资金持仓查询**: 完整的账户资产查询

**局限:**
1. **依赖XTP**: 与中泰XTP强耦合
2. **文档不足**: README和示例代码较少
3. **测试覆盖低**: 缺少完整的测试用例
4. **单一市场**: 仅支持A股市场

---

## 需求规格文档

### 1. 证券交易所适配器架构 (优先级: 高)

**需求描述:**
建立统一的证券交易所适配器架构，支持多家券商API接入。

**功能需求:**
1. **ExchangeStore基类**: 统一的交易所连接管理
2. **单例模式**: 确保全局唯一连接实例
3. **连接池管理**: 支持多连接管理
4. **心跳机制**: 保持连接活跃
5. **断线重连**: 自动重连机制
6. **状态监控**: 连接状态实时监控

**非功能需求:**
1. 线程安全设计
2. 低延迟通信
3. 资源自动释放

### 2. A股市场特性支持 (优先级: 高)

**需求描述:**
添加A股市场的特殊特性支持，包括交易规则、结算周期等。

**功能需求:**
1. **交易时间**: A股交易时间段管理
2. **涨跌停限制**: 10%/20%涨跌停检测
3. **T+1交易**: 当日买入次日才能卖出
4. **最小单位**: 100股整数倍交易
5. **印花税**: 卖出单边收取印花税
6. **融资融券**: 融资融券交易支持
7. **新股申购**: 新股申购功能
8. **分红配股**: 除权除息处理

**非功能需求:**
1. 符合交易所规则
2. 准确的费用计算

### 3. Level2行情处理 (优先级: 高)

**需求描述:**
支持Level2深度行情数据，提供更完整的市场信息。

**功能需求:**
1. **五档行情**: 买一到买五、卖一到卖五
2. **逐笔成交**: 逐笔成交数据
3. **委托队列**: 买卖委托队列信息
4. **tick数据**: tick级行情数据
5. **行情订阅**: 多标的行情订阅
6. **数据缓存**: 行情数据本地缓存

**非功能需求:**
1. 低延迟数据更新
2. 高吞吐量处理

### 4. 低延迟交易架构 (优先级: 高)

**需求描述:**
优化交易架构，实现低延迟的订单执行。

**功能需求:**
1. **异步下单**: 非阻塞订单提交
2. **订单队列**: 高效的订单队列管理
3. **快速回调**: 最小化回调处理时间
4. **内存优化**: 使用deque等高效数据结构
5. **线程池**: 独立的IO和计算线程
6. **零拷贝**: 减少数据拷贝

**非功能需求:**
1. 订单延迟<10ms
2. 支持每秒1000+订单

### 5. 完整订单管理系统 (优先级: 中)

**需求描述:**
建立完整的订单生命周期管理系统。

**功能需求:**
1. **订单状态**: 创建、提交、挂起、部分成交、完全成交、撤单、拒绝
2. **订单修改**: 订单价格和数量修改
3. **批量撤单**: 批量撤销订单
4. **订单查询**: 历史订单查询
5. **成交记录**: 详细成交记录
6. **订单事件**: 订单状态变化事件

**非功能需求:**
1. 订单状态实时更新
2. 不丢失订单事件

### 6. 事件驱动回调系统 (优先级: 中)

**需求描述:**
建立完善的事件驱动回调系统，处理各种交易事件。

**功能需求:**
1. **订单事件**: 订单状态变化通知
2. **成交事件**: 成交回报通知
3. **持仓事件**: 持仓变化通知
4. **资金事件**: 资金变化通知
5. **错误事件**: 错误和异常通知
6. **断线事件**: 连接断开通知
7. **事件过滤**: 事件订阅和过滤

**非功能需求:**
1. 事件处理不阻塞主线程
2. 事件不丢失

### 7. 账户资产查询 (优先级: 中)

**需求描述:**
提供完整的账户资产查询功能。

**功能需求:**
1. **资金查询**: 可用资金、总资产、持仓市值
2. **持仓查询**: 持仓数量、成本价、当前价、盈亏
3. **委托查询**: 当前委托查询
4. **成交查询**: 历史成交查询
5. **历史查询**: 历史委托和成交
6. **实时更新**: 资产持仓实时更新

---

## 设计文档

### 1. 证券交易所适配器架构设计

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
              │  ExchangeStore │
              │   (单例模式)    │
              └───────┬────────┘
                      │
          ┌───────────┼───────────┐
          │           │           │
          ▼           ▼           ▼
    ┌─────────┐ ┌─────────┐ ┌──────────┐
    │Quote API│ │Trade API│ │Data API  │
    └─────────┘ └─────────┘ └──────────┘
```

#### 1.2 ExchangeStore基类设计

```python
# backtrader/exchange/store_base.py
import threading
from abc import ABC, abstractmethod
from collections import deque
from backtrader.metabase import MetaSingleton
import logging
import time

class ExchangeStore(with_metaclass(MetaSingleton, object)):
    """
    交易所存储基类，使用单例模式确保全局唯一连接

    设计特点:
    1. 单例模式: 避免重复连接
    2. 心跳机制: 保持连接活跃
    3. 断线重连: 自动重连
    4. 线程安全: 保护共享资源
    """
    _instances = {}
    _lock = threading.Lock()

    # 参数定义
    params = (
        # 连接参数
        ('server_ip', '127.0.0.1'),
        ('server_port', 7709),
        ('username', ''),
        ('password', ''),
        ('client_id', 1),

        # 交易参数
        ('account_id', ''),
        ('account_type', 0),  # 0=普通, 1=信用

        # 行情参数
        ('market_type', 1),  # 1=上海, 2=深圳

        # 系统参数
        ('timeout', 3.0),
        ('heartbeat_interval', 10.0),
        ('auto_reconnect', True),
        ('reconnect_interval', 5.0),
        ('max_reconnect', 10),

        # 时间同步
        ('time_sync', True),
        ('time_refresh', 60.0),
    )

    def __init__(self):
        # 连接状态
        self._connected = False
        self._reconnect_count = 0
        self._last_heartbeat = 0

        # 数据队列（线程安全）
        self._quote_notifs = deque()
        self._order_notifs = deque()
        self._trade_notifs = deque()

        # API实例
        self._quote_api = None
        self._trade_api = None

        # 日志
        self._logger = logging.getLogger(self.__class__.__name__)

        # 锁
        self._quote_lock = threading.Lock()
        self._trade_lock = threading.Lock()

    @property
    def connected(self):
        """获取连接状态"""
        return self._connected

    def connect(self):
        """建立连接"""
        with self._lock:
            if self._connected:
                return True

            try:
                # 连接行情API
                self._connect_quote()

                # 连接交易API
                self._connect_trade()

                self._connected = True
                self._reconnect_count = 0
                self._last_heartbeat = time.time()

                self._logger.info("连接成功")
                return True

            except Exception as e:
                self._logger.error(f"连接失败: {e}")
                return False

    def disconnect(self):
        """断开连接"""
        with self._lock:
            if not self._connected:
                return

            try:
                self._disconnect_quote()
                self._disconnect_trade()
                self._connected = False
                self._logger.info("断开连接")
            except Exception as e:
                self._logger.error(f"断开连接失败: {e}")

    def reconnect(self):
        """重连"""
        if not self.p.auto_reconnect:
            return False

        if self._reconnect_count >= self.p.max_reconnect:
            self._logger.error("达到最大重连次数")
            return False

        self._reconnect_count += 1
        self._logger.info(f"尝试重连 ({self._reconnect_count}/{self.p.max_reconnect})")

        time.sleep(self.p.reconnect_interval)
        return self.connect()

    def heartbeat(self):
        """心跳检测"""
        if not self._connected:
            return False

        current_time = time.time()
        if current_time - self._last_heartbeat > self.p.heartbeat_interval:
            try:
                self._send_heartbeat()
                self._last_heartbeat = current_time
                return True
            except Exception as e:
                self._logger.error(f"心跳失败: {e}")
                self._connected = False
                return self.reconnect()
        return True

    @abstractmethod
    def _connect_quote(self):
        """连接行情API（子类实现）"""
        pass

    @abstractmethod
    def _connect_trade(self):
        """连接交易API（子类实现）"""
        pass

    @abstractmethod
    def _disconnect_quote(self):
        """断开行情API（子类实现）"""
        pass

    @abstractmethod
    def _disconnect_trade(self):
        """断开交易API（子类实现）"""
        pass

    @abstractmethod
    def _send_heartbeat(self):
        """发送心跳（子类实现）"""
        pass

    def get_quote_notification(self):
        """获取行情通知"""
        try:
            return self._quote_notifs.popleft()
        except IndexError:
            return None

    def get_order_notification(self):
        """获取订单通知"""
        try:
            return self._order_notifs.popleft()
        except IndexError:
            return None

    def get_trade_notification(self):
        """获取成交通知"""
        try:
            return self._trade_notifs.popleft()
        except IndexError:
            return None

    def put_notification(self, queue_type, msg):
        """
        放入通知

        Args:
            queue_type: 队列类型 ('quote', 'order', 'trade')
            msg: 消息内容
        """
        if queue_type == 'quote':
            self._quote_notifs.append(msg)
        elif queue_type == 'order':
            self._order_notifs.append(msg)
        elif queue_type == 'trade':
            self._trade_notifs.append(msg)
```

#### 1.3 ExchangeBroker设计

```python
# backtrader/exchange/broker_base.py
from backtrader.broker import BrokerBase
from backtrader.order import Order, BuyOrder, SellOrder
from backtrader.position import Position
import backtrader as bt
from collections import defaultdict
import threading

class ExchangeBroker(BrokerBase):
    """
    交易所经纪商基类

    功能:
    1. 订单管理: 下单、撤单、改单
    2. 持仓管理: 持仓同步和更新
    3. 资金管理: 资金查询
    4. 订单状态跟踪
    """
    params = (
        # 交易参数
        ('commission', 0.0003),     # 佣金率
        ('stamp_duty', 0.001),      # 印花税（卖出）
        ('min_commission', 5.0),    # 最低佣金

        # 持仓管理
        ('use_positions', True),    # 使用服务器持仓
        ('position_interval', 1.0), # 持仓同步间隔（秒）

        # 订单管理
        ('order_prefix', 'BT'),     # 订单前缀
        ('order_id', 0),            # 订单ID计数器
    )

    def __init__(self, store):
        """
        Args:
            store: ExchangeStore实例
        """
        self._store = store
        self._orders = {}           # {order_ref: Order}
        self._orders_exch = {}      # {exchange_id: order_ref}
        self._positions = {}        # {data: Position}
        self._positions_lock = threading.Lock()

        # 资金信息
        self._cash = 0
        self._value = 0

        super().__init__()

    def start(self):
        """启动时同步持仓和资金"""
        self._sync_account()
        if self.p.use_positions:
            self._sync_positions()

    def _sync_account(self):
        """同步账户资金"""
        asset = self._store.query_asset()
        if asset:
            self._cash = asset.available_cash
            self._value = asset.total_asset

    def _sync_positions(self):
        """同步持仓"""
        positions = defaultdict(Position)

        if self.p.use_positions:
            broker_positions = self._store.query_positions()

            for pos in broker_positions:
                # 找到对应的数据源
                for name, data in self.get_datas().items():
                    if name == pos.symbol:
                        positions[data] = Position(
                            pos.quantity,
                            pos.avg_price
                        )
                        break

        with self._positions_lock:
            self._positions = positions

    def get_cash(self):
        """获取可用资金"""
        return self._cash

    def get_value(self):
        """获取总资产"""
        return self._value

    def get_position(self, data):
        """获取持仓"""
        with self._positions_lock:
            return self._positions.get(data, Position())

    def update_positions(self):
        """更新持仓"""
        self._sync_positions()
        return self._positions

    def _submit(self, owner, data, side, exectype, size, price):
        """
        提交订单

        Args:
            owner: 订单所有者
            data: 数据源
            side: 买卖方向 (bt.Order.Buy/Sell)
            exectype: 订单类型
            size: 数量
            price: 价格
        """
        # 生成本地订单ID
        self.p.order_id += 1
        order_ref = f"{self.p.order_prefix}{self.p.order_id:08d}"

        # 创建Backtrader订单
        otype = BuyOrder if side == bt.Order.Buy else SellOrder
        order = otype(
            owner=owner,
            data=data,
            ref=order_ref,
            size=size,
            price=price,
            exectype=exectype,
        )

        # 保存订单
        self._orders[order_ref] = order
        order.addcomission()

        # 提交到交易所
        try:
            exchange_id = self._store.submit_order(
                symbol=data._name,
                side=side,
                size=size,
                price=price if exectype != bt.Order.Market else None,
                order_type=exectype,
                order_ref=order_ref,
            )

            # 保存交易所ID映射
            if exchange_id:
                self._orders_exch[exchange_id] = order_ref
                order.exchange_id = exchange_id

        except Exception as e:
            self.logger.error(f"提交订单失败: {e}")
            order.reject()
            return order

        order.accepted()
        return order

    def _cancel(self, order):
        """取消订单"""
        if order.exchange_id:
            try:
                self._store.cancel_order(order.exchange_id)
            except Exception as e:
                self.logger.error(f"取消订单失败: {e}")

    def on_order_event(self, order_event):
        """
        处理订单事件

        Args:
            order_event: 订单事件对象
                - exchange_id: 交易所订单ID
                - status: 订单状态
                - filled_qty: 已成交数量
                - avg_price: 平均成交价
        """
        order_ref = self._orders_exch.get(order_event.exchange_id)
        if not order_ref:
            return

        order = self._orders.get(order_ref)
        if not order:
            return

        # 更新订单状态
        status_map = {
            'submitted': bt.Order.Submitted,
            'accepted': bt.Order.Accepted,
            'partial': bt.Order.Partial,
            'completed': bt.Order.Completed,
            'canceled': bt.Order.Canceled,
            'rejected': bt.Order.Rejected,
        }

        new_status = status_map.get(order_event.status)
        if new_status:
            if new_status == bt.Order.Partial:
                order.partial()
                order.execute(self.data.datetime[0],
                            order_event.filled_qty,
                            order_event.avg_price,
                            0,  # commission
                            False)
            elif new_status == bt.Order.Completed:
                order.completed()
            elif new_status == bt.Order.Canceled:
                order.cancel()
            elif new_status == bt.Order.Rejected:
                order.reject()

    def on_trade_event(self, trade_event):
        """
        处理成交事件

        Args:
            trade_event: 成交事件对象
                - exchange_id: 交易所订单ID
                - trade_id: 成交ID
                - price: 成交价格
                - qty: 成交数量
                - time: 成交时间
        """
        # 成交事件在订单事件中已处理
        pass
```

### 2. A股市场特性设计

#### 2.1 A股交易规则

```python
# backtrader/exchange/a_stock_rules.py
from datetime import time, datetime
from backtrader.utils.py3 import date2num

class AStockTradingRules:
    """
    A股交易规则

    特点:
    1. T+1交易: 当日买入次日才能卖出
    2. 涨跌停: 10%/20%涨跌停限制
    3. 最小单位: 100股整数倍
    4. 交易时间: 特定的交易时段
    """
    # 交易时间段
    TRADING_SESSIONS = [
        {'name': 'morning', 'start': time(9, 30), 'end': time(11, 30)},
        {'name': 'afternoon', 'start': time(13, 0), 'end': time(15, 0)},
    ]

    # 涨跌停限制
    LIMIT_UP = {
        'main': 0.10,      # 主板10%
        'small': 0.20,     # 创业板/科创板20%
        'st': 0.05,        # ST股票5%
    }

    LIMIT_DOWN = {
        'main': -0.10,
        'small': -0.20,
        'st': -0.05,
    }

    # 最小交易单位
    MIN_UNIT = 100  # 1手 = 100股

    # 费用
    COMMISSION_RATE = 0.0003    # 佣金率（双向）
    MIN_COMMISSION = 5.0        # 最低佣金
    STAMP_DUTY = 0.001          # 印花税（仅卖出）

    @classmethod
    def is_trading_time(cls, dt):
        """检查是否为交易时间"""
        t = dt.time()
        for session in cls.TRADING_SESSIONS:
            if session['start'] <= t <= session['end']:
                return True
        return False

    @classmethod
    def is_auction_time(cls, dt):
        """检查是否为集合竞价时间"""
        t = dt.time()
        return time(9, 15) <= t <= time(9, 25)

    @classmethod
    def adjust_quantity(cls, qty, is_close=False):
        """
        调整数量为100股整数倍

        Args:
            qty: 原始数量
            is_close: 是否为卖出（卖出可以非100倍）

        Returns:
            int: 调整后的数量
        """
        if is_close:
            # 卖出可以非100倍
            return qty
        # 买入必须100股整数倍
        return (qty // cls.MIN_UNIT) * cls.MIN_UNIT

    @classmethod
    def calculate_fee(cls, price, qty, is_buy=True):
        """
        计算交易费用

        Args:
            price: 成交价格
            qty: 成交数量
            is_buy: 是否为买入

        Returns:
            float: 总费用
        """
        amount = price * qty

        # 佣金
        commission = amount * cls.COMMISSION_RATE
        commission = max(commission, cls.MIN_COMMISSION)

        # 印花税（仅卖出）
        stamp_duty = 0 if is_buy else amount * cls.STAMP_DUTY

        # 过户费（仅上海）
        transfer_fee = amount * 0.00001

        return commission + stamp_duty + transfer_fee

    @classmethod
    def check_limit_price(cls, last_close, price, board_type='main'):
        """
        检查价格是否在涨跌停范围内

        Args:
            last_close: 昨收价
            price: 当前价格
            board_type: 板块类型

        Returns:
            bool: 是否在有效范围内
        """
        limit_up = last_close * (1 + cls.LIMIT_UP[board_type])
        limit_down = last_close * (1 + cls.LIMIT_DOWN[board_type])
        return limit_down <= price <= limit_up


class AStockPosition:
    """
    A股持仓管理，支持T+1规则
    """
    def __init__(self):
        self._holdings = {}  # {symbol: {'qty': int, 'today_buy': int}}
        self._lock = threading.Lock()

    def buy(self, symbol, qty):
        """买入"""
        with self._lock:
            if symbol not in self._holdings:
                self._holdings[symbol] = {'qty': 0, 'today_buy': 0}

            self._holdings[symbol]['qty'] += qty
            self._holdings[symbol]['today_buy'] += qty

    def sell(self, symbol, qty):
        """
        卖出（检查T+1规则）

        Returns:
            tuple: (可卖数量, 剩余委托数量)
        """
        with self._lock:
            if symbol not in self._holdings:
                return 0, qty

            position = self._holdings[symbol]
            # 可卖数量 = 总持仓 - 今日买入
            sellable = position['qty'] - position['today_buy']

            if sellable <= 0:
                return 0, qty

            actual_sell = min(sellable, qty)
            position['qty'] -= actual_sell

            return actual_sell, qty - actual_sell

    def on_settle(self):
        """结算时重置今日买入"""
        with self._lock:
            for position in self._holdings.values():
                position['today_buy'] = 0
```

#### 2.2 涨跌停检测

```python
# backtrader/exchange/limit_detector.py

class LimitDetector:
    """
    涨跌停检测器

    功能:
    1. 检测是否涨跌停
    2. 调整订单价格避免涨跌停
    3. 涨跌停时禁止交易
    """
    def __init__(self, board_type='main'):
        self.board_type = board_type
        self.last_close = None

    def update_close(self, close):
        """更新昨收价"""
        self.last_close = close

    def is_limit_up(self, price):
        """是否涨停"""
        if self.last_close is None:
            return False
        limit_price = self.last_close * (1 + AStockTradingRules.LIMIT_UP[self.board_type])
        return price >= limit_price * 0.9995  # 允许小误差

    def is_limit_down(self, price):
        """是否跌停"""
        if self.last_close is None:
            return False
        limit_price = self.last_close * (1 + AStockTradingRules.LIMIT_DOWN[self.board_type])
        return price <= limit_price * 1.0005

    def adjust_buy_price(self, price):
        """调整买入价格避免涨停"""
        if self.last_close is None:
            return price

        limit_up = self.last_close * (1 + AStockTradingRules.LIMIT_UP[self.board_type])
        return min(price, limit_up * 0.9995)

    def adjust_sell_price(self, price):
        """调整卖出价格避免跌停"""
        if self.last_close is None:
            return price

        limit_down = self.last_close * (1 + AStockTradingRules.LIMIT_DOWN[self.board_type])
        return max(price, limit_down * 1.0005)
```

### 3. Level2行情处理设计

#### 3.1 Level2数据结构

```python
# backtrader/exchange/level2_data.py
from collections import namedtuple
import threading

# Level2行情数据结构
Level2Quote = namedtuple('Level2Quote', [
    'symbol',           # 股票代码
    'data_time',        # 数据时间
    'last_price',       # 最新价
    'open_price',       # 开盘价
    'high_price',       # 最高价
    'low_price',        # 最低价
    'prev_close',       # 昨收价
    'volume',           # 成交量
    'amount',           # 成交额
    'bid_price',        # 买一到买五价 [p1, p2, p3, p4, p5]
    'bid_qty',          # 买一到买五量 [q1, q2, q3, q4, q5]
    'ask_price',        # 卖一到卖五价 [p1, p2, p3, p4, p5]
    'ask_qty',          # 卖一到卖五量 [q1, q2, q3, q4, q5]
])

# 逐笔成交数据
TradeTick = namedtuple('TradeTick', [
    'symbol',           # 股票代码
    'trade_time',       # 成交时间
    'price',            # 成交价格
    'qty',              # 成交数量
    'side',             # 方向 (B=买盘, S=卖盘, N=未知)
])

# 委托队列数据
OrderQueue = namedtuple('OrderQueue', [
    'symbol',           # 股票代码
    'price',            # 委托价格
    'qty',              # 委托数量
    'orders',           # 订单数
    'side',             # 方向 (B=买, S=卖)
])


class Level2DataFeed:
    """
    Level2数据源处理

    功能:
    1. 接收Level2行情数据
    2. 数据格式转换
    3. 数据缓存
    4. 提供Backtrader接口
    """
    def __init__(self):
        self._quotes = {}  # {symbol: Level2Quote}
        self._trades = []  # [TradeTick]
        self._queues = []  # [OrderQueue]
        self._lock = threading.Lock()
        self._subscribed = set()  # 已订阅标的

    def subscribe(self, symbol):
        """订阅行情"""
        self._subscribed.add(symbol)

    def unsubscribe(self, symbol):
        """取消订阅"""
        self._subscribed.discard(symbol)

    def on_quote(self, quote):
        """接收行情更新"""
        with self._lock:
            self._quotes[quote.symbol] = quote

    def on_trade(self, trade):
        """接收逐笔成交"""
        with self._lock:
            self._trades.append(trade)
            # 限制缓存大小
            if len(self._trades) > 10000:
                self._trades = self._trades[-5000:]

    def on_queue(self, queue):
        """接收委托队列"""
        with self._lock:
            self._queues.append(queue)
            if len(self._queues) > 10000:
                self._queues = self._queues[-5000:]

    def get_quote(self, symbol):
        """获取最新行情"""
        with self._lock:
            return self._quotes.get(symbol)

    def get_trades(self, symbol, since=None):
        """获取逐笔成交"""
        with self._lock:
            if since is None:
                return [t for t in self._trades if t.symbol == symbol]
            return [t for t in self._trades
                    if t.symbol == symbol and t.trade_time >= since]

    def get_order_book(self, symbol):
        """获取买卖盘口"""
        quote = self.get_quote(symbol)
        if not quote:
            return None

        return {
            'bids': [
                {'price': p, 'qty': q}
                for p, q in zip(quote.bid_price, quote.bid_qty)
                if p > 0
            ],
            'asks': [
                {'price': p, 'qty': q}
                for p, q in zip(quote.ask_price, quote.ask_qty)
                if p > 0
            ],
            'last_update': quote.data_time,
        }

    def get_spread(self, symbol):
        """获取买卖价差"""
        quote = self.get_quote(symbol)
        if not quote or not quote.bid_price[0] or not quote.ask_price[0]:
            return None

        return {
            'spread': quote.ask_price[0] - quote.bid_price[0],
            'spread_pct': (quote.ask_price[0] - quote.bid_price[0]) / quote.bid_price[0],
            'mid_price': (quote.ask_price[0] + quote.bid_price[0]) / 2,
        }
```

#### 3.2 Level2转K线

```python
# backtrader/exchange/level2_to_kline.py

class Level2ToKline:
    """
    Level2行情转K线

    功能:
    1. 将tick数据聚合成K线
    2. 支持多种周期
    3. 实时更新当前K线
    """
    def __init__(self, period=60):
        """
        Args:
            period: K线周期（秒）
        """
        self.period = period
        self._bars = {}  # {symbol: current_bar}
        self._history = {}  # {symbol: [completed_bars]}

    def on_tick(self, tick):
        """
        处理tick数据

        Args:
            tick: Level2Quote或TradeTick
        """
        symbol = tick.symbol
        price = getattr(tick, 'last_price', tick.price)
        volume = getattr(tick, 'volume', tick.qty)

        # 获取或创建当前K线
        if symbol not in self._bars:
            self._bars[symbol] = self._new_bar(tick)

        bar = self._bars[symbol]

        # 检查是否需要新建K线
        if self._should_new_bar(bar, tick):
            # 保存已完成K线
            if symbol not in self._history:
                self._history[symbol] = []
            self._history[symbol].append(bar)

            # 创建新K线
            self._bars[symbol] = self._new_bar(tick)
            bar = self._bars[symbol]

        # 更新当前K线
        bar['high'] = max(bar['high'], price)
        bar['low'] = min(bar['low'], price)
        bar['close'] = price
        bar['volume'] += volume
        bar['time'] = getattr(tick, 'data_time', tick.trade_time)

    def _new_bar(self, tick):
        """创建新K线"""
        price = getattr(tick, 'last_price', tick.price)
        time_val = getattr(tick, 'data_time', tick.trade_time)

        # 计算K线开始时间
        bar_time = self._align_time(time_val)

        return {
            'time': bar_time,
            'open': price,
            'high': price,
            'low': price,
            'close': price,
            'volume': 0,
        }

    def _align_time(self, time_val):
        """对齐时间到K线周期"""
        # 将时间戳对齐到周期边界
        timestamp = int(time_val.timestamp())
        return timestamp - (timestamp % self.period)

    def _should_new_bar(self, bar, tick):
        """检查是否需要新建K线"""
        tick_time = getattr(tick, 'data_time', tick.trade_time)
        bar_timestamp = bar['time']
        tick_timestamp = self._align_time(tick_time)
        return tick_timestamp > bar_timestamp

    def get_bar(self, symbol):
        """获取当前K线"""
        return self._bars.get(symbol)

    def get_history(self, symbol, count=100):
        """获取历史K线"""
        history = self._history.get(symbol, [])
        bars = history[-count:] if count else history.copy()

        # 添加当前K线
        current = self._bars.get(symbol)
        if current:
            bars.append(current)

        return bars
```

### 4. 事件驱动回调系统设计

```python
# backtrader/exchange/event_system.py
import threading
import queue
import logging
from typing import Callable, Dict, List
from enum import Enum

class EventType(Enum):
    """事件类型"""
    # 连接事件
    CONNECTED = 'connected'
    DISCONNECTED = 'disconnected'
    RECONNECTED = 'reconnected'

    # 订单事件
    ORDER_SUBMITTED = 'order_submitted'
    ORDER_ACCEPTED = 'order_accepted'
    ORDER_REJECTED = 'order_rejected'
    ORDER_PARTIAL = 'order_partial'
    ORDER_FILLED = 'order_filled'
    ORDER_CANCELED = 'order_canceled'

    # 成交事件
    TRADE = 'trade'

    # 持仓事件
    POSITION_UPDATE = 'position_update'

    # 资金事件
    ASSET_UPDATE = 'asset_update'

    # 错误事件
    ERROR = 'error'


class Event:
    """事件对象"""
    def __init__(self, event_type, data=None):
        self.event_type = event_type
        self.data = data or {}
        self.timestamp = time.time()


class EventEmitter:
    """事件发射器"""
    def __init__(self):
        self._listeners: Dict[EventType, List[Callable]] = {}
        self._lock = threading.Lock()

    def on(self, event_type: EventType, callback: Callable):
        """注册事件监听器"""
        with self._lock:
            if event_type not in self._listeners:
                self._listeners[event_type] = []
            self._listeners[event_type].append(callback)

    def off(self, event_type: EventType, callback: Callable):
        """移除事件监听器"""
        with self._lock:
            if event_type in self._listeners:
                try:
                    self._listeners[event_type].remove(callback)
                except ValueError:
                    pass

    def emit(self, event_type: EventType, data=None):
        """发射事件"""
        event = Event(event_type, data)

        with self._lock:
            listeners = self._listeners.get(event_type, []).copy()

        for callback in listeners:
            try:
                callback(event)
            except Exception as e:
                logging.error(f"事件处理错误: {e}")


class EventDispatcher:
    """
    事件分发器

    使用独立线程处理事件，避免阻塞主线程
    """
    def __init__(self, queue_size=10000):
        self._queue = queue.Queue(maxsize=queue_size)
        self._emitter = EventEmitter()
        self._running = False
        self._thread = None
        self._logger = logging.getLogger(__name__)

    def start(self):
        """启动事件处理线程"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止事件处理"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)

    def dispatch(self, event_type: EventType, data=None):
        """分发事件到队列"""
        try:
            self._queue.put_nowait((event_type, data))
        except queue.Full:
            self._logger.warning("事件队列已满，丢弃事件")

    def on(self, event_type: EventType, callback: Callable):
        """注册事件监听"""
        self._emitter.on(event_type, callback)

    def _process_loop(self):
        """事件处理循环"""
        while self._running:
            try:
                event_type, data = self._queue.get(timeout=1)
                self._emitter.emit(event_type, data)
            except queue.Empty:
                continue
            except Exception as e:
                self._logger.error(f"事件处理错误: {e}")
```

### 5. 使用示例

#### 5.1 基础使用

```python
import backtrader as bt
from backtrader.exchange.xtp import XTPStore

# 创建Store
store = XTPStore(
    server_ip='127.0.0.1',
    server_port=7709,
    username='your_username',
    password='your_password',
    client_id=1,
    account_id='your_account',
)

# 连接
store.connect()

# 创建Cerebro
cerebro = bt.Cerebro()

# 添加数据
data = store.getdata(
    symbol='600000.SH',
    timeframe=bt.TimeFrame.Minutes,
    live=True,
)
cerebro.adddata(data)

# 设置Broker
cerebro.setbroker(store.getbroker())

# 添加策略
cerebro.addstrategy(MyStrategy)

# 运行
cerebro.run()
```

#### 5.2 事件监听

```python
from backtrader.exchange.event_system import EventType

class MyStrategy(bt.Strategy):
    def __init__(self):
        # 注册事件监听
        self.store.broker.event_dispatcher.on(
            EventType.ORDER_FILLED,
            self._on_order_filled
        )
        self.store.broker.event_dispatcher.on(
            EventType.POSITION_UPDATE,
            self._on_position_update
        )

    def _on_order_filled(self, event):
        """订单成交通知"""
        print(f"订单成交: {event.data}")

    def _on_position_update(self, event):
        """持仓更新通知"""
        print(f"持仓更新: {event.data}")
```

#### 5.3 Level2行情

```python
from backtrader.exchange.level2_data import Level2DataFeed

class Level2Strategy(bt.Strategy):
    def __init__(self):
        self.level2 = Level2DataFeed()
        self.level2.subscribe(self.data._name)

    def next(self):
        # 获取五档行情
        order_book = self.level2.get_order_book(self.data._name)

        if order_book:
            best_bid = order_book['bids'][0]['price']
            best_ask = order_book['asks'][0]['price']
            spread = best_ask - best_bid

            # 根据价差决定交易
            if spread < self.p.max_spread:
                self.buy()
```

---

## 实施路线图

### 阶段1: 适配器基础架构 (2-3周)
- [ ] 实现ExchangeStore基类
- [ ] 实现ExchangeBroker基类
- [ ] 实现ExchangeData基类
- [ ] 实现单例模式和连接管理
- [ ] 单元测试

### 阶段2: A股特性支持 (2-3周)
- [ ] 实现AStockTradingRules
- [ ] 实现T+1持仓管理
- [ ] 实现涨跌停检测
- [ ] 实现费用计算
- [ ] 集成测试

### 阶段3: Level2行情 (2周)
- [ ] 实现Level2数据结构
- [ ] 实现Level2DataFeed
- [ ] 实现Level2ToKline转换
- [ ] 实现五档行情订阅
- [ ] 性能测试

### 阶段4: 事件系统 (1-2周)
- [ ] 实现EventEmitter
- [ ] 实现EventDispatcher
- [ ] 定义事件类型
- [ ] 集成到Broker

### 阶段5: XTP集成 (2-3周)
- [ ] 实现XTPStore
- [ ] 实现XTPBroker
- [ ] 实现XTPData
- [ ] 实现回调处理
- [ ] 端到端测试

### 阶段6: 优化和文档 (1-2周)
- [ ] 性能优化
- [ ] 低延迟优化
- [ ] 编写使用文档
- [ ] 编写API文档

---

## 附录: 关键文件路径

### Backtrader关键文件
- `cerebro.py`: 核心引擎
- `broker.py`: 经纪商基类
- `strategy.py`: 策略基类
- `feed.py`: 数据源基类

### XTP-Backtrader-API关键文件
- `xtp_backtrader_api/xtpstore.py`: Store主类（单例连接管理）
- `xtp_backtrader_api/xtpbroker.py`: Broker实现
- `xtp_backtrader_api/xtpdata.py`: DataFeed实现
- `xtp_backtrader_api/live_trader.py`: 实时交易器（回调处理）
