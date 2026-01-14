### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/poboquant
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### poboquant项目简介
poboquant是一个Python量化交易框架，具有以下核心特点：
- **多市场**: 支持多市场交易
- **实盘交易**: 支持实盘交易
- **策略模板**: 提供策略模板
- **数据管理**: 数据获取和管理
- **回测引擎**: 内置回测引擎
- **可视化**: 交易可视化功能

### 重点借鉴方向
1. **多市场**: 多市场支持架构
2. **实盘接口**: 实盘交易接口
3. **策略模板**: 策略模板设计
4. **数据管理**: 数据管理模块
5. **可视化**: 交易可视化
6. **API设计**: API接口设计

---

## 一、项目对比分析

### 1.1 架构设计对比

| 特性 | Backtrader | PoboQuant |
|------|-----------|-----------|
| **核心架构** | Line系统 + Cerebro引擎 | 事件驱动 + 回调函数 |
| **策略编写** | 类继承模式 | 函数回调模式 |
| **事件处理** | next()逐bar推进 | OnQuote/OnBar事件 |
| **多市场** | 通过DataFeed扩展 | 内置多交易所支持 |
| **实盘交易** | 需要第三方broker | 原生实盘接口 |
| **期权支持** | 基本支持 | 专门的期权策略支持 |
| **可视化** | matplotlib绘图 | Web UI可视化 |
| **主力合约** | 需手动管理 | GetMainContract自动切换 |

### 1.2 PoboQuant的核心优势

#### 1.2.1 事件驱动API设计

```python
# 初始化事件
def OnStart(context):
    g.code = GetMainContract('SHFE', 'rb', 20)
    SubscribeQuote(g.code)
    SubscribeBar(g.code, BarType.Day)

# 行情事件
def OnQuote(context, code):
    dyndata = GetQuote(code)
    # 处理实时行情

# K线事件
def OnBar(context, code, bartype):
    # 处理K线数据

# 订单变化事件
def OnOrderChange(context, AccountName, order):
    # 处理订单状态

# 账户断线事件
def OnTradeAccountDisconnected(context, accountname):
    # 处理断线重连
```

**优势**：
- 事件名称直观，易于理解
- 不同数据类型有专门的事件
- 支持断线重连等实盘场景

#### 1.2.2 主力合约自动切换

```python
# 获取主力合约
g.code = GetMainContract('SHFE', 'rb', 20)  # 交易所+品种+天数

# 自动检测合约切换并换月
if i.contract != g.code and GetVarietyByCode(g.code) == GetVarietyByCode(i.contract):
    # 平旧合约，开新合约
    context.myacc.InsertOrder(i.contract, BSType.SellClose, closeprice, volume)
    context.myacc.InsertOrder(g.code, BSType.BuyOpen, newprice, volume)
```

**优势**：
- 自动识别主力合约
- 支持换月逻辑
- 避免合约到期风险

#### 1.2.3 丰富的订单类型

```python
# 开仓
context.myacc.InsertOrder(code, BSType.BuyOpen, price, volume)
context.myacc.InsertOrder(code, BSType.SellOpen, price, volume)

# 平仓
context.myacc.InsertOrder(code, BSType.BuyClose, price, volume)
context.myacc.InsertOrder(code, BSType.SellClose, price, volume)

# 平今（期货专用）
context.myacc.InsertOrder(code, BSType.SellCloseToday, price, volume)

# 快速下单
QuickInsertOrder(account, code, 'buy', 'open', price, volume)

# 止损单
InsertAbsStopLossPosition(account, code, 'buy', stop_price, volume)
```

**优势**：
- 区分开平仓
- 支持平今优先
- 内置止损单

#### 1.2.4 指标计算系统

```python
# 创建指标
MACDindi = CreateIndicator("MACD")
param = {"SHORT": 12, "LONG": 26, "M": 9}
MACDindi.SetParameter(param)
MACDindi.Attach(g.code, BarType.Day)
MACDindi.Calc()

# 获取结果
diff = MACDindi.GetValue("DIF")
dea = MACDindi.GetValue("DEA")

# 支持的指标：MACD, KDJ, ATR, RSI, BOLL等
```

**优势**：
- 动态创建指标
- 参数灵活设置
- 结果直接返回数组

#### 1.2.5 市场初始化事件

