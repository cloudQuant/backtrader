### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/rqalpha
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### rqalpha项目简介
rqalpha是由Ricequant开发的Python量化回测框架，具有以下核心特点：
- **模块化设计**: 通过Mod机制实现功能扩展
- **事件驱动**: 基于事件的回测引擎
- **API兼容**: 与Ricequant平台API兼容
- **多维度分析**: 丰富的回测分析指标
- **配置管理**: 灵活的YAML配置系统
- **命令行工具**: 完善的CLI命令行工具

### 重点借鉴方向
1. **Mod扩展机制**: 插件式的模块扩展系统
2. **ExecutionContext**: 执行上下文管理
3. **Environment**: 全局环境变量管理
4. **配置系统**: 基于YAML的配置管理
5. **事件总线**: EventBus事件通信机制
6. **持仓管理**: Position和Portfolio管理

---

## 框架对比分析

### 架构设计对比

| 维度 | backtrader | rqalpha |
|------|-----------|---------|
| **核心引擎** | Cerebro (集中式) | Environment (依赖注入) |
| **扩展机制** | 继承 + 组合 | Mod插件系统 |
| **配置管理** | 代码级参数 | YAML多层级配置 |
| **事件通信** | 回调方法 | EventBus发布-订阅 |
| **上下文管理** | 隐式状态 | ExecutionContext栈式管理 |
| **持仓管理** | Broker内置 | 独立Position/Portfolio模块 |
| **执行阶段** | prenext/next/nextstart | 枚举定义的EXECUTION_PHASE |

### backtrader的优势
1. **简洁性**: API设计更直观，学习曲线平缓
2. **性能**: LineBuffer高效内存管理，支持runonce向量化模式
3. **灵活性**: 支持多时间周期、多数据源的复杂策略
4. **指标库**: 内置60+技术指标，覆盖全面

### rqalpha的优势
1. **模块化**: Mod机制实现真正的插件化，核心功能可替换
2. **配置驱动**: 支持YAML配置，便于策略参数管理
3. **阶段约束**: ExecutionContext确保API在正确阶段调用
4. **事件解耦**: EventBus实现松耦合的组件通信
5. **持仓精细化**: 支持今昨仓分离、FIFO队列管理

---

## 需求规格文档

### 需求1: 插件化扩展系统 (Mod System)

**需求描述**:
引入类似于rqalpha的Mod插件机制，允许用户通过插件方式扩展或替换backtrader的核心功能组件，而无需修改核心代码。

**功能需求**:
1. **Mod接口定义**: 定义AbstractMod基类，包含start_up和tear_down生命周期方法
2. **Mod加载器**: 支持从配置文件动态加载插件
3. **组件替换**: 允许插件替换Broker、DataFeed、Analyzer等核心组件
4. **优先级控制**: 支持插件启动顺序控制
5. **依赖管理**: 支持插件间的依赖关系声明

**非功能需求**:
- 向后兼容: 现有策略代码无需修改
- 性能影响最小: 插件机制不应显著影响回测性能
- 错误隔离: 插件异常不应导致核心框架崩溃

### 需求2: 执行上下文管理 (ExecutionContext)

**需求描述**:
实现执行上下文管理机制，确保策略API在正确的执行阶段被调用，并提供更好的错误提示。

**功能需求**:
1. **执行阶段枚举**: 定义INIT、BEFORE_TRADING、ON_BAR、AFTER_TRADING等阶段
2. **上下文栈**: 支持嵌套上下文管理
3. **阶段检查装饰器**: 装饰器确保方法只在特定阶段可调用
4. **友好错误提示**: 当API在错误阶段调用时，给出清晰提示

**非功能需求**:
- 性能开销小: 上下文检查不应显著影响执行速度
- 可选功能: 允许用户禁用阶段检查以提高性能

### 需求3: YAML配置系统

**需求描述**:
支持通过YAML文件配置回测参数，包括数据源、策略参数、佣金设置等。

**功能需求**:
1. **多层级配置**: 默认配置 < 用户配置 < 项目配置 < 命令行配置
2. **配置验证**: 类型检查和范围验证
3. **策略配置**: 支持在策略文件中定义配置
4. **环境变量**: 支持环境变量替换

