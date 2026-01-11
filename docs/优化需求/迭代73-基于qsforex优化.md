### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/qsforex
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### qsforex项目简介
qsforex是一个专注于外汇市场的事件驱动回测和交易框架，具有以下核心特点：
- **外汇专注**: 专门针对外汇市场设计
- **事件驱动**: 完整的事件驱动架构
- **投资组合**: Portfolio投资组合管理
- **头寸管理**: 精细的Position头寸管理
- **OANDA集成**: 与OANDA API集成实盘交易
- **Decimal精度**: 使用Decimal确保计算精度

### 重点借鉴方向
1. **事件架构**: 事件驱动架构设计（TickEvent、SignalEvent、OrderEvent）
2. **头寸管理**: 精细的Position头寸管理（Pips计算、盈亏计算）
3. **投资组合**: Portfolio组合管理（杠杆、保证金、风险控制）
4. **外汇特性**: 货币对处理、基础货币转换、点值计算
5. **执行模块**: ExecutionHandler执行处理抽象
6. **风险控制**: 基于风险比例的头寸计算

---

## 一、项目对比分析

### 1.1 qsforex 核心特性

| 特性 | 描述 |
|------|------|
| **事件系统** | TickEvent/SignalEvent/OrderEvent 三种事件类型 |
| **Position 类** | 精细的头寸管理（Pips、盈亏、平均价） |
| **Portfolio 类** | 组合管理（杠杆、保证金、风险比例） |
| **Backtest 类** | 事件驱动回测引擎 |
| **Strategy 类** | 策略基类（信号生成） |
| **Decimal 精度** | 使用 Decimal 确保金融计算精度 |
| **货币对处理** | 自动处理基础/报价货币转换 |

### 1.2 backtrader 现有能力对比

| 能力 | backtrader | qsforex | 差距 |
|------|-----------|---------|------|
| **事件驱动** | 核心架构 | 核心架构 | 相当 |
| **外汇支持** | 通用市场 | 专门优化外汇 | qsforex 更专业 |
| **头寸管理** | 内置但分散 | 专门的 Position 类 | qsforex 更精细 |
| **精度控制** | float | Decimal | qsforex 更精确 |
| **杠杆管理** | 通过 broker | Portfolio 层面 | qsforex 更直观 |
| **风险控制** | sizer | risk_per_trade | qsforex 更简洁 |

### 1.3 差距分析

| 方面 | qsforex | backtrader | 差距 |
|------|---------|-----------|------|
| **Pips计算** | 内置 `calculate_pips()` | 需自己实现 | backtrader 可添加 |
| **货币对转换** | 自动处理基础货币 | 无 | backtrader 可借鉴 |
| **头寸盈亏** | Position 实时计算 | Broker 中计算 | qsforex 更透明 |
| **风险头寸** | `calc_risk_position_size()` | Sizer 系统 | 各有优势 |
| **事件类型** | 明确的三种事件 | 内部事件系统 | backtrader 更复杂 |

---

## 二、需求规格文档

### 2.1 功能需求

#### FR1: 增强的外汇头寸管理
专为外汇市场优化的头寸管理：

- **FR1.1**: ForexPosition - 外汇头寸类
- **FR1.2**: `calculate_pips()` - 点值计算
- **FR1.3**: 货币对基础/报价货币自动识别
- **FR1.4**: 交叉汇率自动转换

#### FR2: 事件驱动增强
更清晰的事件类型定义：

- **FR2.1**: TickEvent - 市场报价事件
- **FR2.2**: SignalEvent - 交易信号事件
- **FR2.3**: OrderEvent - 订单执行事件
- **FR2.4**: 事件队列管理

#### FR3: 外汇专用工具
外汇市场专用计算工具：

- **FR3.1**: PipsCalculator - 点值计算器
- **FR3.2**: CurrencyPair - 货币对处理
- **FR3.3**: CrossRate - 交叉汇率计算
- **FR3.4**: MarginCalculator - 保证金计算

#### FR4: 精度控制
金融级精度控制：

- **FR4.1**: Decimal 支持
- **FR4.2**: 舍入模式控制
- **FR4.3**: 精度友好的运算

### 2.2 非功能需求

- **NFR1**: 性能 - 不影响回测速度
- **NFR2**: 兼容性 - 与现有 backtrader API 兼容
- **NFR3**: 精度 - 金融级计算精度
- **NFR4**: 可选性 - 所有新功能为可选