```python
def OnMarketQuotationInitialEx(context, exchange, daynight):
    if exchange != 'DCE':
        return
    g.code = GetMainContract('DCE', 'j', 20)
    SubscribeBar(g.code, BarType.Min15)
    # 盘前持仓检查
```

**优势**：
- 区分交易所和日夜盘
- 盘前初始化机会
- 持仓状态检查

#### 1.2.6 定时器功能

```python
# 设置定时器
g.timer = SetTimer(60)  # 60秒

def OnTimer(context, timerid):
    if timerid == g.timer:
        # 定时任务
        KillTimer(g.timer)
```

**优势**：
- 支持定时任务
- 可用于重连等场景
- 灵活的时间控制

#### 1.2.7 丰富的策略示例

PoboQuant提供了大量实用的策略示例：
- 期权策略：波动率交易、对冲、希腊值计算
- 期货策略：跨期套利、价差交易、海龟策略
- 股票策略：日内交易、技术指标
- 风控策略：止损、资金管理

### 1.3 可借鉴的具体设计

#### 1.3.1 事件驱动架构

虽然Backtrader使用next()模式，但可以增加事件钩子：
- OnBar(): K线完成时触发
- OnQuote(): Tick数据到达时触发
- OnOrderChanged(): 订单状态变化
- OnAccountDisconnected(): 连接断开

#### 1.3.2 主力合约管理

- 自动主力合约检测
- 换月逻辑封装
- 合约到期提醒

#### 1.3.3 订单类型扩展

- BuyOpen/SellOpen/BuyClose/SellClose
- CloseToday优先
- 条件单/止损单

#### 1.3.4 快速下单接口

```python
# 简化的下单接口
QuickInsertOrder(account, code, direction, offset, price, volume)
```

#### 1.3.5 指标工厂模式

```python
# 动态创建指标
indicator = CreateIndicator("MACD", params={...})
```

---

## 二、需求文档

### 2.1 优化目标

借鉴PoboQuant的实用设计，增强Backtrader的实盘交易能力：

1. **事件钩子系统**: 增加更多事件触发点
2. **主力合约管理**: 自动检测和切换主力合约
3. **订单类型扩展**: 支持开平仓区分
4. **快速下单接口**: 简化下单操作
5. **断线重连**: 实盘连接稳定性
6. **定时器系统**: 支持定时任务

### 2.2 详细需求

#### 需求1: 事件钩子系统

**描述**: 在现有next()模式基础上，增加事件钩子

**功能点**:
- OnBar(): K线完成回调
- OnQuote(): Tick数据回调
- OnOrderChanged(): 订单状态变化
- OnPositionChanged(): 持仓变化
- OnTimer(): 定时器触发

**验收标准**:
- 提供EventsMixin类
- 支持多个事件订阅
- 不影响现有策略

#### 需求2: 主力合约管理器

**描述**: 自动检测和管理期货主力合约

**功能点**:
- 主力合约识别（成交量/持仓量）
- 合约切换检测
- 自动换月功能
- 合约到期提醒

**验收标准**:
- 提供MainContractManager类
- 支持多品种监控
- 自动换月或手动确认

#### 需求3: 扩展订单类型

**描述**: 支持期货开平仓区分

**功能点**:
- BuyOpen/SellOpen/BuyClose/SellClose订单
- CloseToday优先级
- 条件单（止损止盈）
- 冰山订单

**验收标准**:
- 新订单类型可用
- 与现有Broker兼容
- 支持回测和实盘

#### 需求4: 快速下单接口

**描述**: 简化的下单函数

**功能点**:
- quick_buy()/quick_sell()
- 市价单/限价单
- 批量下单
- 订单状态查询

**验收标准**:
- 一行代码完成下单
- 支持多种订单类型
- 错误处理完善

#### 需求5: 断线重连机制

**描述**: 实盘连接稳定性保障

**功能点**:
- 连接状态监控
- 自动重连
- 重连后状态恢复
- 重连通知

**验收标准**:
- 检测断线<5秒
- 自动重连成功率>95%
- 重连后持仓正确

#### 需求6: 定时器系统

**描述**: 策略内定时任务支持

**功能点**:
- 设置定时器
- 取消定时器
- 周期性任务
- 延迟任务

**验收标准**:
- 提供Timer管理器
- 定时精度±1秒
- 支持多定时器

---

## 三、设计文档

