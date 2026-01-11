### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/ctpbee
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### ctpbee项目简介
ctpbee是一个简洁优雅的CTP期货接口框架，具有以下核心特点：
- **简洁设计**: 类Flask设计风格，简洁易用
- **CTP封装**: 对CTP接口的完整封装
- **异步支持**: 支持异步操作
- **扩展机制**: 灵活的扩展点设计
- **数据录制**: 内置行情录制功能
- **风控系统**: 基础风控模块

### 重点借鉴方向
1. **接口封装**: CTP接口的优雅封装
2. **App设计**: 类Flask的应用设计模式
3. **扩展点**: Extension扩展机制
4. **Action层**: 交易动作层抽象
5. **数据录制**: Recorder行情录制
6. **风控模块**: RiskController风控设计

---

## 项目对比分析

### Backtrader vs ctpbee 架构对比

| 维度 | Backtrader | ctpbee |
|------|------------|--------|
| **设计风格** | 传统Python OOP | 类Flask应用设计 |
| **应用入口** | Cerebro引擎 | CtpBee应用 |
| **扩展机制** | addstrat/addindicator | add_extension |
| **交易接口** | 抽象Broker基类 | Action层 + Interface |
| **数据访问** | Line系统 | Center数据中心 |
| **事件驱动** | prenext/next回调 | on_tick/on_bar等回调 |
| **配置管理** | 参数系统 | Config类（多来源） |
| **CTP支持** | 需要自行实现 | 内置完整CTP封装 |
| **实盘交易** | 通过IB/OANDA等 | 原生支持CTP |
| **数据记录** | Analyzer分析器 | Recorder数据中心 |
| **信号系统** | Observer观察者 | Signal信号分发 |

### ctpbee可借鉴的核心优势

#### 1. 应用设计模式
- **类Flask风格**: 简洁的应用创建和配置方式
- **应用上下文**: 清晰的应用生命周期管理
- **配置管理**: 支持多种配置来源（字典、JSON、文件）
- **工厂模式**: 灵活的应用创建方式

#### 2. 扩展机制
- **统一扩展基类**: CtpbeeApi作为所有扩展的基类
- **生命周期管理**: 支持扩展的启用、禁用、移除
- **事件回调**: 标准化的事件回调接口
- **依赖注入**: 支持扩展之间的依赖管理

#### 3. Action交易层
- **语义化交易方法**: buy_open/sell_close等语义清晰的方法
- **滑点控制**: 内置滑点处理机制
- **智能平仓**: 自动处理平今/平昨逻辑
- **权限检查**: 通过装饰器实现交易权限控制

#### 4. 数据中心
- **统一数据访问**: 通过center对象访问所有数据
- **事件驱动记录**: 自动记录所有市场事件
- **数据缓存**: 内置ticks/bars/orders等数据缓存
- **查询接口**: 便捷的数据查询方法

#### 5. 信号系统
- **松耦合通信**: 基于信号的事件分发机制
- **多订阅支持**: 同一事件可被多个订阅者处理
- **异步处理**: 支持异步事件处理

#### 6. 网关设计
- **接口适配器**: 统一的网关接口规范
- **多接口支持**: CTP、CTP Mini、融航等
- **事件转换**: 将底层接口事件转换为标准格式

---

## 需求文档

### 需求概述

借鉴ctpbee项目的设计理念，为backtrader添加以下功能模块，提升框架的易用性和扩展性：

### 功能需求

#### FR1: 应用设计模式

**FR1.1 应用上下文管理**
- 需求描述: 建立类似Flask的应用上下文管理机制
- 优先级: 高
- 验收标准:
  - 支持应用上下文的创建和销毁
  - 支持上下文变量的存取
  - 支持嵌套上下文

**FR1.2 配置管理增强**
- 需求描述: 增强配置管理功能，支持多种配置来源
- 优先级: 高
- 验收标准:
  - 支持从字典加载配置
  - 支持从JSON文件加载配置
  - 支持从Python文件加载配置
  - 支持配置环境变量

**FR1.3 应用工厂模式**
- 需求描述: 支持应用工厂模式创建应用实例
- 优先级: 中
- 验收标准:
  - 支持函数式应用创建
  - 支持应用配置函数
  - 支持多应用实例

#### FR2: 扩展机制增强