### 2.3 用户故事

| ID | 故事描述 | 优先级 |
|----|---------|--------|
| US1 | 作为外汇交易员，我想使用Pips计算功能，便于量化交易盈亏 | P0 |
| US2 | 作为多币种交易者，我希望自动处理货币对转换，避免手动计算 | P0 |
| US3 | 作为风控经理，我想使用精确的Decimal计算，避免浮点误差 | P1 |
| US4 | 作为策略开发者，我想使用清晰的事件系统，便于理解交易流程 | P1 |

---

## 三、设计文档

### 3.1 模块结构设计

```
backtrader/
├── forex/                  # 新增外汇模块
│   ├── __init__.py
│   ├── position.py          # ForexPosition 类
│   ├── pips.py              # Pips 计算工具
│   ├── currency.py          # 货币对处理
│   ├── margin.py            # 保证金计算
│   └── events.py            # 外汇事件定义
├── utils/
│   ├── decimal.py           # Decimal 工具
│   └── precision.py         # 精度控制
└── position/
    └── forex.py             # 外汇头寸管理
```

### 3.2 核心类设计

#### 3.2.1 ForexPosition 类

```python
"""
Forex Position for backtrader
参考：qsforex/portfolio/position.py
"""
from decimal import Decimal, getcontext, ROUND_HALF_DOWN
import backtrader as bt


class CurrencyPair:
    """
    货币对工具类

    自动处理基础货币/报价货币的识别和转换
    """

    def __init__(self, pair):
        """
        Args:
            pair: 货币对字符串，如 'EURUSD'
        """
        self.pair = pair.replace('/', '').upper()
        if len(self.pair) != 6:
            raise ValueError(f"Invalid currency pair: {pair}")
        self.base_currency = self.pair[:3]     # EUR
        self.quote_currency = self.pair[3:]    # USD

    def __repr__(self):
        return f"{self.base_currency}/{self.quote_currency}"

    def is_inverse(self, home_currency):
        """检查是否需要反向汇率"""
        return self.quote_currency == home_currency

    def get_cross_pair(self, home_currency):
        """获取交叉汇率货币对"""
        if self.quote_currency == home_currency:
            return None  # 不需要转换
        return f"{self.quote_currency}{home_currency}"


class ForexPosition:
    """
    外汇头寸类

    参考 qsforex Position 设计，提供精细的外汇头寸管理
    """

    def __init__(self, data, home_currency='USD', leverage=1.0):
        """
        Args:
            data: backtrader 数据源
            home_currency: 账户基础货币
            leverage: 杠杆倍数
        """
        self.data = data
        self._name = data._name if hasattr(data, '_name') else 'UNKNOWN'
        self.home_currency = home_currency
        self.leverage = leverage

        # 解析货币对
        self.currency_pair = CurrencyPair(self._name)

        # 头寸信息
        self.size = 0  # 持仓数量（正数为多头，负数为空头）
        self.avg_price = Decimal('0')  # 平均开仓价
        self.cur_price = Decimal('0')  # 当前价格

        # 盈亏信息
        self.profit_base = Decimal('0')  # 基础货币盈亏
        self.profit_pips = Decimal('0')  # 点值盈亏
        self.profit_perc = Decimal('0')  # 百分比盈亏

        # 初始化价格
        self._update_current_price()

    def _update_current_price(self):
        """更新当前价格"""
        if hasattr(self.data, 'bid') and hasattr(self.data, 'ask'):
            # 对于外汇，通常使用中间价
            self.cur_price = Decimal(str((self.data.bid[0] + self.data.ask[0]) / 2))

    def calculate_pips(self):
        """
        计算点值

        参考 qsforex 的 calculate_pips 实现
        """
        if self.size == 0:
            return Decimal('0')

        mult = Decimal('1') if self.size > 0 else Decimal('-1')
        price_diff = self.cur_price - self.avg_price

        # 大多数货币对小数点后4位为1点（JPY货币对为2位）
        pip_location = Decimal('0.0001')
        if 'JPY' in self._name:
            pip_location = Decimal('0.01')

        pips = (mult * price_diff / pip_location).quantize(
            Decimal('0.01'), ROUND_HALF_DOWN
        )
        return pips

    def calculate_profit_base(self, cross_rates=None):
        """
        计算基础货币盈亏

        Args:
            cross_rates: 交叉汇率字典 {pair: rate}
        """
        if self.size == 0:
            return Decimal('0')

        pips = self.calculate_pips()

        # 计算每个点的价值
        pip_value = self._get_pip_value(cross_rates)

        # 盈亏 = 点数 * 点值 * 手数
        profit = pips * pip_value * abs(Decimal(str(self.size)))
        return profit.quantize(Decimal('0.01'), ROUND_HALF_DOWN)

    def _get_pip_value(self, cross_rates=None):
        """
        获取每个点的价值（以账户基础货币计）

        Args:
            cross_rates: 交叉汇率字典
        """
        cross_rates = cross_rates or {}

        # 如果报价货币就是基础货币
        if self.currency_pair.quote_currency == self.home_currency:
            return Decimal('1')

        # 需要交叉汇率转换
        cross_pair = self.currency_pair.get_cross_pair(self.home_currency)
        if cross_pair and cross_pair in cross_rates:
            return Decimal(str(cross_rates[cross_pair]))

        # 默认返回1（实际使用中需要提供汇率）
        return Decimal('1')

    def calculate_profit_perc(self):
        """计算盈亏百分比"""
        if self.size == 0 or self.avg_price == 0:
            return Decimal('0')

        return (self.profit_base / (abs(Decimal(str(self.size))) * self.avg_price) * Decimal('100')).quantize(
            Decimal('0.01'), ROUND_HALF_DOWN
        )

    def update_position(self):
        """更新头寸价格和盈亏"""
        self._update_current_price()
        self.profit_pips = self.calculate_pips()
        self.profit_base = self.calculate_profit_base()
        self.profit_perc = self.calculate_profit_perc()

    def open_position(self, size, price=None):
        """
        开仓

        Args:
            size: 开仓数量（正数为多头，负数为空头）
            price: 开仓价格（None则使用当前价格）
        """
        if price is None:
            price = self.cur_price
        else:
            price = Decimal(str(price))

        if self.size == 0:
            # 新开仓
            self.size = size
            self.avg_price = price
        elif (self.size > 0 and size > 0) or (self.size < 0 and size < 0):
            # 加仓
            total_cost = self.avg_price * self.size + price * size
            self.size += size
            self.avg_price = total_cost / self.size
        else:
            # 对冲（简化处理：反向开仓视为平仓）
            self.close_position(abs(size), price)
            if abs(size) > abs(self.size + size):
                # 反向开仓量大于原有持仓，剩余部分开新仓
                remaining = size + self.size
                self.size = remaining
                self.avg_price = price

        self.update_position()

    def close_position(self, size=None, price=None):
        """
        平仓

        Args:
            size: 平仓数量（None则全部平仓）
            price: 平仓价格

        Returns:
            Decimal: 平仓盈亏
        """
        if size is None:
            size = abs(self.size)
        else:
            size = Decimal(str(size))

        if price is None:
            price = self.cur_price
        else:
            price = Decimal(str(price))

        if self.size == 0:
            return Decimal('0')

        # 计算平仓盈亏
        mult = Decimal('1') if self.size > 0 else Decimal('-1')
        pnl = mult * (price - self.avg_price) * size

        # 更新持仓
        if self.size > 0:
            self.size -= size
        else:
            self.size += size

        if abs(self.size) < Decimal('0.01'):  # 全部平仓
            self.size = 0
            self.avg_price = Decimal('0')

        self.update_position()
        return pnl.quantize(Decimal('0.01'), ROUND_HALF_DOWN)

    def get_margin_required(self):
        """计算所需保证金"""
        if self.size == 0:
            return Decimal('0')

        # 保证金 = 持仓价值 / 杠杆
        position_value = abs(Decimal(str(self.size))) * self.cur_price
        margin = position_value / Decimal(str(self.leverage))
        return margin.quantize(Decimal('0.01'), ROUND_HALF_DOWN)

    def __repr__(self):
        return (f"ForexPosition({self._name}, size={self.size}, "
                f"avg_price={self.avg_price}, profit={self.profit_base})")
```