### 3.1 事件钩子系统设计

#### 3.1.1 EventsMixin类

```python
from typing import Callable, Dict, List
from enum import Enum

class EventType(Enum):
    """事件类型枚举"""
    ON_BAR = "on_bar"
    ON_QUOTE = "on_quote"
    ON_ORDER_CHANGED = "on_order_changed"
    ON_POSITION_CHANGED = "on_position_changed"
    ON_ACCOUNT_CHANGED = "on_account_changed"
    ON_TIMER = "on_timer"

class EventsMixin:
    """事件钩子混入类

    为策略添加事件订阅能力
    """

    def __init__(self):
        self._event_handlers: Dict[EventType, List[Callable]] = {}
        self._timers: Dict[int, Callable] = {}
        self._timer_counter = 0

    def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """订阅事件

        Args:
            event_type: 事件类型
            handler: 处理函数
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable) -> None:
        """取消订阅"""
        if event_type in self._event_handlers:
            self._event_handlers[event_type].remove(handler)

    def emit(self, event_type: EventType, *args, **kwargs) -> None:
        """触发事件"""
        if event_type in self._event_handlers:
            for handler in self._event_handlers[event_type]:
                try:
                    handler(*args, **kwargs)
                except Exception as e:
                    self._handle_event_error(event_type, e)

    def _handle_event_error(self, event_type: EventType, error: Exception) -> None:
        """处理事件错误"""
        # 默认只打印日志，不中断策略
        print(f"Event {event_type.value} error: {error}")

    # 便捷订阅方法
    def on_bar(self, handler: Callable) -> Callable:
        """K线完成装饰器"""
        self.subscribe(EventType.ON_BAR, handler)
        return handler

    def on_quote(self, handler: Callable) -> Callable:
        """Tick数据装饰器"""
        self.subscribe(EventType.ON_QUOTE, handler)
        return handler

    def on_order_changed(self, handler: Callable) -> Callable:
        """订单变化装饰器"""
        self.subscribe(EventType.ON_ORDER_CHANGED, handler)
        return handler

    def on_position_changed(self, handler: Callable) -> Callable:
        """持仓变化装饰器"""
        self.subscribe(EventType.ON_POSITION_CHANGED, handler)
        return handler

    def on_timer(self, interval: int) -> Callable:
        """定时器装饰器

        Args:
            interval: 间隔（秒）
        """
        def decorator(handler: Callable) -> Callable:
            timer_id = self.set_timer(interval, handler)
            return handler
        return decorator

    def set_timer(self, interval: int, handler: Callable) -> int:
        """设置定时器

        Args:
            interval: 间隔（秒）
            handler: 处理函数

        Returns:
            定时器ID
        """
        self._timer_counter += 1
        timer_id = self._timer_counter
        self._timers[timer_id] = {
            'handler': handler,
            'interval': interval,
            'next_run': None,
        }
        return timer_id

    def kill_timer(self, timer_id: int) -> None:
        """取消定时器"""
        if timer_id in self._timers:
            del self._timers[timer_id]

    def check_timers(self, current_time) -> None:
        """检查并触发定时器"""
        for timer_id, timer in self._timers.items():
            if timer['next_run'] is None:
                timer['next_run'] = current_time + timedelta(seconds=timer['interval'])
            elif current_time >= timer['next_run']:
                timer['handler']()
                timer['next_run'] = current_time + timedelta(seconds=timer['interval'])
```

#### 3.1.2 集成到Strategy

```python
class EventfulStrategy(bt.Strategy, EventsMixin):
    """支持事件钩子的策略基类"""

    def __init__(self):
        super().__init__()
        EventsMixin.__init__(self)

        # 内部注册Cerebro的事件
        self._register_internal_events()

    def _register_internal_events(self):
        """注册内部事件"""
        # 在next()后触发ON_BAR事件
        self._original_next = self.next

        def wrapped_next():
            self._original_next()
            self.emit(EventType.ON_BAR,
                     bar=len(self),
                     datetime=self.datetime.datetime(0),
                     data=self.data)

        self.next = wrapped_next

    def next(self):
        """策略主逻辑（子类覆盖）"""
        pass

# 使用示例
class MyStrategy(EventfulStrategy):
    def __init__(self):
        super().__init__()

        # 方式1: 装饰器订阅
        @self.on_bar
        def handle_bar(bar, datetime, data):
            print(f"Bar {bar} at {datetime}")

        # 方式2: 方法订阅
        self.subscribe(EventType.ON_BAR, self.my_bar_handler)

        # 设置定时器
        @self.on_timer(interval=60)
        def every_minute():
            print("Timer triggered")

    def my_bar_handler(self, bar, datetime, data):
        print(f"Alternative handler for bar {bar}")

    def next(self):
        # 正常策略逻辑
        if self.data.close[0] > self.data.close[-1]:
            self.buy()
```