**非功能需求**:
- 向后兼容: 保持现有代码配置方式
- 配置简化: 常用配置应有合理的默认值

### 需求4: 事件总线系统

**需求描述**:
实现发布-订阅模式的事件总线，用于组件间解耦通信。

**功能需求**:
1. **事件定义**: 预定义ORDER_PENDING、ORDER_FILLED、TRADE等事件类型
2. **监听器注册**: 支持同步/异步监听器
3. **优先级支持**: 支持监听器优先级排序
4. **事件过滤**: 支持条件过滤

**非功能需求**:
- 性能优化: 事件分发应尽可能高效
- 向后兼容: 现有notify_*回调机制继续支持

### 需求5: 增强持仓管理

**需求描述**:
改进持仓管理功能，支持更精细的持仓控制和更丰富的持仓信息。

**功能需求**:
1. **FIFO队列**: 支持先进先出的持仓平仓逻辑
2. **今昨仓分离**: 期货策略支持今仓昨仓分别管理
3. **持仓详情**: 记录每笔交易的开仓价、平仓价、盈亏
4. **持仓代理**: 统一管理多空持仓

**非功能需求**:
- 向后兼容: 现有持仓查询API保持不变
- 可选功能: 高级功能可按需启用

---

## 设计文档

### 1. Mod扩展系统设计

#### 1.1 核心类设计

```python
# backtrader/mod.py

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Type
from collections import OrderedDict

class ModConfig:
    """Mod配置类"""
    def __init__(self, name: str, enabled: bool = True, priority: int = 100,
                 dependencies: Optional[List[str]] = None):
        self.name = name
        self.enabled = enabled
        self.priority = priority
        self.dependencies = dependencies or []

class AbstractMod(ABC):
    """Mod插件基类"""

    def __init__(self, config: ModConfig):
        self.config = config
        self.env = None

    @abstractmethod
    def start_up(self, env, mod_config: Dict):
        """插件启动时调用

        Args:
            env: Environment实例
            mod_config: 插件配置字典
        """
        pass

    def tear_down(self, code: int = 0, exception: Optional[Exception] = None):
        """插件清理时调用

        Args:
            code: 退出码
            exception: 异常信息(如果有)
        """
        pass

class ModHandler:
    """Mod插件管理器"""

    def __init__(self):
        self._env = None
        self._mod_configs: List[ModConfig] = []
        self._mod_instances: OrderedDict = OrderedDict()

    def set_env(self, env):
        """设置Environment实例"""
        self._env = env

    def load_from_config(self, config_dict: Dict):
        """从配置加载Mod

        Args:
            config_dict: 配置字典，格式: {mod_name: {enabled, priority, config}}
        """
        for name, mod_conf in config_dict.items():
            if not mod_conf.get('enabled', True):
                continue
            self._mod_configs.append(ModConfig(
                name=name,
                enabled=mod_conf.get('enabled', True),
                priority=mod_conf.get('priority', 100),
                dependencies=mod_conf.get('dependencies', [])
            ))

    def start_up(self):
        """启动所有已加载的Mod

        按优先级排序后启动，处理依赖关系
        """
        # 拓扑排序处理依赖
        sorted_mods = self._topological_sort()

        # 按优先级排序
        sorted_mods.sort(key=lambda x: x.priority, reverse=True)

        for mod_config in sorted_mods:
            mod_instance = self._import_and_create_mod(mod_config)
            if mod_instance:
                mod_config_dict = self._get_mod_config(mod_config.name)
                mod_instance.start_up(self._env, mod_config_dict)
                self._mod_instances[mod_config.name] = mod_instance

    def tear_down(self, code: int = 0, exception: Optional[Exception] = None):
        """清理所有Mod，按启动逆序"""
        for mod_instance in reversed(self._mod_instances.values()):
            try:
                mod_instance.tear_down(code, exception)
            except Exception as e:
                # 记录错误但继续清理其他插件
                pass

    def _import_and_create_mod(self, mod_config: ModConfig) -> Optional[AbstractMod]:
        """动态导入并创建Mod实例"""
        try:
            # 支持系统模块和自定义模块
            import importlib
            if '.' in mod_config.name:
                # 自定义模块: package.mod.ClassName
                module_path, class_name = mod_config.name.rsplit('.', 1)
                module = importlib.import_module(module_path)
                mod_class = getattr(module, class_name)
            else:
                # 系统模块: backtrader.mods.{name}
                from backtrader.mods import import_mod
                mod_class = import_mod(mod_config.name)

            return mod_class(mod_config)
        except Exception as e:
            return None

    def _topological_sort(self) -> List[ModConfig]:
        """处理依赖关系的拓扑排序"""
        # 实现依赖解析
        pass
```