#### 3.2.2 外汇事件系统

```python
"""
Forex Events for backtrader
参考：qsforex/event/event.py
"""
from decimal import Decimal
from datetime import datetime


class ForexEvent:
    """外汇事件基类"""
    pass


class TickEvent(ForexEvent):
    """
    Tick 报价事件

    模拟外汇市场的实时报价更新
    """

    def __init__(self, instrument, time, bid, ask):
        self.type = 'TICK'
        self.instrument = instrument
        self.time = time
        self.bid = Decimal(str(bid))
        self.ask = Decimal(str(ask))
        self.mid = (self.bid + self.ask) / 2

    def get_spread(self):
        """获取买卖价差"""
        return self.ask - self.bid

    def get_spread_pips(self):
        """获取点差"""
        spread = self.get_spread()
        pip_location = Decimal('0.0001')
        if 'JPY' in self.instrument:
            pip_location = Decimal('0.01')
        return spread / pip_location

    def __repr__(self):
        return f"TickEvent({self.instrument}, bid={self.bid}, ask={self.ask})"


class SignalEvent(ForexEvent):
    """
    交易信号事件

    由策略生成，表示买卖信号
    """

    def __init__(self, instrument, order_type, side, time, strength=1.0):
        """
        Args:
            instrument: 货币对
            order_type: 订单类型 ('market', 'limit', 'stop')
            side: 方向 ('buy', 'sell')
            time: 信号时间
            strength: 信号强度 (0-1)
        """
        self.type = 'SIGNAL'
        self.instrument = instrument
        self.order_type = order_type
        self.side = side
        self.time = time
        self.strength = strength

    def __repr__(self):
        return f"SignalEvent({self.instrument}, {self.side}, {self.order_type})"


class OrderEvent(ForexEvent):
    """
    订单事件

    表示订单的执行
    """

    def __init__(self, instrument, units, order_type, side, price=None):
        """
        Args:
            instrument: 货币对
            units: 手数
            order_type: 订单类型
            side: 方向
            price: 执行价格（市价单为None）
        """
        self.type = 'ORDER'
        self.instrument = instrument
        self.units = int(units)
        self.order_type = order_type
        self.side = side
        self.price = Decimal(str(price)) if price is not None else None

    def __repr__(self):
        return f"OrderEvent({self.instrument}, {self.side}, {self.units} units)"


class ForexEventManager:
    """
    外汇事件管理器

    管理事件队列和事件分发
    """

    def __init__(self):
        self._handlers = {
            'TICK': [],
            'SIGNAL': [],
            'ORDER': []
        }

    def register_handler(self, event_type, handler):
        """注册事件处理器"""
        if event_type in self._handlers:
            self._handlers[event_type].append(handler)

    def emit(self, event):
        """发出事件"""
        event_type = getattr(event, 'type', None)
        if event_type and event_type in self._handlers:
            for handler in self._handlers[event_type]:
                handler(event)

    def create_tick_signal(self, data):
        """从 backtrader 数据创建 Tick 事件"""
        if hasattr(data, 'bid') and hasattr(data, 'ask'):
            return TickEvent(
                instrument=data._name,
                time=data.datetime.datetime(0),
                bid=data.bid[0],
                ask=data.ask[0]
            )
        return None
```