**FR2.1 统一扩展基类**
- 需求描述: 建立统一的扩展基类，规范扩展接口
- 优先级: 高
- 验收标准:
  - 定义ExtensionBase基类
  - 定义标准生命周期方法
  - 支持扩展依赖管理

**FR2.2 扩展生命周期管理**
- 需求描述: 实现扩展的启用、禁用、移除功能
- 优先级: 中
- 验收标准:
  - 支持动态添加扩展
  - 支持禁用和启用扩展
  - 支持移除扩展

**FR2.3 扩展事件总线**
- 需求描述: 实现扩展间的事件通信机制
- 优先级: 中
- 验收标准:
  - 支持事件发布订阅
  - 支持事件过滤
  - 支持异步事件处理

#### FR3: Action交易层

**FR3.1 语义化交易方法**
- 需求描述: 提供语义化的交易方法
- 优先级: 高
- 验收标准:
  - 支持buy_open/buy_close方法
  - 支持sell_open/sell_close方法
  - 支持期货风格的交易指令

**FR3.2 滑点控制**
- 需求描述: 内置滑点处理机制
- 优先级: 中
- 验收标准:
  - 支持买入/卖出分别设置滑点
  - 支持按合约设置滑点
  - 支持滑点开关

**FR3.3 智能平仓**
- 需求描述: 实现智能平仓逻辑
- 优先级: 中
- 验收标准:
  - 自动处理平今/平昨
  - 支持优先平今/平昨配置
  - 支持交易所规则配置

#### FR4: 数据中心

**FR4.1 统一数据访问**
- 需求描述: 建立统一的数据访问接口
- 优先级: 高
- 验收标准:
  - 提供center对象访问所有数据
  - 支持数据订阅
  - 支持数据查询

**FR4.2 数据录制**
- 需求描述: 实现行情数据的自动录制
- 优先级: 中
- 验收标准:
  - 支持Tick数据录制
  - 支持K线数据录制
  - 支持订单/成交数据录制
  - 支持录制到文件/数据库

**FR4.3 数据回放**
- 需求描述: 实现录制数据的回放功能
- 优先级: 中
- 验收标准:
  - 支持从文件回放
  - 支持从数据库回放
  - 支持回放速度控制

#### FR5: 信号系统

**FR5.1 信号定义**
- 需求描述: 定义标准信号类型
- 优先级: 高
- 验收标准:
  - 定义市场数据信号
  - 定义交易信号
  - 定义账户信号

**FR5.2 信号订阅**
- 需求描述: 实现信号的订阅机制
- 优先级: 高
- 验收标准:
  - 支持函数订阅
  - 支持方法订阅
  - 支持一次性订阅

**FR5.3 信号分发**
- 需求描述: 实现信号的分发机制
- 优先级: 中
- 验收标准:
  - 支持同步分发
  - 支持异步分发
  - 支持信号优先级

#### FR6: CTP接口封装

**FR6.1 CTP网关**
- 需求描述: 实现CTP接口的完整封装
- 优先级: 高
- 验收标准:
  - 支持CTP行情接口
  - 支持CTP交易接口
  - 支持CTP Mini接口

**FR6.2 接口适配器**
- 需求描述: 实现接口适配器模式
- 优先级: 中
- 验收标准:
  - 定义网关抽象接口
  - 支持多网关切换
  - 支持网关配置

### 非功能需求

#### NFR1: 性能
- 信号分发延迟 < 1ms
- 数据写入延迟 < 10ms
- 扩展加载时间 < 100ms

#### NFR2: 兼容性
- 保持与现有backtrader API兼容
- 支持Python 3.7+
- 支持Windows/Linux/MacOS

#### NFR3: 可扩展性
- 新增扩展无需修改核心代码
- 支持自定义信号类型
- 支持自定义数据存储

---

## 设计文档

### 整体架构设计

#### 新增模块结构