#### 1.2 与Cerebro集成

```python
# backtrader/cerebro.py 添加

class Cerebro:
    def __init__(self):
        # ... 现有代码 ...
        self._mod_handler = ModHandler()
        self._mod_handler.set_env(self)  # 或创建独立的Environment

    def addmod(self, mod_name: str, **kwargs):
        """添加Mod插件"""
        mod_config = ModConfig(mod_name, **kwargs)
        self._mod_handler._mod_configs.append(mod_config)
        return self

    def run(self):
        # 启动Mod
        self._mod_handler.start_up()

        try:
            # 现有run逻辑
            results = self._run()
        finally:
            # 清理Mod
            self._mod_handler.tear_down()

        return results
```

### 2. ExecutionContext设计

#### 2.1 核心类设计

```python
# backtrader/execution_context.py

from enum import Enum
from contextlib import contextmanager
from functools import wraps
from typing import Optional, List, Callable

class ExecutionPhase(Enum):
    """执行阶段枚举"""
    ON_INIT = "on_init"              # 策略初始化
    BEFORE_TRADING = "before_trading"  # 交易前
    ON_BAR = "on_bar"                # K线处理
    AFTER_TRADING = "after_trading"  # 交易后
    SCHEDULED = "scheduled"          # 定时任务
    FINALIZE = "finalize"            # 结束

class ExecutionContext:
    """执行上下文管理器"""

    _stack = []  # 类级别的上下文栈

    def __init__(self, phase: ExecutionPhase):
        self.phase = phase
        self._prev_context = None

    def __enter__(self):
        self._prev_context = self.current()
        ExecutionContext._stack.append(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if ExecutionContext._stack and ExecutionContext._stack[-1] is self:
            ExecutionContext._stack.pop()
        return False

    @classmethod
    def current(cls) -> Optional['ExecutionContext']:
        """获取当前上下文"""
        if cls._stack:
            return cls._stack[-1]
        return None

    @classmethod
    def get_phase(cls) -> ExecutionPhase:
        """获取当前执行阶段"""
        ctx = cls.current()
        return ctx.phase if ctx else None

    @classmethod
    def enforce_phase(cls, *allowed_phases: ExecutionPhase) -> Callable:
        """阶段检查装饰器

        确保被装饰的方法只在允许的阶段执行
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                current_phase = cls.get_phase()
                if current_phase not in allowed_phases:
                    raise RuntimeError(
                        f"{func.__name__} can only be called in phases "
                        f"{[p.value for p in allowed_phases]}, "
                        f"but current phase is {current_phase.value if current_phase else 'None'}"
                    )
                return func(*args, **kwargs)
            return wrapper
        return decorator

# 使用示例
@ExecutionContext.enforce_phase(ExecutionPhase.ON_BAR, ExecutionPhase.SCHEDULED)
def order_target_percent(symbol, percent):
    """只在ON_BAR或SCHEDULED阶段允许下单"""
    pass
```

#### 2.2 与Cerebro集成

```python
# backtrader/cerebro.py 修改

def _run(self):
    # 初始化阶段
    with ExecutionContext(ExecutionPhase.ON_INIT):
        self._stratrunstart()

    # 主循环
    while not runstop:
        # 交易前
        with ExecutionContext(ExecutionPhase.BEFORE_TRADING):
            self._pre_trading()

        # K线处理
        with ExecutionContext(ExecutionPhase.ON_BAR):
            self._next()

        # 交易后
        with ExecutionContext(ExecutionPhase.AFTER_TRADING):
            self._post_trading()

    # 结束
    with ExecutionContext(ExecutionPhase.FINALIZE):
        self._stratstop()
```