#### 3.2.3 Pips 计算工具

```python
"""
Pips Calculator
参考 qsforex Position.calculate_pips()
"""
from decimal import Decimal, ROUND_HALF_DOWN


class PipsCalculator:
    """
    点值计算器

    外汇交易的盈亏通常用"点"(Pips)来衡量
    """

    # 各货币对的标准点值
    PIP_LOCATIONS = {
        'JPY': Decimal('0.01'),      # 日元货币对
        'DEFAULT': Decimal('0.0001')  # 其他货币对
    }

    @classmethod
    def get_pip_location(cls, pair):
        """
        获取货币对的点值位置

        Args:
            pair: 货币对名称 (如 'EURUSD')

        Returns:
            Decimal: 点值位置
        """
        if 'JPY' in pair.upper():
            return cls.PIP_LOCATIONS['JPY']
        return cls.PIP_LOCATIONS['DEFAULT']

    @classmethod
    def calculate_pips(cls, entry_price, exit_price, pair, position_type='long'):
        """
        计算点值

        Args:
            entry_price: 入场价格
            exit_price: 出场价格
            pair: 货币对
            position_type: 'long' 或 'short'

        Returns:
            Decimal: 点值
        """
        entry = Decimal(str(entry_price))
        exit = Decimal(str(exit_price))
        pip_location = cls.get_pip_location(pair)

        if position_type == 'long':
            pips = (exit - entry) / pip_location
        else:
            pips = (entry - exit) / pip_location

        return pips.quantize(Decimal('0.01'), ROUND_HALF_DOWN)

    @classmethod
    def price_to_pips(cls, price_change, pair):
        """
        将价格变化转换为点值

        Args:
            price_change: 价格变化量
            pair: 货币对

        Returns:
            Decimal: 点值
        """
        change = Decimal(str(price_change))
        pip_location = cls.get_pip_location(pair)
        return (change / pip_location).quantize(Decimal('0.01'), ROUND_HALF_DOWN)

    @classmethod
    def pips_to_price(cls, pips, pair):
        """
        将点值转换为价格变化

        Args:
            pips: 点值
            pair: 货币对

        Returns:
            Decimal: 价格变化
        """
        p = Decimal(str(pips))
        pip_location = cls.get_pip_location(pair)
        return (p * pip_location).quantize(pip_location, ROUND_HALF_DOWN)


# 使用示例
if __name__ == '__main__':
    # EURUSD 从 1.1000 到 1.1050
    pips = PipsCalculator.calculate_pips(1.1000, 1.1050, 'EURUSD')
    print(f"EURUSD 盈利: {pips} pips")  # 输出: 50 pips

    # USDJPY 从 110.00 到 110.50
    pips = PipsCalculator.calculate_pips(110.00, 110.50, 'USDJPY')
    print(f"USDJPY 盈利: {pips} pips")  # 输出: 50 pips
```