### 3.2 主力合约管理器设计

#### 3.2.1 MainContractManager类

```python
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import requests

class MainContractManager:
    """主力合约管理器

    功能:
    - 获取主力合约
    - 监控合约切换
    - 自动换月
    """

    # 合约月份映射
    MONTH_MAP = {
        '01': 'F', '02': 'G', '03': 'H', '04': 'J', '05': 'K',
        '06': 'M', '07': 'N', '08': 'Q', '09': 'U', '10': 'V',
        '11': 'X', '12': 'Z',
    }

    def __init__(self):
        self._contracts: Dict[str, str] = {}  # 品种 -> 主力合约
        self._switch_threshold = 20  # 切换阈值（天）
        self._expiry_warning = 30  # 到期提醒（天）

    def get_main_contract(
        self,
        exchange: str,
        variety: str,
        lookback_days: int = 20
    ) -> Optional[str]:
        """获取主力合约

        Args:
            exchange: 交易所代码（SHFE, DCE, CZCE, CFFEX）
            variety: 品种代码（rb, j, TA等）
            lookback_days: 回溯天数

        Returns:
            主力合约代码，如 "rb2405"
        """
        key = f"{exchange}.{variety}"

        # 从缓存获取
        if key in self._contracts:
            return self._contracts[key]

        # 计算主力合约
        current_date = datetime.now()
        main_contract = None
        max_volume = 0
        max_oi = 0

        # 遍历可能的合约（未来12个月）
        for month_delta in range(12):
            target_date = current_date + timedelta(days=30 * month_delta)

            # 构造合约代码
            if exchange == 'CZCE':
                # 郑商所合约: TA305, MA405 等
                year = target_date.year % 100
                month = target_date.month
                code = f"{variety}{year}{month:02d}"
            elif exchange == 'SHFE' or exchange == 'DCE':
                # 上期所/大商所: rb2405, j2405 等
                year = target_date.year % 100
                month = target_date.month
                code = f"{variety}{year}{month:02d}"
            else:
                continue

            # 查询合约数据
            volume, oi = self._get_contract_volume_oi(exchange, code)

            # 判断主力合约
            if volume > max_volume or (volume == max_volume and oi > max_oi):
                max_volume = volume
                max_oi = oi
                main_contract = code

        if main_contract:
            self._contracts[key] = main_contract

        return main_contract

    def _get_contract_volume_oi(self, exchange: str, code: str) -> Tuple[int, int]:
        """获取合约成交量和持仓量

        实际实现需要连接数据源
        """
        # 这里返回模拟数据，实际需要从交易所或数据源获取
        return 0, 0

    def detect_switch(
        self,
        exchange: str,
        variety: str,
        current_contract: str
    ) -> Optional[str]:
        """检测是否需要切换主力合约

        Args:
            exchange: 交易所
            variety: 品种
            current_contract: 当前合约

        Returns:
            新的主力合约，不需要切换返回None
        """
        new_contract = self.get_main_contract(exchange, variety)

        if new_contract and new_contract != current_contract:
            return new_contract

        return None

    def get_expiry_date(self, contract: str) -> Optional[datetime]:
        """获取合约到期日

        Args:
            contract: 合约代码

        Returns:
            到期日期
        """
        # 从合约代码解析月份
        # 示例: rb2405 -> 2024年5月
        if len(contract) >= 4:
            year_suffix = contract[-4:-2]
            month = contract[-2:]

            try:
                year = 2000 + int(year_suffix)
                # 期货合约通常在月中交割
                expiry_date = datetime(year, int(month), 15)
                return expiry_date
            except (ValueError, IndexError):
                pass

        return None

    def check_expiry_warning(self, contract: str) -> Optional[int]:
        """检查合约是否接近到期

        Args:
            contract: 合约代码

        Returns:
            距离到期的天数，None表示无法判断
        """
        expiry = self.get_expiry_date(contract)
        if expiry:
            days_left = (expiry - datetime.now()).days
            if days_left <= self._expiry_warning:
                return days_left
        return None

    def switch_contract(
        self,
        old_contract: str,
        new_contract: str,
        position: int,
        price: float,
        broker
    ) -> bool:
        """执行换月操作

        Args:
            old_contract: 旧合约
            new_contract: 新合约
            position: 持仓数量
            price: 当前价格
            broker:经纪商对象

        Returns:
            是否成功
        """
        try:
            # 平旧合约
            if position > 0:
                broker.close(old_contract, size=position, price=price)
            else:
                broker.close(old_contract, size=-position, price=price)

            # 开新合约
            if position > 0:
                broker.buy(new_contract, size=position, price=price)
            else:
                broker.sell(new_contract, size=-position, price=price)

            return True
        except Exception as e:
            print(f"Contract switch failed: {e}")
            return False
```