### 3. YAML配置系统设计

#### 3.1 配置结构

```yaml
# config.yml 示例

base:
  start_date: 2020-01-01
  end_date: 2023-12-31
  cash: 1000000
  commission: 0.001

data:
  - name: stock_data
    type: csv
    path: ./data/stock.csv
    timeframe: day

  - name: future_data
    type: pandas
    symbol: RB2305

strategy:
  name: MyStrategy
  params:
    period: 20
    threshold: 0.02

mods:
  sys_risk:
    enabled: true
    priority: 100
    config:
      max_drawdown: 0.2

  sys_analyzer:
    enabled: true
    config:
      metrics: [sharpe, max_drawdown, annual_return]
```

#### 3.2 配置加载器

```python
# backtrader/config.py

import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from copy import deepcopy

class Config:
    """配置管理器"""

    DEFAULT_CONFIG = {
        'base': {
            'start_date': None,
            'end_date': None,
            'cash': 10000,
            'commission': 0.0,
        },
        'data': [],
        'strategy': {
            'name': None,
            'params': {},
        },
        'mods': {},
    }

    def __init__(self):
        self._config = deepcopy(self.DEFAULT_CONFIG)

    def load_from_yaml(self, path: str):
        """从YAML文件加载配置"""
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            user_config = yaml.safe_load(f) or {}

        self._deep_update(user_config, self._config)

    def load_from_dict(self, config: Dict[str, Any]):
        """从字典加载配置"""
        self._deep_update(config, self._config)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点分隔路径"""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    def _deep_update(self, source: Dict, target: Dict):
        """递归更新字典"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_update(value, target[key])
            else:
                target[key] = value

# 使用
def run_from_config(config_path: str):
    config = Config()
    config.load_from_yaml(config_path)

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(config.get('base.cash'))
    cerebro.broker.setcommission(config.get('base.commission'))

    # 加载数据
    for data_config in config.get('data', []):
        data = load_data(data_config)
        cerebro.adddata(data)

    # 添加策略
    strategy_config = config.get('strategy')
    StrategyClass = get_strategy(strategy_config['name'])
    cerebro.addstrategy(StrategyClass, **strategy_config.get('params', {}))

    return cerebro.run()
```

### 4. EventBus设计

#### 4.1 核心类设计

```python
# backtrader/events.py

from enum import Enum
from typing import Callable, Dict, List, Any, Optional
from collections import defaultdict
from dataclasses import dataclass

class EventType(Enum):
    """事件类型枚举"""
    # 系统事件
    PRE_SYSTEM_INIT = "pre_system_init"
    POST_SYSTEM_INIT = "post_system_init"
    PRE_BAR = "pre_bar"
    BAR = "bar"
    POST_BAR = "post_bar"
    FINALIZE = "finalize"

    # 订单事件
    ORDER_PENDING = "order_pending"
    ORDER_ACCEPTED = "order_accepted"
    ORDER_REJECTED = "order_rejected"
    ORDER_COMPLETED = "order_completed"
    ORDER_CANCELED = "order_canceled"

    # 成交事件
    TRADE_OPENED = "trade_opened"
    TRADE_CLOSED = "trade_closed"

@dataclass
class Event:
    """事件对象"""
    type: EventType
    data: Dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.data.get(key)

class EventBus:
    """事件总线"""

    def __init__(self):
        self._listeners: Dict[EventType, List[Callable]] = defaultdict(list)
        self._system_listeners: Dict[EventType, List[Callable]] = defaultdict(list)

    def subscribe(self, event_type: EventType, listener: Callable,
                 priority: int = 100, is_system: bool = False):
        """订阅事件

        Args:
            event_type: 事件类型
            listener: 监听器函数
            priority: 优先级，越大越先执行
            is_system: 是否为系统监听器
        """
        listener_dict = self._system_listeners if is_system else self._listeners
        listener_dict[event_type].append((priority, listener))
        # 按优先级排序
        listener_dict[event_type].sort(key=lambda x: x[0], reverse=True)

    def unsubscribe(self, event_type: EventType, listener: Callable):
        """取消订阅"""
        self._listeners[event_type] = [
            (p, l) for p, l in self._listeners[event_type] if l != listener
        ]
        self._system_listeners[event_type] = [
            (p, l) for p, l in self._system_listeners[event_type] if l != listener
        ]

    def publish(self, event: Event):
        """发布事件

        先执行系统监听器，支持返回True中断传播
        再执行用户监听器
        """
        # 系统监听器
        for priority, listener in self._system_listeners[event.type]:
            try:
                result = listener(event)
                if result is True:  # 中断传播
                    return
            except Exception as e:
                pass

        # 用户监听器
        for priority, listener in self._listeners[event.type]:
            try:
                listener(event)
            except Exception as e:
                pass

    def clear(self):
        """清空所有监听器"""
        self._listeners.clear()
        self._system_listeners.clear()
```