#### 3.2.4 保证金计算器

```python
"""
Margin Calculator for Forex
"""
from decimal import Decimal, ROUND_HALF_UP


class MarginCalculator:
    """
    外汇保证金计算器

    计算外汇交易所需的保证金
    """

    @staticmethod
    def calculate_margin(
        units, price, leverage, contract_size=Decimal('100000')
    ):
        """
        计算所需保证金

        Args:
            units: 手数
            price: 当前价格
            leverage: 杠杆倍数
            contract_size: 合约大小（标准手为100,000基础货币）

        Returns:
            Decimal: 所需保证金
        """
        units = Decimal(str(units))
        price = Decimal(str(price))
        leverage = Decimal(str(leverage))

        # 保证金 = (手数 × 合约大小 × 价格) / 杠杆
        # 注意：对于大多数货币对，价格是针对基础货币的
        position_value = units * contract_size * price
        margin = position_value / leverage

        return margin.quantize(Decimal('0.01'), ROUND_HALF_UP)

    @staticmethod
    def calculate_margin_required(
        position_size, current_price, account_currency, pair, leverage, exchange_rate=1.0
    ):
        """
        计算跨币种保证金需求

        Args:
            position_size: 持仓大小（手数）
            current_price: 当前价格
            account_currency: 账户货币
            pair: 货币对
            leverage: 杠杆
            exchange_rate: 汇率（如需要转换）

        Returns:
            Decimal: 所需保证金
        """
        base_margin = MarginCalculator.calculate_margin(
            position_size, current_price, leverage
        )
        return base_margin * Decimal(str(exchange_rate))

    @staticmethod
    def calculate_max_units(
        account_balance, price, leverage, risk_ratio=Decimal('0.02'), contract_size=Decimal('100000')
    ):
        """
        根据风险比例计算最大可交易手数

        Args:
            account_balance: 账户余额
            price: 当前价格
            leverage: 杠杆
            risk_ratio: 每笔交易风险比例（默认2%）
            contract_size: 合约大小

        Returns:
            Decimal: 最大手数
        """
        balance = Decimal(str(account_balance))
        p = Decimal(str(price))
        lev = Decimal(str(leverage))
        risk = Decimal(str(risk_ratio))

        # 风险金额
        risk_amount = balance * risk

        # 可用保证金（考虑杠杆）
        available_margin = risk_amount * lev

        # 最大手数
        max_units = available_margin / (contract_size * p)

        return int(max_units.quantize(Decimal('1'), ROUND_HALF_UP))

    @staticmethod
    def calculate_units_from_risk(
        account_balance, price, leverage, stop_loss_pips, risk_per_trade_pct=Decimal('0.02')
    ):
        """
        根据止损点值和风险比例计算手数

        Args:
            account_balance: 账户余额
            price: 当前价格
            leverage: 杠杆
            stop_loss_pips: 止损点值
            risk_per_trade_pct: 每笔交易风险比例

        Returns:
            Decimal: 手数
        """
        balance = Decimal(str(account_balance))
        risk_pct = Decimal(str(risk_per_trade_pct))

        # 风险金额
        risk_amount = balance * risk_pct

        # 每手风险
        pip_value = Decimal('0.0001')  # 假设非JPY货币对
        risk_per_unit = stop_loss_pips * pip_value * 100000  # 标准手

        # 手数
        units = risk_amount / risk_per_unit if risk_per_unit > 0 else Decimal('0')

        return int(units.quantize(Decimal('1'), ROUND_HALF_UP))
```