```
backtrader/
├── backtrader/
│   ├── core/              # 新增：核心抽象层
│   │   ├── __init__.py
│   │   ├── app.py         # 应用上下文
│   │   ├── config.py      # 配置管理
│   │   └── context.py     # 上下文管理
│   ├── extensions/        # 新增：扩展系统
│   │   ├── __init__.py
│   │   ├── base.py        # 扩展基类
│   │   ├── manager.py     # 扩展管理器
│   │   └── events.py      # 事件系统
│   ├── signals/           # 新增：信号系统
│   │   ├── __init__.py
│   │   ├── signal.py      # 信号定义
│   │   ├── dispatcher.py  # 信号分发器
│   │   └── bus.py         # 信号总线
│   ├── trading/           # 新增：交易层
│   │   ├── __init__.py
│   │   ├── action.py      # Action交易层
│   │   ├── slippage.py    # 滑点控制
│   │   └── position.py    # 持仓管理
│   ├── data/              # 新增：数据中心
│   │   ├── __init__.py
│   │   ├── center.py      # 数据中心
│   │   ├── recorder.py    # 数据录制
│   │   └── replayer.py    # 数据回放
│   ├── gateways/          # 新增：网关层
│   │   ├── __init__.py
│   │   ├── base.py        # 网关基类
│   │   ├── ctp.py         # CTP网关
│   │   ├── ctp_mini.py    # CTP Mini网关
│   │   └── adapter.py     # 网关适配器
│   └── utils/
│       └── decorators.py  # 装饰器
```

### 详细设计

#### 1. 应用上下文管理

**1.1 应用类**

```python
# backtrader/core/app.py
from typing import Dict, Optional, Callable
from .config import Config
from .context import AppContext

class CerebroApp:
    """类Flask风格的应用类"""

    def __init__(self, import_name: str, config: Optional[Dict] = None):
        self.import_name = import_name
        self.config = Config(config or {})
        self._context = AppContext(self)
        self.extensions = {}

    def with_config(self, config: Dict):
        """链式配置"""
        self.config.update(config)
        return self

    def from_object(self, obj):
        """从对象加载配置"""
        if isinstance(obj, str):
            obj = self._import_object(obj)
        for key in dir(obj):
            if key.isupper():
                self.config[key] = getattr(obj, key)
        return self

    def add_extension(self, extension):
        """添加扩展"""
        if isinstance(extension, type):
            extension = extension()
        extension.init_app(self)
        self.extensions[extension.name] = extension
        return self

    def with_extensions(self, *extensions):
        """链式添加多个扩展"""
        for ext in extensions:
            self.add_extension(ext)
        return self

    def run(self):
        """运行应用"""
        # 初始化所有扩展
        for ext in self.extensions.values():
            ext.on_init()
        # 启动回测/实盘
        return self._run_strategy()

    def app_context(self):
        """应用上下文管理器"""
        return self._context

    def __enter__(self):
        self._context.push()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._context.pop()
```

**1.2 配置类**

```python
# backtrader/core/config.py
from typing import Dict, Any
import json
import os

class Config(dict):
    """配置管理类"""

    def __init__(self, defaults: Dict = None):
        super().__init__(defaults or {})

    def from_mapping(self, mapping: Dict[str, Any]):
        """从字典加载配置"""
        self.update(mapping)
        return self

    def from_json(self, filename: str):
        """从JSON文件加载配置"""
        with open(filename, 'r', encoding='utf-8') as f:
            self.update(json.load(f))
        return self

    def from_pyfile(self, filename: str):
        """从Python文件加载配置"""
        d = {}
        with open(filename, 'r', encoding='utf-8') as f:
            exec(compile(f.read(), filename, 'exec'), d)
        for key, value in d.items():
            if key.isupper():
                self[key] = value
        return self

    def from_env(self, prefix: str = 'BT_'):
        """从环境变量加载配置"""
        for key, value in os.environ.items():
            if key.startswith(prefix):
                config_key = key[len(prefix):]
                self[config_key] = value
        return self

    def get_bool(self, key: str, default: bool = False) -> bool:
        """获取布尔配置"""
        value = self.get(key, default)
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return bool(value)
```

**1.3 上下文管理**

```python
# backtrader/core/context.py
from typing import Dict, Any

class AppContext:
    """应用上下文"""

    def __init__(self, app):
        self.app = app
        self._data = {}

    def push(self):
        """推入上下文栈"""
        _context_stack.push(self)

    def pop(self):
        """弹出上下文栈"""
        _context_stack.pop()

    @property
    def data(self) -> Dict[str, Any]:
        """上下文数据"""
        return self._data

    def get(self, key: str, default=None):
        """获取上下文变量"""
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        """设置上下文变量"""
        self._data[key] = value

class _ContextStack:
    """上下文栈"""

    def __init__(self):
        self._stack = []

    def push(self, ctx: AppContext):
        self._stack.append(ctx)

    def pop(self):
        if self._stack:
            return self._stack.pop()
        return None

    @property
    def top(self) -> Optional[AppContext]:
        if self._stack:
            return self._stack[-1]
        return None

_context_stack = _ContextStack()

def current_app:
    """获取当前应用"""
    return _context_stack.top.app if _context_stack.top else None
```