#### 4.2 与Cerebro集成

```python
# backtrader/cerebro.py 添加

class Cerebro:
    def __init__(self):
        # ... 现有代码 ...
        self._event_bus = EventBus()

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    def _run(self):
        # 发布系统初始化事件
        self._event_bus.publish(Event(EventType.POST_SYSTEM_INIT, {'cerebro': self}))

        # 在主循环中发布BAR事件
        while not runstop:
            self._event_bus.publish(Event(EventType.PRE_BAR, {'datetime': dt}))
            self._next()
            self._event_bus.publish(Event(EventType.POST_BAR, {'datetime': dt}))

# 在Broker中发布订单事件
class BrokerBack(BrokerBase):
    def accept(self, order):
        # 接受订单
        self._cerebro.event_bus.publish(
            Event(EventType.ORDER_ACCEPTED, {'order': order})
        )

    def next(self):
        # 检查订单状态变化并发布事件
        if order.iscompleted():
            self._cerebro.event_bus.publish(
                Event(EventType.ORDER_COMPLETED, {'order': order})
            )
```

### 5. 增强持仓管理设计

#### 5.1 核心类设计

```python
# backtrader/position.py

from collections import deque
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

@dataclass
class PositionItem:
    """持仓项，记录单次开仓信息"""
    entry_date: datetime
    entry_price: float
    quantity: float
    commission: float = 0.0

    @property
    def value(self) -> float:
        """持仓价值"""
        return self.entry_price * self.quantity

class PositionQueue:
    """FIFO持仓队列"""

    def __init__(self):
        self._queue: deque[PositionItem] = deque()
        self._total_quantity = 0.0

    def add_position(self, item: PositionItem):
        """添加开仓"""
        self._queue.append(item)
        self._total_quantity += item.quantity

    def reduce_position(self, quantity: float, exit_price: float,
                        exit_date: datetime) -> List[Dict[str, Any]]:
        """平仓，按FIFO顺序

        Returns:
            已平仓的交易列表
        """
        closed_trades = []
        remaining = abs(quantity)

        while remaining > 0 and self._queue:
            item = self._queue[0]

            if item.quantity <= remaining:
                # 完全平掉这个持仓项
                remaining -= item.quantity
                self._queue.popleft()
                self._total_quantity -= item.quantity

                closed_trades.append({
                    'entry_date': item.entry_date,
                    'exit_date': exit_date,
                    'entry_price': item.entry_price,
                    'exit_price': exit_price,
                    'quantity': item.quantity,
                    'commission': item.commission,
                    'pnl': (exit_price - item.entry_price) * item.quantity - item.commission,
                })
            else:
                # 部分平仓
                item.quantity -= remaining
                self._total_quantity -= remaining

                closed_trades.append({
                    'entry_date': item.entry_date,
                    'exit_date': exit_date,
                    'entry_price': item.entry_price,
                    'exit_price': exit_price,
                    'quantity': remaining,
                    'commission': item.commission * (remaining / (remaining + item.quantity)),
                    'pnl': (exit_price - item.entry_price) * remaining,
                })
                remaining = 0

        return closed_trades

    @property
    def quantity(self) -> float:
        return self._total_quantity

    @property
    def items(self) -> List[PositionItem]:
        return list(self._queue)

    @property
    def avg_price(self) -> float:
        """平均持仓成本"""
        if not self._queue or self._total_quantity == 0:
            return 0.0
        total_value = sum(item.value for item in self._queue)
        return total_value / self._total_quantity

class EnhancedPosition:
    """增强的持仓管理类"""

    def __init__(self):
        self._long_queue = PositionQueue()  # 多头持仓
        self._short_queue = PositionQueue()  # 空头持仓
        self._last_price = 0.0

    def apply_trade(self, quantity: float, price: float, date: datetime,
                    commission: float = 0.0):
        """应用成交"""
        if quantity > 0:
            # 开多或平空
            if self._short_queue.quantity > 0:
                # 先平空
                close_qty = min(quantity, self._short_queue.quantity)
                closed_trades = self._short_queue.reduce_position(
                    -close_qty, price, date
                )
                # 剩余开多
                remaining = quantity - close_qty
                if remaining > 0:
                    self._long_queue.add_position(
                        PositionItem(date, price, remaining, commission)
                    )
            else:
                # 直接开多
                self._long_queue.add_position(
                    PositionItem(date, price, quantity, commission)
                )
        else:
            # 开空或平多
            abs_qty = abs(quantity)
            if self._long_queue.quantity > 0:
                # 先平多
                close_qty = min(abs_qty, self._long_queue.quantity)
                closed_trades = self._long_queue.reduce_position(
                    -close_qty, price, date
                )
                # 剩余开空
                remaining = abs_qty - close_qty
                if remaining > 0:
                    self._short_queue.add_position(
                        PositionItem(date, price, remaining, commission)
                    )
            else:
                # 直接开空
                self._short_queue.add_position(
                    PositionItem(date, price, abs_qty, commission)
                )

        self._last_price = price
        return closed_trades

    @property
    def net_quantity(self) -> float:
        """净持仓"""
        return self._long_queue.quantity - self._short_queue.quantity

    @property
    def market_value(self) -> float:
        """市值"""
        if self._last_price == 0:
            return 0.0
        return self.net_quantity * self._last_price

    @property
    def unrealized_pnl(self) -> float:
        """浮动盈亏"""
        long_pnl = (self._last_price - self._long_queue.avg_price) * self._long_queue.quantity
        short_pnl = (self._short_queue.avg_price - self._last_price) * self._short_queue.quantity
        return long_pnl + short_pnl

    @property
    def realized_pnl(self) -> float:
        """已实现盈亏"""
        # 需要跟踪历史平仓记录
        pass

    @property
    def long_avg_price(self) -> float:
        return self._long_queue.avg_price

    @property
    def short_avg_price(self) -> float:
        return self._short_queue.avg_price

    @property
    def closable_long(self) -> float:
        """可平多头数量"""
        return self._long_queue.quantity

    @property
    def closable_short(self) -> float:
        """可平空头数量"""
        return self._short_queue.quantity

    def get_position_detail(self) -> Dict[str, Any]:
        """获取持仓详情"""
        return {
            'net_quantity': self.net_quantity,
            'long_quantity': self._long_queue.quantity,
            'short_quantity': self._short_queue.quantity,
            'long_avg_price': self.long_avg_price,
            'short_avg_price': self.short_avg_price,
            'last_price': self._last_price,
            'market_value': self.market_value,
            'unrealized_pnl': self.unrealized_pnl,
            'long_items': len(self._long_queue.items),
            'short_items': len(self._short_queue.items),
        }
```