#### 3.2.2 集成到Strategy

```python
class MainContractStrategy(bt.Strategy):
    """支持主力合约管理的策略"""

    params = (
        ('variety', 'rb'),
        ('exchange', 'SHFE'),
        ('auto_switch', True),
        ('switch_check_days', 5),
    )

    def __init__(self):
        super().__init__()
        self.contract_mgr = MainContractManager()
        self._last_switch_check = None

    def next(self):
        current_date = self.datetime.datetime(0)

        # 定期检查是否需要换月
        if self._should_check_switch(current_date):
            self._check_and_switch_contract()

        # 正常策略逻辑
        self.run_strategy()

    def _should_check_switch(self, current_date) -> bool:
        """判断是否应该检查换月"""
        if self._last_switch_check is None:
            return True

        days_since_check = (current_date - self._last_switch_check).days
        return days_since_check >= self.p.switch_check_days

    def _check_and_switch_contract(self):
        """检查并执行换月"""
        # 获取当前主力合约
        current_main = self.contract_mgr.get_main_contract(
            self.p.exchange,
            self.p.variety
        )

        if not current_main:
            return

        # 检查是否需要切换
        new_contract = self.contract_mgr.detect_switch(
            self.p.exchange,
            self.p.variety,
            current_main
        )

        if new_contract and self.p.auto_switch:
            # 执行换月
            position = self.getposition(self.data).size
            if position != 0:
                self.contract_mgr.switch_contract(
                    current_main,
                    new_contract,
                    position,
                    self.data.close[0],
                    self.broker
                )

        # 检查到期提醒
        days_left = self.contract_mgr.check_expiry_warning(current_main)
        if days_left is not None:
            print(f"Warning: Contract {current_main} expires in {days_left} days")

        self._last_switch_check = self.datetime.datetime(0)
```

### 3.3 订单类型扩展设计

#### 3.3.1 订单类型枚举

```python
from enum import Enum

class OrderType(Enum):
    """扩展的订单类型"""
    # 原有类型
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"

    # 新增期货专用类型
    BUY_OPEN = "buy_open"          # 买入开仓
    SELL_OPEN = "sell_open"        # 卖出开仓
    BUY_CLOSE = "buy_close"        # 买入平仓
    SELL_CLOSE = "sell_close"      # 卖出平仓
    BUY_CLOSE_TODAY = "buy_close_today"    # 平今买入
    SELL_CLOSE_TODAY = "sell_close_today"  # 平今卖出

class ConditionOrder:
    """条件订单

    满足特定条件时触发
    """

    def __init__(
        self,
        order_type: OrderType,
        condition: Callable[['ConditionOrder'], bool],
        size: float,
        price: Optional[float] = None,
    ):
        self.order_type = order_type
        self.condition = condition
        self.size = size
        self.price = price
        self.is_active = True
        self.created_at = None

    def check(self) -> bool:
        """检查条件是否满足"""
        if not self.is_active:
            return False
        return self.condition(self)

    def activate(self):
        """激活订单"""
        self.is_active = True

    def deactivate(self):
        """停用订单"""
        self.is_active = False
```

#### 3.3.2 扩展Broker接口