#### 2. 扩展机制

**2.1 扩展基类**

```python
# backtrader/extensions/base.py
from abc import ABC, abstractmethod

class ExtensionBase(ABC):
    """扩展基类"""

    name: str = None

    def __init__(self):
        self.app = None

    def init_app(self, app):
        """初始化扩展"""
        self.app = app

    def on_init(self):
        """应用初始化时调用"""
        pass

    def on_start(self):
        """应用启动时调用"""
        pass

    def on_stop(self):
        """应用停止时调用"""
        pass

    def on_tick(self, tick):
        """Tick数据"""
        pass

    def on_bar(self, bar):
        """K线数据"""
        pass

    def on_order(self, order):
        """订单事件"""
        pass

    def on_trade(self, trade):
        """成交事件"""
        pass

    def on_position(self, position):
        """持仓事件"""
        pass

    def on_account(self, account):
        """账户事件"""
        pass
```

**2.2 扩展管理器**

```python
# backtrader/extensions/manager.py
from typing import Dict, List
from .base import ExtensionBase
from ..signals.dispatcher import SignalDispatcher

class ExtensionManager:
    """扩展管理器"""

    def __init__(self):
        self._extensions: Dict[str, ExtensionBase] = {}
        self._dispatcher = SignalDispatcher()

    def add(self, extension: ExtensionBase) -> 'ExtensionManager':
        """添加扩展"""
        self._extensions[extension.name] = extension
        return self

    def remove(self, name: str) -> bool:
        """移除扩展"""
        if name in self._extensions:
            del self._extensions[name]
            return True
        return False

    def enable(self, name: str) -> bool:
        """启用扩展"""
        if name in self._extensions:
            self._extensions[name].on_start()
            return True
        return False

    def disable(self, name: str) -> bool:
        """禁用扩展"""
        if name in self._extensions:
            self._extensions[name].on_stop()
            return True
        return False

    def get(self, name: str) -> ExtensionBase:
        """获取扩展"""
        return self._extensions.get(name)

    def dispatch(self, event: str, data):
        """分发事件到所有扩展"""
        method_name = f'on_{event}'
        for ext in self._extensions.values():
            method = getattr(ext, method_name, None)
            if method:
                method(data)

    def __iter__(self):
        return iter(self._extensions.values())
```

#### 3. 信号系统

**3.1 信号定义**

```python
# backtrader/signals/signal.py
from enum import Enum
from dataclasses import dataclass

class SignalType(Enum):
    """信号类型"""
    # 市场数据信号
    TICK = 'tick'
    BAR = 'bar'
    BAR_OPENED = 'bar_opened'
    BAR_CLOSED = 'bar_closed'

    # 交易信号
    ORDER_SUBMITTED = 'order_submitted'
    ORDER_ACCEPTED = 'order_accepted'
    ORDER_REJECTED = 'order_rejected'
    ORDER_COMPLETED = 'order_completed'
    ORDER_CANCELLED = 'order_cancelled'

    TRADE_OPENED = 'trade_opened'
    TRADE_CLOSED = 'trade_closed'

    # 账户信号
    ACCOUNT_UPDATE = 'account_update'
    POSITION_UPDATE = 'position_update'

    # 应用信号
    APP_INIT = 'app_init'
    APP_START = 'app_start'
    APP_STOP = 'app_stop'

@dataclass
class Signal:
    """信号对象"""
    type: SignalType
    data: Any
    timestamp: float = None
    source: str = None
```

**3.2 信号分发器**