#### 5.2 期货今昨仓管理

```python
# backtrader/position_future.py

class FuturePositionQueue(PositionQueue):
    """期货持仓队列，支持今昨仓分离"""

    def __init__(self):
        super().__init__()
        self._today_queue: deque[PositionItem] = deque()  # 今仓
        self._yesterday_queue: deque[PositionItem] = deque()  # 昨仓

    def add_position(self, item: PositionItem, is_today: bool = True):
        """添加持仓"""
        if is_today:
            self._today_queue.append(item)
        else:
            self._yesterday_queue.append(item)
        self._total_quantity += item.quantity

    def reduce_position(self, quantity: float, exit_price: float,
                        exit_date: datetime, close_today: bool = False) -> List[Dict]:
        """平仓

        Args:
            quantity: 平仓数量
            exit_price: 平仓价格
            exit_date: 平仓日期
            close_today: 是否优先平今仓 (期货交易所规则)
        """
        closed_trades = []
        remaining = abs(quantity)

        # 根据close_today决定平仓顺序
        if close_today:
            queues = [self._today_queue, self._yesterday_queue]
        else:
            queues = [self._yesterday_queue, self._today_queue]

        for queue in queues:
            while remaining > 0 and queue:
                item = queue[0]

                if item.quantity <= remaining:
                    remaining -= item.quantity
                    queue.popleft()
                    self._total_quantity -= item.quantity

                    closed_trades.append({
                        'entry_date': item.entry_date,
                        'exit_date': exit_date,
                        'entry_price': item.entry_price,
                        'exit_price': exit_price,
                        'quantity': item.quantity,
                        'is_today': queue is self._today_queue,
                        'pnl': (exit_price - item.entry_price) * item.quantity,
                    })
                else:
                    item.quantity -= remaining
                    self._total_quantity -= remaining

                    closed_trades.append({
                        'entry_date': item.entry_date,
                        'exit_date': exit_date,
                        'entry_price': item.entry_price,
                        'exit_price': exit_price,
                        'quantity': remaining,
                        'is_today': queue is self._today_queue,
                        'pnl': (exit_price - item.entry_price) * remaining,
                    })
                    remaining = 0

        return closed_trades

    @property
    def today_quantity(self) -> float:
        return sum(item.quantity for item in self._today_queue)

    @property
    def yesterday_quantity(self) -> float:
        return sum(item.quantity for item in self._yesterday_queue)
```