### 3.3 在 backtrader 中使用

```python
"""
使用示例：在 backtrader 中集成外汇功能
"""
import backtrader as bt
from backtrader.forex import ForexPosition, PipsCalculator, MarginCalculator
from backtrader.forex.events import TickEvent, SignalEvent, ForexEventManager


class ForexStrategy(bt.Strategy):
    """
    外汇策略示例
    """

    params = (
        ('leverage', 100),          # 100倍杠杆
        ('risk_per_trade', 0.02),   # 每笔2%风险
        ('stop_loss_pips', 50),     # 50点止损
        ('take_profit_pips', 100),  # 100点止盈
    )

    def __init__(self):
        # 初始化外汇头寸管理
        self.forex_positions = {}
        for data in self.datas:
            pos = ForexPosition(
                data,
                home_currency='USD',
                leverage=self.p.leverage
            )
            self.forex_positions[data._name] = pos

        # 初始化指标
        self.sma_fast = bt.indicators.SMA(self.data0, period=20)
        self.sma_slow = bt.indicators.SMA(self.data0, period=50)

        # 记录入场信息
        self.entry_price = None
        self.entry_pips = None

    def next(self):
        # 获取当前数据
        current_price = self.data0.close[0]
        pair_name = self.data0._name

        # 更新头寸
        if pair_name in self.forex_positions:
            self.forex_positions[pair_name].update_position()

        # 检查止损/止盈
        if self.entry_price is not None:
            current_pips = PipsCalculator.calculate_pips(
                self.entry_price, current_price, pair_name,
                'long' if self.getposition(self.data0).size > 0 else 'short'
            )

            # 止损
            if current_pips <= -self.p.stop_loss_pips:
                self.close()
                self.entry_price = None
                return

            # 止盈
            if current_pips >= self.p.take_profit_pips:
                self.close()
                self.entry_price = None
                return

        # 策略逻辑：金叉买入
        if self.sma_fast[0] > self.sma_slow[0] and self.sma_fast[-1] <= self.sma_slow[-1]:
            if self.getposition(self.data0).size == 0:
                # 计算手数
                units = MarginCalculator.calculate_units_from_risk(
                    self.broker.getvalue(),
                    current_price,
                    self.p.leverage,
                    self.p.stop_loss_pips,
                    self.p.risk_per_trade
                )

                # 开仓
                self.buy(size=units)
                self.entry_price = current_price

        # 死叉卖出
        elif self.sma_fast[0] < self.sma_slow[0] and self.sma_fast[-1] >= self.sma_slow[-1]:
            if self.getposition(self.data0).size > 0:
                self.close()
                self.entry_price = None

    def notify_trade(self, trade):
        """交易完成通知"""
        if trade.isclosed:
            # 计算盈亏点数
            if self.entry_price is not None and trade.pnl != 0:
                pips = PipsCalculator.price_to_pips(
                    trade.pnl / abs(trade.size),
                    self.data._name
                )
                print(f"Trade closed: PnL={trade.pnl:.2f}, Pips={pips}")

    def stop(self):
        """回测结束"""
        print("\n=== 回测结果 ===")
        print(f"最终资金: {self.broker.getvalue():.2f}")
        for name, pos in self.forex_positions.items():
            if pos.size != 0:
                print(f"{name}: {pos.size} 手, 盈亏: {pos.profit_base:.2f} ({pos.profit_pips} pips)")
```

---

## 四、API 设计

### 4.1 外汇头寸 API