```python
# backtrader/signals/dispatcher.py
from typing import Callable, Dict, List, Set
from .signal import Signal, SignalType
import asyncio

class SignalDispatcher:
    """信号分发器"""

    def __init__(self):
        self._subscribers: Dict[SignalType, List[Callable]] = {}
        self._one_time: Dict[SignalType, List[Callable]] = {}
        self._async_mode = False
        self._loop = None

    def subscribe(self, signal_type: SignalType, callback: Callable):
        """订阅信号"""
        if signal_type not in self._subscribers:
            self._subscribers[signal_type] = []
        self._subscribers[signal_type].append(callback)
        return callback

    def subscribe_once(self, signal_type: SignalType, callback: Callable):
        """订阅一次性信号"""
        if signal_type not in self._one_time:
            self._one_time[signal_type] = []
        self._one_time[signal_type].append(callback)
        return callback

    def unsubscribe(self, signal_type: SignalType, callback: Callable):
        """取消订阅"""
        if signal_type in self._subscribers:
            self._subscribers[signal_type].remove(callback)

    def emit(self, signal_type: SignalType, data=None):
        """发送信号"""
        signal = Signal(type=signal_type, data=data)

        # 处理普通订阅
        if signal_type in self._subscribers:
            for callback in self._subscribers[signal_type]:
                self._call_callback(callback, signal)

        # 处理一次性订阅
        if signal_type in self._one_time:
            for callback in self._one_time[signal_type]:
                self._call_callback(callback, signal)
            del self._one_time[signal_type]

    def _call_callback(self, callback: Callable, signal: Signal):
        """调用回调函数"""
        if self._async_mode:
            asyncio.create_task(callback(signal))
        else:
            callback(signal)

    def set_async_mode(self, enabled: bool):
        """设置异步模式"""
        self._async_mode = enabled

# 全局信号总线
signal_bus = SignalDispatcher()
```

#### 4. Action交易层

**4.1 Action基类**

```python
# backtrader/trading/action.py
from enum import Enum
from .slippage import SlippageController

class OrderType(Enum):
    """订单类型"""
    MARKET = 'market'      # 市价单
    LIMIT = 'limit'        # 限价单
    STOP = 'stop'          # 止损单
    FAK = 'fak'            # FAK (Fill and Kill)
    FOK = 'fok'            # FOK (Fill or Kill)

class ActionLayer:
    """交易动作层"""

    def __init__(self, app):
        self.app = app
        self.slippage = SlippageController(app.config)

    def buy_open(self, symbol: str, price: float, volume: int,
                 order_type: OrderType = OrderType.LIMIT, **kwargs):
        """开多"""
        price = self.slippage.apply_buy_slippage(symbol, price)
        return self._send_order(symbol, 'buy_open', price, volume, order_type, **kwargs)

    def sell_close(self, symbol: str, price: float, volume: int,
                  order_type: OrderType = OrderType.LIMIT, **kwargs):
        """平多"""
        price = self.slippage.apply_sell_slippage(symbol, price)
        return self._send_order(symbol, 'sell_close', price, volume, order_type, **kwargs)

    def sell_open(self, symbol: str, price: float, volume: int,
                  order_type: OrderType = OrderType.LIMIT, **kwargs):
        """开空"""
        price = self.slippage.apply_sell_slippage(symbol, price)
        return self._send_order(symbol, 'sell_open', price, volume, order_type, **kwargs)

    def buy_close(self, symbol: str, price: float, volume: int,
                  order_type: OrderType = OrderType.LIMIT, **kwargs):
        """平空"""
        price = self.slippage.apply_buy_slippage(symbol, price)
        return self._send_order(symbol, 'buy_close', price, volume, order_type, **kwargs)

    # 别名方法
    def buy(self, symbol: str, price: float, volume: int, **kwargs):
        """买入（开多）"""
        return self.buy_open(symbol, price, volume, **kwargs)

    def short(self, symbol: str, price: float, volume: int, **kwargs):
        """做空（开空）"""
        return self.sell_open(symbol, price, volume, **kwargs)

    def sell(self, symbol: str, price: float, volume: int, **kwargs):
        """卖出（平多/平空根据持仓判断）"""
        return self._smart_close(symbol, price, volume, **kwargs)

    def cover(self, symbol: str, price: float, volume: int, **kwargs):
        """平空"""
        return self.buy_close(symbol, price, volume, **kwargs)

    def _smart_close(self, symbol: str, price: float, volume: int, **kwargs):
        """智能平仓"""
        position = self.app.center.get_position(symbol)
        if position.long_volume > 0:
            return self.sell_close(symbol, price, volume, **kwargs)
        elif position.short_volume > 0:
            return self.buy_close(symbol, price, volume, **kwargs)
        else:
            raise ValueError(f"No position for {symbol}")

    def _send_order(self, symbol: str, direction: str, price: float,
                    volume: int, order_type: OrderType, **kwargs):
        """发送订单"""
        order_req = {
            'symbol': symbol,
            'direction': direction,
            'price': price,
            'volume': volume,
            'order_type': order_type,
            **kwargs
        }
        return self.app.gateway.send_order(order_req)
```