### 6. 实施计划

#### 6.1 实施优先级

1. **高优先级** (第一阶段)
   - YAML配置系统 - 立即可用，提升用户体验
   - EventBus基础实现 - 为其他功能提供基础设施

2. **中优先级** (第二阶段)
   - ExecutionContext - 增强错误提示
   - Mod扩展系统 - 实现插件化

3. **可选优先级** (第三阶段)
   - 增强持仓管理 - 高级用户需求
   - 今昨仓管理 - 期货策略专用

#### 6.2 向后兼容性保证

所有新功能都是**可选的**，现有代码无需修改即可继续使用：

```python
# 现有用法继续支持
cerebro = bt.Cerebro()
cerebro.addstrategy(MyStrategy, period=20)
cerebro.run()

# 新用法
cerebro = bt.Cerebro()
cerebro.load_config('config.yml')  # 可选
cerebro.addmod(RiskMod)  # 可选
cerebro.run()
```

#### 6.3 目录结构

```
backtrader/
├── __init__.py
├── cerebro.py          # 核心引擎 (修改)
├── events.py           # 新增: EventBus
├── execution_context.py # 新增: ExecutionContext
├── config.py           # 新增: 配置系统
├── mod.py              # 新增: Mod系统
├── position.py         # 新增: 增强持仓管理
├── position_future.py  # 新增: 期货持仓
└── mods/               # 新增: 内置Mod目录
    ├── __init__.py
    ├── risk.py         # 风控Mod
    ├── analyzer.py     # 分析器Mod
    └── ...
```

---

## 总结

通过借鉴rqalpha的设计思想，backtrader可以在保持简洁性的同时，获得以下改进：

1. **更好的可扩展性**: Mod插件系统使功能扩展更灵活
2. **更清晰的配置管理**: YAML配置降低使用门槛
3. **更强的类型安全**: ExecutionContext确保API正确使用
4. **更松的耦合**: EventBus实现组件间解耦
5. **更精细的持仓控制**: 支持FIFO和今昨仓管理

这些改进都是**向后兼容**的，用户可以按需使用新功能，不影响现有策略代码。