```python
class FuturesBroker(bt.Broker):
    """支持期货订单类型的经纪商"""

    def buy_open(
        self,
        data,
        size: float,
        price: Optional[float] = None,
        exectype=None,
    ) -> bt.Order:
        """买入开仓"""
        return self.buy(
            data=data,
            size=size,
            price=price,
            exectype=exectype,
            **{'ordertype': OrderType.BUY_OPEN}
        )

    def sell_open(
        self,
        data,
        size: float,
        price: Optional[float] = None,
        exectype=None,
    ) -> bt.Order:
        """卖出开仓"""
        return self.sell(
            data=data,
            size=size,
            price=price,
            exectype=exectype,
            **{'ordertype': OrderType.SELL_OPEN}
        )

    def buy_close(
        self,
        data,
        size: float,
        price: Optional[float] = None,
        exectype=None,
        close_today: bool = False,
    ) -> bt.Order:
        """买入平仓"""
        ordertype = OrderType.BUY_CLOSE_TODAY if close_today else OrderType.BUY_CLOSE
        return self.buy(
            data=data,
            size=size,
            price=price,
            exectype=exectype,
            **{'ordertype': ordertype}
        )

    def sell_close(
        self,
        data,
        size: float,
        price: Optional[float] = None,
        exectype=None,
        close_today: bool = False,
    ) -> bt.Order:
        """卖出平仓"""
        ordertype = OrderType.SELL_CLOSE_TODAY if close_today else OrderType.SELL_CLOSE
        return self.sell(
            data=data,
            size=size,
            price=price,
            exectype=exectype,
            **{'ordertype': ordertype}
        )

    def set_stop_loss(
        self,
        position: bt.Position,
        stop_price: float,
        size: Optional[float] = None,
    ) -> bt.Order:
        """设置止损单

        Args:
            position: 持仓对象
            stop_price: 止损价格
            size: 平仓数量，默认为全部持仓

        Returns:
            止损订单
        """
        if size is None:
            size = abs(position.size)

        # 创建条件订单
        def stop_condition(order):
            current_price = self.getposition(position.data).price
            if position.size > 0:  # 多头止损
                return current_price <= stop_price
            else:  # 空头止损
                return current_price >= stop_price

        stop_order = ConditionOrder(
            order_type=OrderType.STOP,
            condition=stop_condition,
            size=size,
            price=stop_price,
        )

        self._condition_orders.append(stop_order)
        return stop_order

    def set_take_profit(
        self,
        position: bt.Position,
        target_price: float,
        size: Optional[float] = None,
    ) -> bt.Order:
        """设置止盈单"""
        if size is None:
            size = abs(position.size)

        def tp_condition(order):
            current_price = self.getposition(position.data).price
            if position.size > 0:  # 多头止盈
                return current_price >= target_price
            else:  # 空头止盈
                return current_price <= target_price

        tp_order = ConditionOrder(
            order_type=OrderType.LIMIT,
            condition=tp_condition,
            size=size,
            price=target_price,
        )

        self._condition_orders.append(tp_order)
        return tp_order
```

### 3.4 快速下单接口设计