**4.2 滑点控制**

```python
# backtrader/trading/slippage.py
from typing import Dict

class SlippageController:
    """滑点控制器"""

    def __init__(self, config):
        self.config = config
        self.buy_slippage = config.get('SLIPPAGE_BUY', 0)
        self.sell_slippage = config.get('SLIPPAGE_SELL', 0)
        self.symbol_slippage: Dict[str, Dict] = config.get('SYMBOL_SLIPPAGE', {})

    def apply_buy_slippage(self, symbol: str, price: float) -> float:
        """应用买入滑点"""
        slippage = self.symbol_slippage.get(symbol, {}).get('buy', self.buy_slippage)
        return price + slippage

    def apply_sell_slippage(self, symbol: str, price: float) -> float:
        """应用卖出滑点"""
        slippage = self.symbol_slippage.get(symbol, {}).get('sell', self.sell_slippage)
        return price - slippage
```

#### 5. 数据中心

**5.1 数据中心**

```python
# backtrader/data/center.py
from typing import Dict, List, Optional
from collections import defaultdict

class DataCenter:
    """数据中心"""

    def __init__(self):
        self._ticks: Dict[str, List] = defaultdict(list)
        self._bars: Dict[str, List] = defaultdict(list)
        self._orders: List = []
        self._trades: List = []
        self._positions: Dict[str, 'Position'] = {}
        self._account: Optional['Account'] = None

    def add_tick(self, tick):
        """添加Tick数据"""
        self._ticks[tick.symbol].append(tick)

    def add_bar(self, bar):
        """添加K线数据"""
        self._bars[bar.symbol].append(bar)

    def add_order(self, order):
        """添加订单"""
        self._orders.append(order)

    def add_trade(self, trade):
        """添加成交"""
        self._trades.append(trade)

    def update_position(self, position):
        """更新持仓"""
        self._positions[position.symbol] = position

    def update_account(self, account):
        """更新账户"""
        self._account = account

    def get_tick(self, symbol: str) -> Optional['Tick']:
        """获取最新Tick"""
        ticks = self._ticks.get(symbol)
        return ticks[-1] if ticks else None

    def get_bar(self, symbol: str) -> Optional['Bar']:
        """获取最新K线"""
        bars = self._bars.get(symbol)
        return bars[-1] if bars else None

    def get_position(self, symbol: str) -> Optional['Position']:
        """获取持仓"""
        return self._positions.get(symbol)

    @property
    def ticks(self) -> Dict[str, List]:
        """所有Tick数据"""
        return dict(self._ticks)

    @property
    def bars(self) -> Dict[str, List]:
        """所有K线数据"""
        return dict(self._bars)

    @property
    def orders(self) -> List:
        """所有订单"""
        return self._orders

    @property
    def trades(self) -> List:
        """所有成交"""
        return self._trades

    @property
    def positions(self) -> Dict[str, 'Position']:
        """所有持仓"""
        return dict(self._positions)

    @property
    def account(self) -> Optional['Account']:
        """账户信息"""
        return self._account
```

**5.2 数据录制器**