```python
from backtrader.forex import ForexPosition

# 创建外汇头寸
position = ForexPosition(data, home_currency='USD', leverage=100)

# 开仓
position.open_position(size=1000, price=1.1000)

# 更新价格和盈亏
position.update_position()

# 获取信息
print(f"持仓: {position.size}")
print(f"平均价: {position.avg_price}")
print(f"点数盈亏: {position.profit_pips}")
print(f"资金盈亏: {position.profit_base}")
print(f"所需保证金: {position.get_margin_required()}")

# 平仓
pnl = position.close_position(size=500, price=1.1050)
print(f"平仓盈亏: {pnl}")
```

### 4.2 Pips 计算器 API

```python
from backtrader.forex import PipsCalculator

# 计算点值
pips = PipsCalculator.calculate_pips(1.1000, 1.1050, 'EURUSD', 'long')
print(f"盈利于: {pips} pips")

# 价格转点值
pips = PipsCalculator.price_to_pips(0.0050, 'EURUSD')
print(f"价格变化: {pips} pips")

# 点值转价格
price_change = PipsCalculator.pips_to_price(50, 'EURUSD')
print(f"点值对应价格: {price_change}")
```

### 4.3 保证金计算 API

```python
from backtrader.forex import MarginCalculator

# 计算保证金
margin = MarginCalculator.calculate_margin(
    units=1,           # 1手
    price=1.1000,      # 价格
    leverage=100       # 100倍杠杆
)
print(f"所需保证金: {margin}")

# 根据风险计算最大手数
max_units = MarginCalculator.calculate_max_units(
    account_balance=10000,
    price=1.1000,
    leverage=100,
    risk_ratio=0.02
)
print(f"最大手数: {max_units}")

# 根据止损计算手数
units = MarginCalculator.calculate_units_from_risk(
    account_balance=10000,
    price=1.1000,
    leverage=100,
    stop_loss_pips=50,
    risk_per_trade_pct=0.02
)
print(f"建议手数: {units}")
```

---

## 五、实施计划

### 5.1 实施阶段

| 阶段 | 内容 | 时间 |
|------|------|------|
| Phase 1 | CurrencyPair 和 PipsCalculator | 0.5天 |
| Phase 2 | ForexPosition 头寸类 | 1天 |
| Phase 3 | MarginCalculator 保证金计算 | 0.5天 |
| Phase 4 | 外汇事件系统 | 0.5天 |
| Phase 5 | 策略集成和示例 | 0.5天 |
| Phase 6 | 测试和文档 | 1天 |

### 5.2 优先级

1. **P0**: PipsCalculator - 点值计算
2. **P0**: ForexPosition - 外汇头寸管理
3. **P1**: MarginCalculator - 保证金计算
4. **P1**: CurrencyPair - 货币对处理
5. **P2**: 外汇事件系统
6. **P2**: Decimal 精度工具

---

## 六、参考资料

### 6.1 关键参考代码

- qsforex/portfolio/position.py - Position 头寸管理
- qsforex/portfolio/portfolio.py - Portfolio 组合管理
- qsforex/event/event.py - 事件系统定义
- qsforex/backtest/backtest.py - 回测引擎
- qsforex/strategy/strategy.py - 策略基类

### 6.2 qsforex 核心设计

```python
# Position 核心方法
position.calculate_pips()           # 计算点值
position.calculate_profit_base()    # 计算盈亏
position.calculate_profit_perc()    # 计算盈亏百分比
position.update_position_price()    # 更新价格
position.add_units()                # 加仓
position.remove_units()             # 减仓
position.close_position()           # 平仓

# Portfolio 核心方法
portfolio.add_new_position()        # 新建头寸
portfolio.add_position_units()      # 加仓
portfolio.remove_position_units()   # 减仓
portfolio.close_position()          # 平仓
portfolio.update_portfolio()        # 更新组合
portfolio.execute_signal()          # 执行信号
portfolio.calc_risk_position_size() # 计算风险头寸

# 事件处理流程
TickEvent -> strategy.calculate_signals() -> SignalEvent
SignalEvent -> portfolio.execute_signal() -> OrderEvent
OrderEvent -> execution.execute_order()
```

### 6.3 关键设计模式

1. **观察者模式** - 事件驱动架构
2. **策略模式** - 不同的交易策略
3. **组合模式** - Portfolio 管理多个 Position
4. **工厂模式** - 创建不同类型的订单

### 6.4 backtrader 可复用组件

- `backtrader/strategy.py` - 策略基类
- `backtrader/broker.py` - Broker 和保证金
- `backtrader/position.py` - 原有头寸类
- `backtrader/feeds/*` - 数据源