```python
class QuickOrder:
    """快速下单工具类"""

    def __init__(self, strategy: bt.Strategy):
        self.strategy = strategy

    def buy(
        self,
        data=None,
        size: float = 1,
        price: Optional[float] = None,
        market: bool = False,
    ) -> bt.Order:
        """快速买入

        Args:
            data: 数据源，默认使用第一个
            size: 数量
            price: 价格，None表示市价
            market: 是否市价单

        Returns:
            订单对象
        """
        if data is None:
            data = self.strategy.data

        if market or price is None:
            return self.strategy.buy(data, size, exectype=bt.Order.Market)
        else:
            return self.strategy.buy(data, size, price=price, exectype=bt.Order.Limit)

    def sell(
        self,
        data=None,
        size: float = 1,
        price: Optional[float] = None,
        market: bool = False,
    ) -> bt.Order:
        """快速卖出"""
        if data is None:
            data = self.strategy.data

        if market or price is None:
            return self.strategy.sell(data, size, exectype=bt.Order.Market)
        else:
            return self.strategy.sell(data, size, price=price, exectype=bt.Order.Limit)

    def close(
        self,
        data=None,
        size: Optional[float] = None,
        price: Optional[float] = None,
        market: bool = True,
    ) -> bt.Order:
        """快速平仓

        Args:
            data: 数据源
            size: 平仓数量，None表示全部
            price: 价格
            market: 是否市价单

        Returns:
            订单对象
        """
        if data is None:
            data = self.strategy.data

        position = self.strategy.getposition(data)
        if size is None:
            size = position.size

        if size == 0:
            return None

        if size > 0:
            return self.sell(data, size=abs(size), price=price, market=market)
        else:
            return self.buy(data, size=abs(size), price=price, market=market)

    # 期货专用
    def buy_open(
        self,
        data=None,
        size: float = 1,
        price: Optional[float] = None,
    ) -> bt.Order:
        """买入开仓"""
        if isinstance(self.strategy.broker, FuturesBroker):
            return self.strategy.broker.buy_open(
                data or self.strategy.data,
                size,
                price,
            )
        else:
            return self.buy(data or self.strategy.data, size, price)

    def sell_close(
        self,
        data=None,
        size: Optional[float] = None,
        price: Optional[float] = None,
        close_today: bool = False,
    ) -> bt.Order:
        """卖出平仓"""
        if data is None:
            data = self.strategy.data

        position = self.strategy.getposition(data)
        if size is None:
            size = position.size

        if isinstance(self.strategy.broker, FuturesBroker):
            return self.strategy.broker.sell_close(
                data, size, price, close_today
            )
        else:
            return self.sell(data, size, price)

class QuickOrderStrategy(bt.Strategy):
    """支持快速下单的策略基类"""

    def __init__(self):
        super().__init__()
        self.order = QuickOrder(self)

# 使用示例
class MyStrategy(QuickOrderStrategy):
    def next(self):
        # 简洁的下单语法
        if self.data.close[0] > self.data.close[-1]:
            self.order.buy(size=100, market=True)  # 市价买入100股

        # 平仓
        if self.getposition().size > 0:
            self.order.close()  # 全部平仓

        # 期货操作
        if hasattr(self, 'order'):
            self.order.buy_open(size=10)  # 开多10手
```

### 3.5 断线重连机制设计

```python
import threading
import time
from datetime import datetime
from typing import Callable, Optional

class ConnectionMonitor:
    """连接监控器

    监控实盘连接状态，自动重连
    """

    def __init__(
        self,
        check_interval: int = 5,
        max_retries: int = 3,
        retry_delay: int = 10,
    ):
        """初始化监控器

        Args:
            check_interval: 检查间隔（秒）
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）
        """
        self._check_interval = check_interval
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._is_connected = True
        self._last_check = None
        self._reconnect_callbacks: List[Callable] = []
        self._disconnect_callbacks: List[Callable] = []

    def on_reconnect(self, callback: Callable) -> None:
        """注册重连回调"""
        self._reconnect_callbacks.append(callback)

    def on_disconnect(self, callback: Callable) -> None:
        """注册断线回调"""
        self._disconnect_callbacks.append(callback)

    def check_connection(self) -> bool:
        """检查连接状态"""
        # 实际实现需要根据具体broker API
        # 这里只是示例
        return self._is_connected

    def _trigger_disconnect(self):
        """触发断线事件"""
        for callback in self._disconnect_callbacks:
            try:
                callback()
            except Exception as e:
                print(f"Disconnect callback error: {e}")

    def _trigger_reconnect(self):
        """触发重连事件"""
        for callback in self._reconnect_callbacks:
            try:
                callback()
            except Exception as e:
                print(f"Reconnect callback error: {e}")

    def reconnect(self) -> bool:
        """执行重连"""
        retry_count = 0

        while retry_count < self._max_retries:
            try:
                # 尝试重连
                time.sleep(self._retry_delay)
                # 实际重连逻辑
                self._is_connected = True
                self._trigger_reconnect()
                return True
            except Exception as e:
                retry_count += 1
                print(f"Reconnect failed (attempt {retry_count}/{self._max_retries}): {e}")

        return False

class ReconnectableStrategy(bt.Strategy):
    """支持断线重连的策略基类"""

    params = (
        ('enable_reconnect', True),
        ('reconnect_check_interval', 5),
    )

    def __init__(self):
        super().__init__()
        self.connection_monitor = ConnectionMonitor(
            check_interval=self.p.reconnect_check_interval
        )

        # 注册回调
        self.connection_monitor.on_disconnect(self._on_disconnect)
        self.connection_monitor.on_reconnect(self._on_reconnect)

    def _on_disconnect(self):
        """断线回调"""
        print(f"[{datetime.now()}] Connection lost!")
        # 可以添加通知逻辑

    def _on_reconnect(self):
        """重连回调"""
        print(f"[{datetime.now()}] Reconnected successfully")
        # 恢复状态
        self._restore_state()

    def _restore_state(self):
        """恢复策略状态"""
        # 重新订阅数据
        # 恢复持仓信息
        # 重新设置条件单
        pass

    def next(self):
        # 检查连接状态
        if self.p.enable_reconnect:
            if not self.connection_monitor.check_connection():
                self.connection_monitor.reconnect()

        # 正常策略逻辑
        self.run_strategy()

    def run_strategy(self):
        """策略主逻辑（子类覆盖）"""
        pass
```