```python
# backtrader/data/recorder.py
import json
import sqlite3
from datetime import datetime
from pathlib import Path

class Recorder:
    """数据录制器"""

    def __init__(self, output_path: str):
        self.output_path = Path(output_path)
        self.recording = False
        self._db_conn = None

    def start(self):
        """开始录制"""
        self.recording = True
        if self.output_path.suffix == '.db':
            self._init_db()

    def stop(self):
        """停止录制"""
        self.recording = False
        if self._db_conn:
            self._db_conn.close()

    def record_tick(self, tick):
        """录制Tick"""
        if not self.recording:
            return
        if self._db_conn:
            self._save_tick_to_db(tick)
        else:
            self._save_tick_to_file(tick)

    def record_bar(self, bar):
        """录制K线"""
        if not self.recording:
            return
        if self._db_conn:
            self._save_bar_to_db(bar)
        else:
            self._save_bar_to_file(bar)

    def _init_db(self):
        """初始化数据库"""
        self._db_conn = sqlite3.connect(str(self.output_path))
        cursor = self._db_conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                datetime TEXT,
                last_price REAL,
                volume INTEGER,
                open_interest INTEGER,
                bid_price REAL,
                ask_price REAL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                datetime TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume INTEGER,
                open_interest INTEGER
            )
        ''')
        self._db_conn.commit()

    def _save_tick_to_db(self, tick):
        """保存Tick到数据库"""
        cursor = self._db_conn.cursor()
        cursor.execute('''
            INSERT INTO ticks (symbol, datetime, last_price, volume, open_interest, bid_price, ask_price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (tick.symbol, tick.datetime, tick.last_price, tick.volume,
              tick.open_interest, tick.bid_price, tick.ask_price))
        self._db_conn.commit()

    def _save_tick_to_file(self, tick):
        """保存Tick到文件"""
        with open(self.output_path / 'ticks.jsonl', 'a') as f:
            f.write(json.dumps({
                'symbol': tick.symbol,
                'datetime': tick.datetime.isoformat(),
                'last_price': tick.last_price,
                'volume': tick.volume,
                'open_interest': tick.open_interest,
                'bid_price': tick.bid_price,
                'ask_price': tick.ask_price
            }) + '\n')
```

#### 6. CTP网关

**6.1 网关基类**

```python
# backtrader/gateways/base.py
from abc import ABC, abstractmethod
from enum import Enum

class GatewayType(Enum):
    """网关类型"""
    CTP = 'ctp'
    CTP_MINI = 'ctp_mini'
    LOOPER = 'looper'
    LOCAL = 'local'

class Gateway(ABC):
    """网关基类"""

    @abstractmethod
    def connect(self, config: dict):
        """连接"""
        pass

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        pass

    @abstractmethod
    def subscribe_quote(self, symbols: List[str]):
        """订阅行情"""
        pass

    @abstractmethod
    def send_order(self, order_req: dict):
        """发送订单"""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str):
        """撤销订单"""
        pass

    @abstractmethod
    def query_account(self):
        """查询账户"""
        pass

    @abstractmethod
    def query_position(self, symbol: str = None):
        """查询持仓"""
        pass
```

**6.2 CTP网关**

```python
# backtrader/gateways/ctp.py
from .base import Gateway
from ...signals.signal import SignalType
from ...signals.dispatcher import signal_bus

class CTPGateway(Gateway):
    """CTP网关"""

    def __init__(self):
        self._md_api = None
        self._td_api = None
        self._connected = False

    def connect(self, config: dict):
        """连接CTP"""
        # 初始化行情API
        from ctpbee import MdApi
        self._md_api = MdApi()
        self._md_api.RegisterFront(config.get('md_address'))
        self._md_api.RegisterSpi(self._CTPMdSpi(self))
        self._md_api.Init()

        # 初始化交易API
        from ctpbee import TdApi
        self._td_api = TdApi()
        self._td_api.RegisterFront(config.get('td_address'))
        self._td_api.RegisterSpi(self._CTPTdSpi(self))
        self._td_api.Init()

        self._connected = True

    def disconnect(self):
        """断开连接"""
        if self._md_api:
            self._md_api.Release()
        if self._td_api:
            self._td_api.Release()
        self._connected = False

    def subscribe_quote(self, symbols: list):
        """订阅行情"""
        if self._md_api:
            self._md_api.SubscribeMarketData(symbols)

    def send_order(self, order_req: dict):
        """发送订单"""
        if not self._td_api:
            raise RuntimeError("TD API not connected")
        req = self._build_order_req(order_req)
        return self._td_api.ReqOrderInsert(req, 0)

    def cancel_order(self, order_id: str):
        """撤销订单"""
        if not self._td_api:
            raise RuntimeError("TD API not connected")
        req = self._build_cancel_req(order_id)
        return self._td_api.ReqOrderAction(req, 0)

    def query_account(self):
        """查询账户"""
        if self._td_api:
            self._td_api.ReqQryTradingAccount()

    def query_position(self, symbol: str = None):
        """查询持仓"""
        if self._td_api:
            req = {} if symbol is None else {'InstrumentID': symbol}
            self._td_api.ReqQryInvestorPosition(req)

    class _CTPMdSpi:
        """CTP行情回调"""
        def __init__(self, gateway):
            self.gateway = gateway

        def OnFrontConnected(self):
            """行情连接成功"""
            signal_bus.emit(SignalType.APP_START, {'type': 'md'})

        def OnRtnDepthMarketData(self, pDepthMarketData):
            """行情数据推送"""
            tick = self._parse_tick(pDepthMarketData)
            signal_bus.emit(SignalType.TICK, tick)

    class _CTPTdSpi:
        """CTP交易回调"""
        def __init__(self, gateway):
            self.gateway = gateway

        def OnFrontConnected(self):
            """交易连接成功"""
            signal_bus.emit(SignalType.APP_START, {'type': 'td'})

        def OnRtnOrder(self, pOrder):
            """订单回报"""
            order = self._parse_order(pOrder)
            signal_bus.emit(SignalType.ORDER_SUBMITTED, order)

        def OnRtnTrade(self, pTrade):
            """成交回报"""
            trade = self._parse_trade(pTrade)
            signal_bus.emit(SignalType.TRADE_OPENED, trade)
```