### 3.6 实现优先级

| 优先级 | 功能 | 复杂度 | 收益 |
|--------|------|--------|------|
| P0 | 快速下单接口 | 低 | 高 |
| P0 | 事件钩子系统 | 中 | 高 |
| P1 | 订单类型扩展 | 中 | 中 |
| P1 | 主力合约管理器 | 高 | 中 |
| P2 | 断线重连机制 | 高 | 中 |
| P2 | 定时器系统 | 低 | 低 |

### 3.7 兼容性保证

所有新功能通过以下方式保证兼容性：
1. 新增Mixin类不修改Strategy基类
2. 通过继承选择性启用新功能
3. 默认行为完全保持不变
4. 提供传统API的封装方法

---

## 四、使用示例

### 4.1 完整策略示例

```python
import backtrader as bt
from backtrader.extensions import (
    EventfulStrategy,
    MainContractManager,
    FuturesBroker,
    QuickOrder,
)

class MyFutureStrategy(EventfulStrategy, QuickOrderStrategy):
    """完整的期货策略示例

    结合了事件钩子、主力合约管理、快速下单等功能
    """

    params = (
        'variety', 'rb'
        'exchange', 'SHSE'
        'period', 20
    )

    def __init__(self):
        # 初始化基类
        EventfulStrategy.__init__(self)
        QuickOrderStrategy.__init__(self)

        # 主力合约管理器
        self.contract_mgr = MainContractManager()

        # 订阅事件
        @self.on_bar
        def log_bar(bar, dt, data):
            print(f"Bar {bar}: Close={data.close[0]:.2f}")

        @self.on_order_changed
        def log_order(order):
            print(f"Order {order.ref}: Status={order.getstatusname()}")

        # 设置定时器：每小时检查一次
        @self.on_timer(interval=3600)
        def hourly_check():
            self._check_contract_switch()

        # 指标
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)

    def next(self):
        # 检查定时器
        self.check_timers(self.datetime.datetime(0))

        # 策略逻辑
        if not self.position:
            if self.data.close[0] > self.sma[0]:
                # 使用快速下单接口
                self.order.buy_open(size=10)
        else:
            if self.data.close[0] < self.sma[0]:
                self.order.sell_close()  # 自动平仓

# 运行
cerebro = bt.Cerebro()

# 使用期货经纪商
cerebro.setbroker(FuturesBroker())

# 添加策略
cerebro.addstrategy(
    MyFutureStrategy,
    variety='rb',
    exchange='SHSE',
)

# 运行
result = cerebro.run()
```

### 4.2 简化的策略编写

```python
# 使用事件钩子，策略代码更清晰
class SimpleEventStrategy(EventfulStrategy):

    def __init__(self):
        super().__init__()

        # 所有逻辑通过事件处理
        @self.on_bar
        def handle_bar(bar, dt, data):
            if data.close[0] > data.close[-1]:
                self.order.buy()
            elif data.close[0] < data.close[-1]:
                self.order.close()

    def next(self):
        pass  # 不需要next，逻辑都在事件中
```

---

## 五、总结

通过借鉴PoboQuant的实用设计，Backtrader可以获得：

1. **更灵活的事件模型**: 事件钩子系统补充next()模式
2. **更好的实盘支持**: 断线重连、主力合约管理
3. **更简洁的API**: 快速下单接口减少样板代码
4. **更强的期货支持**: 开平仓区分、换月逻辑
5. **更丰富的功能**: 定时器、条件单、订单管理

这些改进使Backtrader在保持核心优势的同时，获得更适合实盘交易的能力。