### 实现计划

#### 第一阶段：应用设计模式（优先级：高）
1. 实现CerebroApp应用类
2. 实现Config配置管理
3. 实现AppContext上下文管理

#### 第二阶段：信号系统（优先级：高）
1. 实现Signal信号定义
2. 实现SignalDispatcher信号分发器
3. 集成信号到Cerebro

#### 第三阶段：扩展机制（优先级：高）
1. 实现ExtensionBase基类
2. 实现ExtensionManager扩展管理器
3. 集成扩展到应用

#### 第四阶段：Action交易层（优先级：中）
1. 实现ActionLayer交易层
2. 实现SlippageController滑点控制
3. 实现智能平仓逻辑

#### 第五阶段：数据中心（优先级：中）
1. 实现DataCenter数据中心
2. 实现Recorder数据录制
3. 实现Replayer数据回放

#### 第六阶段：CTP网关（优先级：高）
1. 实现Gateway网关基类
2. 实现CTPGateway CTP网关
3. 集成网关到应用

### API兼容性保证

所有新增功能保持与现有backtrader API的兼容性：

1. **向后兼容**: 现有代码无需修改即可运行
2. **可选启用**: 新功能通过选择使用
3. **渐进增强**: 用户可以选择使用新功能或保持原有方式

```python
# 示例：传统方式（保持不变）
import backtrader as bt

cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(MyStrategy)
result = cerebro.run()

# 示例：新方式（可选）
from backtrader.core import CerebroApp
from backtrader.gateways import CTPGateway

app = CerebroApp('my_app')
app.config.from_mapping({
    'INTERFACE': 'ctp',
    'MD_ADDR': 'tcp://180.168.146.187:10131',
    'TD_ADDR': 'tcp://180.168.146.187:10130'
})
app.with_extensions(MyStrategy, RiskControl)
result = app.run()
```

### 使用示例

**策略扩展示例：**

```python
from backtrader.extensions.base import ExtensionBase

class MyStrategy(ExtensionBase):
    name = 'my_strategy'

    def on_init(self):
        print('策略初始化')
        self.data = self.app.center.get_tick('rb2205')

    def on_tick(self, tick):
        if self.should_buy(tick):
            self.app.action.buy_open(tick.symbol, tick.last_price, 1)

    def should_buy(self, tick):
        # 交易逻辑
        return True

# 使用
app = CerebroApp('my_app')
app.add_extension(MyStrategy())
app.run()
```

**信号订阅示例：**

```python
from backtrader.signals.dispatcher import signal_bus
from backtrader.signals.signal import SignalType

def on_tick_handler(signal):
    print(f"收到Tick: {signal.data}")

signal_bus.subscribe(SignalType.TICK, on_tick_handler)
```

### 测试策略

1. **单元测试**: 每个新增模块的单元测试覆盖率 > 80%
2. **集成测试**: 与现有功能的集成测试
3. **性能测试**: 信号分发延迟 < 1ms
4. **兼容性测试**: 确保现有代码无需修改即可运行
