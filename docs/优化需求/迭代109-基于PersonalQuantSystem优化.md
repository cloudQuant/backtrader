### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/PersonalQuantSystem
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### PersonalQuantSystem项目简介
PersonalQuantSystem是一个个人量化交易系统，具有以下核心特点：
- **个人系统**: 面向个人投资者
- **完整闭环**: 从研究到交易的闭环
- **策略管理**: 个人策略管理
- **资金管理**: 个人资金管理
- **风险控制**: 个人风控
- **简洁实用**: 简洁实用设计

### 重点借鉴方向
1. **个人量化**: 个人量化设计
2. **简洁性**: 简洁实用设计
3. **完整性**: 系统完整性
4. **易用性**: 用户友好设计
5. **资金管理**: 资金管理模块
6. **风控设计**: 个人风控设计

---

## 研究分析

### PersonalQuantSystem架构特点总结

通过对PersonalQuantSystem项目的深入研究，总结出以下核心架构特点：

#### 1. 统一的配置管理架构
```
配置层次结构:
├── 回测配置 (BacktestConfig)
│   ├── 数据源配置
│   ├── 策略参数配置
│   └── 性能分析配置
└── 实盘配置 (LiveConfig)
    ├── 券商接口配置
    ├── 账户配置
    └── 风险控制配置
```

**核心特性**:
- 单一配置文件(YAML)管理所有参数
- 回测与实盘配置分离但结构统一
- 支持动态配置更新和保存
- 配置验证和默认值处理

#### 2. 分层错误处理体系
```
异常层次:
TradingError (基类)
    ├── NotConnectError (连接错误)
    ├── InsufficientFundsError (资金不足)
    ├── StockSuspendedError (股票停牌)
    ├── NetworkError (网络错误)
    └── OrderError (订单错误)
```

**核心特性**:
- 自定义异常类体系
- 智能错误处理策略
- 用户友好的错误消息
- 错误回调机制

#### 3. 常量集中管理
```python
# 交易相关枚举
- OrderStatus: 订单状态
- TradeDirection: 交易方向
- OrderType: 订单类型

# 错误处理常量
- 错误类型映射
- 处理策略定义
- 用户友好消息

# 系统常量
- 最大重试次数
- 风险参数
- 涨跌停限制
```

#### 4. 模块化系统架构
```
PersonalQuantSystem/
├── libs/              # 核心库
│   ├── config/       # 配置管理
│   ├── core/         # 核心功能
│   ├── strategies/   # 策略库
│   └── utils/        # 工具函数
├── main.py           # 统一入口
└── config.yaml       # 配置文件
```

#### 5. 依赖注入模式
```python
# 容器管理依赖
container = Container()
container.register('config', config_manager)
container.register('logger', logger)
container.register('error_manager', error_manager)

# 获取依赖
error_manager = container.get('error_manager')
```

### Backtrader当前架构特点

#### 优势
- 成熟的事件驱动架构
- 完整的策略回测功能
- 丰富的技术指标库
- 灵活的数据源支持
- 良好的可视化功能

#### 局限性（针对个人量化系统）
1. **配置管理分散**: 参数定义在策略类中，缺乏统一配置
2. **错误处理简陋**: 主要依赖Python异常，缺少业务语义
3. **学习曲线陡峭**: 概念复杂，新手入门困难
4. **实盘对接复杂**: 需要额外适配实盘接口
5. **缺乏个人化**: 缺少面向个人投资者的友好设计

---

## 需求规格文档

### 1. 增强配置管理模块

#### 1.1 功能描述
提供统一的配置管理系统，支持YAML配置文件，实现回测与实盘配置的统一管理。

#### 1.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| CFG-001 | 支持YAML配置文件 | P0 |
| CFG-002 | 回测与实盘配置分离 | P0 |
| CFG-003 | 配置验证和默认值 | P0 |
| CFG-004 | 配置热更新 | P1 |
| CFG-005 | 配置加密存储 | P1 |
| CFG-006 | 多环境配置支持 | P2 |
| CFG-007 | 配置文件继承 | P2 |

#### 1.3 接口设计
```python
class ConfigManager:
    """配置管理器"""

    def __init__(self, config_path: str = None):
        """初始化配置管理器"""

    def load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        pass

    def save_config(self, config_path: str = None):
        """保存当前配置"""
        pass

    @property
    def is_backtest(self) -> bool:
        """是否为回测模式"""
        pass

    @property
    def backtest(self) -> BacktestConfig:
        """获取回测配置"""
        pass

    @property
    def live(self) -> LiveConfig:
        """获取实盘配置"""
        pass

    def get_strategy_config(self, strategy_name: str) -> dict:
        """获取策略配置"""
        pass

    def validate(self) -> List[str]:
        """验证配置，返回错误列表"""
        pass
```

### 2. 业务异常体系模块

#### 2.1 功能描述
建立具有业务语义的异常体系，提供清晰的错误分类和处理策略。

#### 2.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| ERR-001 | 定义交易异常基类 | P0 |
| ERR-002 | 定义连接异常 | P0 |
| ERR-003 | 定义资金异常 | P0 |
| ERR-004 | 定义订单异常 | P0 |
| ERR-005 | 定义数据异常 | P1 |
| ERR-006 | 定义策略异常 | P1 |
| ERR-007 | 错误处理策略 | P1 |
| ERR-008 | 用户友好错误消息 | P1 |

#### 2.3 异常类设计
```python
class TradingError(Exception):
    """交易错误基类"""
    def __init__(self, code: str, message: str, suggestion: str = None):
        self.code = code              # 错误代码
        self.message = message        # 错误消息
        self.suggestion = suggestion  # 处理建议

class NotConnectError(TradingError):
    """连接错误"""
    pass

class InsufficientFundsError(TradingError):
    """资金不足错误"""
    pass

class StockSuspendedError(TradingError):
    """股票停牌错误"""
    pass

class NetworkError(TradingError):
    """网络错误"""
    pass

class OrderError(TradingError):
    """订单错误"""
    pass

class DataError(TradingError):
    """数据错误"""
    pass

class StrategyError(TradingError):
    """策略错误"""
    pass
```

### 3. 常量管理模块

#### 3.1 功能描述
集中管理系统常量和枚举，提供统一的常量访问接口。

#### 3.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| CONST-001 | 订单状态枚举 | P0 |
| CONST-002 | 交易方向枚举 | P0 |
| CONST-003 | 订单类型枚举 | P0 |
| CONST-004 | 系统常量定义 | P1 |
| CONST-005 | 风险参数常量 | P1 |
| CONST-006 | 错误代码映射 | P1 |

#### 3.3 常量设计
```python
from enum import Enum

class OrderStatus(Enum):
    """订单状态枚举"""
    SUBMITTED = 'submitted'    # 已提交
    ACCEPTED = 'accepted'      # 已接受
    PARTIAL = 'partial'        # 部分成交
    FILLED = 'filled'          # 全部成交
    CANCELED = 'canceled'      # 已撤销
    REJECTED = 'rejected'      # 已拒绝
    EXPIRED = 'expired'        # 已过期

class TradeDirection(Enum):
    """交易方向枚举"""
    LONG = 'long'              # 做多
    SHORT = 'short'            # 做空

class OrderType(Enum):
    """订单类型枚举"""
    MARKET = 'market'          # 市价单
    LIMIT = 'limit'            # 限价单
    STOP = 'stop'              # 止损单
    STOP_LIMIT = 'stop_limit'  # 止损限价单

class SystemConsts:
    """系统常量"""
    MAX_RETRY = 3              # 最大重试次数
    REQUEST_TIMEOUT = 30       # 请求超时(秒)
    DEFAULT_CASH = 100000      # 默认初始资金
    COMMISSION = 0.0003        # 默认佣金率

class RiskConsts:
    """风险参数常量"""
    MAX_POSITION_RATIO = 0.3   # 最大单仓比例
    MAX_TOTAL_POSITION = 0.8   # 最大总仓位
    STOP_LOSS_RATIO = 0.05     # 默认止损比例
```

### 4. 输出管理模块

#### 4.1 功能描述
提供统一的输出管理接口，支持日志、表格、彩色输出等多种形式。

#### 4.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| OUT-001 | 统一日志接口 | P0 |
| OUT-002 | 表格输出支持 | P1 |
| OUT-003 | 彩色终端输出 | P1 |
| OUT-004 | 输出级别控制 | P0 |
| OUT-005 | 文件输出支持 | P1 |

#### 4.3 接口设计
```python
class OutputManager:
    """输出管理器"""

    def debug(self, message: str):
        """调试级别输出"""
        pass

    def info(self, message: str):
        """信息级别输出"""
        pass

    def warning(self, message: str):
        """警告级别输出"""
        pass

    def error(self, message: str):
        """错误级别输出"""
        pass

    def table(self, headers: List[str], rows: List[List[str]]):
        """表格输出"""
        pass

    def success(self, message: str):
        """成功消息输出"""
        pass
```

### 5. 个人化策略模块

#### 5.1 功能描述
提供面向个人投资者的简化策略开发接口，降低学习曲线。

#### 5.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| STRAT-001 | 简化策略基类 | P0 |
| STRAT-002 | 常用策略模板 | P1 |
| STRAT-003 | 策略配置化 | P1 |
| STRAT-004 | 策略快速测试 | P1 |
| STRAT-005 | 策略组合支持 | P2 |

#### 5.4 接口设计
```python
class SimpleStrategy(bt.Strategy):
    """简化策略基类"""

    # 可在配置文件中覆盖的参数
    params = (
        ('symbols', []),           # 交易品种
        ('position_size', 100),    # 固定仓位大小
        ('stop_loss', 0.05),       # 止损比例
        ('take_profit', 0.15),     # 止盈比例
    )

    def __init__(self):
        super().__init__()
        self.trades = []           # 交易记录
        self.entry_price = None    # 入场价格

    def buy_signal(self) -> bool:
        """买入信号（用户实现）"""
        return False

    def sell_signal(self) -> bool:
        """卖出信号（用户实现）"""
        return False

    def next(self):
        """策略主逻辑"""
        # 检查止损止盈
        if self.check_stop_loss():
            return
        if self.check_take_profit():
            return

        # 检查交易信号
        if not self.position:
            if self.buy_signal():
                self.enter_long()
        else:
            if self.sell_signal():
                self.exit_long()

    def enter_long(self):
        """开多仓"""
        size = self.p.position_size
        self.buy(size=size)
        self.entry_price = self.data.close[0]

    def exit_long(self):
        """平多仓"""
        self.close()

    def check_stop_loss(self) -> bool:
        """检查止损"""
        if self.position and self.entry_price:
            loss_ratio = (self.entry_price - self.data.close[0]) / self.entry_price
            if loss_ratio >= self.p.stop_loss:
                self.close()
                return True
        return False

    def check_take_profit(self) -> bool:
        """检查止盈"""
        if self.position and self.entry_price:
            profit_ratio = (self.data.close[0] - self.entry_price) / self.entry_price
            if profit_ratio >= self.p.take_profit:
                self.close()
                return True
        return False
```

### 6. 资金管理模块

#### 6.1 功能描述
提供面向个人投资者的资金管理功能，包括仓位计算、资金分配等。

#### 6.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| MONEY-001 | 固定仓位管理 | P0 |
| MONEY-002 | 百分比仓位管理 | P1 |
| MONEY-003 | 风险平价仓位 | P1 |
| MONEY-004 | 凯利公式仓位 | P2 |
| MONEY-005 | 资金曲线跟踪 | P1 |

#### 6.3 接口设计
```python
class PositionSizer:
    """仓位计算器基类"""

    def __call__(self, strategy) -> int:
        """计算仓位大小"""
        pass

class FixedAmount(PositionSizer):
    """固定金额仓位"""

    params = (('amount', 10000),)  # 固定金额

    def __call__(self, strategy) -> int:
        price = strategy.data.close[0]
        return int(self.p.amount / price)

class FixedPercent(PositionSizer):
    """固定百分比仓位"""

    params = (('percent', 0.1),)  # 资金百分比

    def __call__(self, strategy) -> int:
        value = strategy.broker.getvalue()
        price = strategy.data.close[0]
        amount = value * self.p.percent
        return int(amount / price)

class RiskPercent(PositionSizer):
    """风险百分比仓位（基于止损）"""

    params = (
        ('risk_percent', 0.02),  # 风险百分比
        ('stop_loss', 0.05),     # 止损比例
    )

    def __call__(self, strategy) -> int:
        value = strategy.broker.getvalue()
        price = strategy.data.close[0]
        risk_amount = value * self.p.risk_percent
        loss_per_share = price * self.p.stop_loss
        return int(risk_amount / loss_per_share)
```

### 7. 快速回测模块

#### 7.1 功能描述
提供简化的回测接口，支持快速策略测试。

#### 7.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| QB-001 | 一键回测接口 | P0 |
| QB-002 | 简化数据加载 | P0 |
| QB-003 | 自动性能分析 | P1 |
| QB-004 | 批量参数测试 | P1 |
| QB-005 | 快速可视化 | P1 |

#### 7.3 接口设计
```python
class QuickBacktest:
    """快速回测工具"""

    def __init__(self, initial_cash: float = 100000):
        """初始化回测"""
        self.cerebro = bt.Cerebro()
        self.cerebro.broker.setcash(initial_cash)
        self.results = None

    def add_data(self, data, name: str = None):
        """添加数据"""
        self.cerebro.adddata(data, name=name)
        return self

    def set_strategy(self, strategy_cls, **kwargs):
        """设置策略"""
        self.cerebro.addstrategy(strategy_cls, **kwargs)
        return self

    def add_analyzer(self, analyzer_cls, **kwargs):
        """添加分析器"""
        self.cerebro.addanalyzer(analyzer_cls, **kwargs)
        return self

    def run(self):
        """运行回测"""
        self.results = self.cerebro.run()
        return self

    def get_metrics(self) -> dict:
        """获取回测指标"""
        if not self.results:
            return {}

        strat = self.results[0]
        return {
            'final_value': self.cerebro.broker.getvalue(),
            'return': (self.cerebro.broker.getvalue() / self.cerebro.broker.starting_cash) - 1,
            'trades': len(strat.trades) if hasattr(strat, 'trades') else 0,
        }

# 使用示例
def quick_test(strategy_class, data, **params):
    """快速测试函数"""
    result = (QuickBacktest()
              .add_data(data)
              .set_strategy(strategy_class, **params)
              .add_analyzer(bt.analyzers.SharpeRatio)
              .add_analyzer(bt.analyzers.DrawDown)
              .run())

    return result.get_metrics()
```

---

## 设计文档

### 整体架构设计

#### 1. 目录结构
```
backtrader/
├── personal/                # 个人量化模块
│   ├── __init__.py
│   ├── config/              # 配置管理
│   │   ├── __init__.py
│   │   ├── manager.py       # 配置管理器
│   │   ├── models.py        # 配置模型
│   │   └── validators.py    # 配置验证
│   ├── errors/              # 异常体系
│   │   ├── __init__.py
│   │   ├── base.py          # 基础异常
│   │   ├── trading.py       # 交易异常
│   │   ├── network.py       # 网络异常
│   │   └── data.py          # 数据异常
│   ├── constants/           # 常量定义
│   │   ├── __init__.py
│   │   ├── enums.py         # 枚举定义
│   │   └── values.py        # 常量值
│   ├── output/              # 输出管理
│   │   ├── __init__.py
│   │   ├── manager.py       # 输出管理器
│   │   └── formatters.py    # 格式化器
│   ├── strategies/          # 简化策略
│   │   ├── __init__.py
│   │   ├── base.py          # 策略基类
│   │   ├── templates.py     # 策略模板
│   │   └── signals.py       # 信号生成器
│   ├── money/               # 资金管理
│   │   ├── __init__.py
│   │   ├── position.py      # 仓位计算
│   │   └── risk.py          # 风险控制
│   └── quick/               # 快速工具
│       ├── __init__.py
│       ├── backtest.py      # 快速回测
│       └── compare.py       # 策略对比
│
└── utils/                   # 工具模块
    ├── __init__.py
    └── container.py         # 依赖注入容器
```

### 详细设计

#### 1. 配置管理器设计

```python
# personal/config/manager.py
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

@dataclass
class BacktestConfig:
    """回测配置"""
    initial_cash: float = 100000
    commission: float = 0.0003
    slippage: float = 0.0
    start_date: str = None
    end_date: str = None

@dataclass
class LiveConfig:
    """实盘配置"""
    broker: str = 'miniqmt'
    account: str = None
    password: str = None
    server: str = 'localhost'

@dataclass
class RiskConfig:
    """风险配置"""
    max_position_ratio: float = 0.3
    max_total_position: float = 0.8
    stop_loss_ratio: float = 0.05
    max_drawdown: float = 0.2

class ConfigManager:
    """配置管理器

    提供统一的配置管理接口，支持YAML配置文件。
    """

    def __init__(self, config_path: str = None):
        """初始化配置管理器

        Args:
            config_path: 配置文件路径
        """
        self._config_path = config_path
        self._config: Dict[str, Any] = {}
        self._mode: str = 'backtest'  # backtest or live

        if config_path:
            self.load_config(config_path)

    def load_config(self, config_path: str) -> Dict[str, Any]:
        """加载配置文件

        Args:
            config_path: 配置文件路径(YAML)

        Returns:
            配置字典
        """
        config_file = Path(config_path)

        if not config_file.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_file, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

        # 自动检测模式
        self._mode = self._config.get('mode', 'backtest')

        return self._config

    def save_config(self, config_path: str = None):
        """保存配置到文件

        Args:
            config_path: 保存路径，默认使用原路径
        """
        path = config_path or self._config_path
        if not path:
            raise ValueError("未指定配置文件路径")

        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(self._config, f, allow_unicode=True)

    @property
    def is_backtest(self) -> bool:
        """是否为回测模式"""
        return self._mode == 'backtest'

    @property
    def backtest(self) -> BacktestConfig:
        """获取回测配置"""
        if 'backtest' not in self._config:
            self._config['backtest'] = {}
        return BacktestConfig(**self._config.get('backtest', {}))

    @property
    def live(self) -> LiveConfig:
        """获取实盘配置"""
        if 'live' not in self._config:
            self._config['live'] = {}
        return LiveConfig(**self._config.get('live', {}))

    @property
    def risk(self) -> RiskConfig:
        """获取风险配置"""
        if 'risk' not in self._config:
            self._config['risk'] = {}
        return RiskConfig(**self._config.get('risk', {}))

    def get_strategy_config(self, strategy_name: str) -> Dict[str, Any]:
        """获取策略配置

        Args:
            strategy_name: 策略名称

        Returns:
            策略配置字典
        """
        strategies = self._config.get('strategies', {})
        return strategies.get(strategy_name, {})

    def validate(self) -> List[str]:
        """验证配置

        Returns:
            错误消息列表，空列表表示无错误
        """
        errors = []

        # 验证基本配置
        if self.is_backtest:
            if not self._config.get('backtest', {}).get('initial_cash'):
                errors.append("回测模式需要设置initial_cash")
        else:
            if not self._config.get('live', {}).get('broker'):
                errors.append("实盘模式需要设置broker")

        # 验证风险配置
        risk = self._config.get('risk', {})
        max_pos = risk.get('max_position_ratio', 0.3)
        if max_pos <= 0 or max_pos > 1:
            errors.append("max_position_ratio必须在(0, 1]范围内")

        return errors

    def get(self, key: str, default=None):
        """获取配置值

        Args:
            key: 配置键，支持点分隔的路径
            default: 默认值

        Returns:
            配置值
        """
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any):
        """设置配置值

        Args:
            key: 配置键，支持点分隔的路径
            value: 配置值
        """
        keys = key.split('.')
        config = self._config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value
```

#### 2. 异常体系设计

```python
# personal/errors/base.py
from typing import Optional, Dict

class TradingError(Exception):
    """交易错误基类

    所有交易相关异常的父类，提供统一的错误信息格式。
    """

    # 错误代码映射
    ERROR_CODES = {
        'NOT_CONNECT': 'E001',
        'INSUFFICIENT_FUNDS': 'E002',
        'STOCK_SUSPENDED': 'E003',
        'NETWORK_ERROR': 'E004',
        'ORDER_ERROR': 'E005',
        'DATA_ERROR': 'E006',
        'STRATEGY_ERROR': 'E007',
    }

    # 用户友好消息
    USER_MESSAGES = {
        'NOT_CONNECT': '无法连接到交易服务器，请检查网络连接',
        'INSUFFICIENT_FUNDS': '账户资金不足，请减少交易数量或入金',
        'STOCK_SUSPENDED': '股票已停牌，当前无法交易',
        'NETWORK_ERROR': '网络请求失败，请稍后重试',
        'ORDER_ERROR': '订单提交失败，请检查订单参数',
        'DATA_ERROR': '数据获取失败，请检查数据源配置',
        'STRATEGY_ERROR': '策略执行出错，请检查策略逻辑',
    }

    def __init__(self, error_type: str, detail: str = None, suggestion: str = None):
        """初始化交易异常

        Args:
            error_type: 错误类型
            detail: 详细信息
            suggestion: 处理建议
        """
        self.error_type = error_type
        self.code = self.ERROR_CODES.get(error_type, 'E999')
        self.message = self.USER_MESSAGES.get(error_type, '未知错误')
        self.detail = detail
        self.suggestion = suggestion or self._get_default_suggestion(error_type)

        # 构建完整错误消息
        full_msg = f"[{self.code}] {self.message}"
        if detail:
            full_msg += f": {detail}"
        if suggestion:
            full_msg += f"\n建议: {suggestion}"

        super().__init__(full_msg)

    def _get_default_suggestion(self, error_type: str) -> Optional[str]:
        """获取默认处理建议"""
        suggestions = {
            'NOT_CONNECT': '1. 检查网络连接\n2. 确认服务器地址正确\n3. 尝试重新连接',
            'INSUFFICIENT_FUNDS': '1. 减少交易数量\n2. 检查账户余额\n3. 考虑降低仓位',
            'NETWORK_ERROR': '1. 检查网络连接\n2. 稍后重试\n3. 联系服务商',
        }
        return suggestions.get(error_type)

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {
            'code': self.code,
            'type': self.error_type,
            'message': self.message,
            'detail': self.detail,
            'suggestion': self.suggestion,
        }

# personal/errors/trading.py
from .base import TradingError

class NotConnectError(TradingError):
    """连接错误"""
    def __init__(self, detail: str = None):
        super().__init__('NOT_CONNECT', detail)

class InsufficientFundsError(TradingError):
    """资金不足错误"""
    def __init__(self, detail: str = None):
        super().__init__('INSUFFICIENT_FUNDS', detail)

class StockSuspendedError(TradingError):
    """股票停牌错误"""
    def __init__(self, symbol: str = None):
        detail = f"股票 {symbol} 已停牌" if symbol else None
        super().__init__('STOCK_SUSPENDED', detail)

class OrderError(TradingError):
    """订单错误"""
    def __init__(self, detail: str = None):
        super().__init__('ORDER_ERROR', detail)

# personal/errors/network.py
from .base import TradingError

class NetworkError(TradingError):
    """网络错误"""
    def __init__(self, detail: str = None):
        super().__init__('NETWORK_ERROR', detail)

# personal/errors/data.py
from .base import TradingError

class DataError(TradingError):
    """数据错误"""
    def __init__(self, detail: str = None):
        super().__init__('DATA_ERROR', detail)

# personal/errors/strategy.py
from .base import TradingError

class StrategyError(TradingError):
    """策略错误"""
    def __init__(self, detail: str = None):
        super().__init__('STRATEGY_ERROR', detail)
```

#### 3. 输出管理器设计

```python
# personal/output/manager.py
import sys
from typing import List
from datetime import datetime

class OutputManager:
    """输出管理器

    提供统一的输出接口，支持多种输出格式和级别。
    """

    # ANSI颜色代码
    COLORS = {
        'red': '\033[91m',
        'green': '\033[92m',
        'yellow': '\033[93m',
        'blue': '\033[94m',
        'reset': '\033[0m',
    }

    def __init__(self, verbose: bool = True, use_color: bool = True):
        """初始化输出管理器

        Args:
            verbose: 是否输出详细信息
            use_color: 是否使用彩色输出
        """
        self.verbose = verbose
        self.use_color = use_color and self._supports_color()

    def _supports_color(self) -> bool:
        """检测终端是否支持彩色"""
        try:
            import curses
            curses.setupterm()
            return curses.tigetnum('colors') > 0
        except:
            return False

    def _colorize(self, text: str, color: str) -> str:
        """给文本添加颜色

        Args:
            text: 文本内容
            color: 颜色名称

        Returns:
            彩色文本
        """
        if not self.use_color:
            return text

        color_code = self.COLORS.get(color, '')
        reset_code = self.COLORS['reset']
        return f"{color_code}{text}{reset_code}"

    def _format_time(self) -> str:
        """格式化时间戳"""
        return datetime.now().strftime('%H:%M:%S')

    def debug(self, message: str):
        """调试级别输出"""
        if self.verbose:
            time_str = self._colorize(self._format_time(), 'blue')
            msg = f"[DEBUG] {time_str} {message}"
            print(msg, file=sys.stderr)

    def info(self, message: str):
        """信息级别输出"""
        print(f"{message}")

    def warning(self, message: str):
        """警告级别输出"""
        msg = self._colorize(f"[WARNING] {message}", 'yellow')
        print(msg, file=sys.stderr)

    def error(self, message: str):
        """错误级别输出"""
        msg = self._colorize(f"[ERROR] {message}", 'red')
        print(msg, file=sys.stderr)

    def success(self, message: str):
        """成功消息输出"""
        msg = self._colorize(f"[OK] {message}", 'green')
        print(msg)

    def table(self, headers: List[str], rows: List[List[str]]):
        """表格输出

        Args:
            headers: 表头
            rows: 数据行
        """
        try:
            from terminaltables3 import AsciiTable
            table_data = [headers] + rows
            table = AsciiTable(table_data)
            print(table.table)
        except ImportError:
            # 简单表格输出
            # 计算列宽
            col_widths = [len(h) for h in headers]
            for row in rows:
                for i, cell in enumerate(row):
                    col_widths[i] = max(col_widths[i], len(str(cell)))

            # 打印分隔线
            separator = '+'.join('-' * (w + 2) for w in col_widths)
            print(separator)

            # 打印表头
            header_row = '|'.join(f' {h:<{col_widths[i]}} ' for i, h in enumerate(headers))
            print(f"|{header_row}|")
            print(separator)

            # 打印数据行
            for row in rows:
                data_row = '|'.join(f' {str(cell):<{col_widths[i]}} ' for i, cell in enumerate(row))
                print(f"|{data_row}|")
            print(separator)

    def progress(self, current: int, total: int, prefix: str = ''):
        """进度条输出

        Args:
            current: 当前值
            total: 总值
            prefix: 前缀文本
        """
        percent = (current / total) * 100 if total > 0 else 0
        bar_length = 40
        filled = int(bar_length * current / total) if total > 0 else 0
        bar = '█' * filled + '░' * (bar_length - filled)

        print(f"\r{prefix} [{bar}] {percent:.1f}% ({current}/{total})", end='', flush=True)

        if current >= total:
            print()  # 完成后换行
```

#### 4. 简化策略基类设计

```python
# personal/strategies/base.py
import backtrader as bt
from typing import Callable, Optional

class SimpleStrategy(bt.Strategy):
    """简化策略基类

    面向个人投资者的简化策略开发接口。
    """

    # 默认参数
    params = (
        ('symbols', []),           # 交易品种列表
        ('position_size', 100),    # 固定仓位大小
        ('position_pct', 0.95),    # 资金使用比例
        ('stop_loss', 0.05),       # 止损比例
        ('take_profit', 0.15),     # 止盈比例
        ('trailing_stop', 0.0),    # 移动止损比例
    )

    def __init__(self):
        super().__init__()

        # 交易记录
        self.trades = []
        self.entry_price = None
        self.entry_date = None
        self.highest_since_entry = None

    def next(self):
        """策略主逻辑

        自动处理止损止盈，用户只需实现买卖信号。
        """
        # 更新最高价（用于移动止损）
        if self.position and self.highest_since_entry is not None:
            self.highest_since_entry = max(
                self.highest_since_entry,
                self.data.close[0]
            )

        # 检查止损止盈
        if self.position:
            if self.check_stop_loss():
                return
            if self.check_take_profit():
                return

        # 检查交易信号
        if not self.position:
            if self.buy_signal():
                self.enter_long()
        else:
            if self.sell_signal():
                self.exit_long()

    def buy_signal(self) -> bool:
        """买入信号

        子类需要实现此方法来定义买入条件。

        Returns:
            是否产生买入信号
        """
        return False

    def sell_signal(self) -> bool:
        """卖出信号

        子类需要实现此方法来定义卖出条件。

        Returns:
            是否产生卖出信号
        """
        return False

    def enter_long(self):
        """开多仓"""
        # 计算仓位大小
        if self.p.position_size > 0:
            size = self.p.position_size
        else:
            # 按资金比例计算
            cash = self.broker.getcash()
            price = self.data.close[0]
            size = int((cash * self.p.position_pct) / price)

        if size > 0:
            self.buy(size=size)
            self.entry_price = self.data.close[0]
            self.entry_date = len(self)
            self.highest_since_entry = self.entry_price

    def exit_long(self):
        """平多仓"""
        if self.position:
            self.close()
            self.entry_price = None
            self.entry_date = None
            self.highest_since_entry = None

    def check_stop_loss(self) -> bool:
        """检查止损

        Returns:
            是否触发止损
        """
        if not self.position or not self.entry_price:
            return False

        current_price = self.data.close[0]

        # 固定止损
        loss_ratio = (self.entry_price - current_price) / self.entry_price
        if loss_ratio >= self.p.stop_loss:
            self.close()
            return True

        # 移动止损
        if self.p.trailing_stop > 0 and self.highest_since_entry:
            trailing_stop_price = self.highest_since_entry * (1 - self.p.trailing_stop)
            if current_price < trailing_stop_price:
                self.close()
                return True

        return False

    def check_take_profit(self) -> bool:
        """检查止盈

        Returns:
            是否触发止盈
        """
        if not self.position or not self.entry_price:
            return False

        profit_ratio = (self.data.close[0] - self.entry_price) / self.entry_price

        if profit_ratio >= self.p.take_profit:
            self.close()
            return True

        return False

    def notify_trade(self, trade):
        """交易完成通知"""
        if trade.isclosed:
            self.trades.append({
                'entry_date': self.entry_date,
                'exit_date': len(self),
                'entry_price': trade.entryprice,
                'exit_price': trade.price,
                'pnl': trade.pnl,
                'pnl_net': trade.pnlcomm,
            })

    def get_trades_df(self):
        """获取交易记录DataFrame"""
        import pandas as pd
        return pd.DataFrame(self.trades)

# personal/strategies/templates.py
class CrossOverStrategy(SimpleStrategy):
    """交叉策略模板

    基于快速和慢速均线交叉的经典策略模板。
    """

    params = (
        ('fast_period', 10),
        ('slow_period', 30),
    )

    def __init__(self):
        super().__init__()

        # 指标
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)

    def buy_signal(self) -> bool:
        """金叉买入"""
        return self.crossover > 0

    def sell_signal(self) -> bool:
        """死叉卖出"""
        return self.crossover < 0

class RSIStrategy(SimpleStrategy):
    """RSI策略模板

    基于RSI指标的超买超卖策略。
    """

    params = (
        ('rsi_period', 14),
        ('rsi_oversold', 30),
        ('rsi_overbought', 70),
    )

    def __init__(self):
        super().__init__()

        # RSI指标
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

    def buy_signal(self) -> bool:
        """RSI超卖买入"""
        return self.rsi[0] < self.p.rsi_oversold

    def sell_signal(self) -> bool:
        """RSI超买卖出"""
        return self.rsi[0] > self.p.rsi_overbought
```

#### 5. 快速回测工具设计

```python
# personal/quick/backtest.py
import backtrader as bt
from typing import Type, Dict, Any, Optional
import pandas as pd

class QuickBacktest:
    """快速回测工具

    提供简化的回测接口，支持链式调用。
    """

    def __init__(self, initial_cash: float = 100000, commission: float = 0.0003):
        """初始化回测

        Args:
            initial_cash: 初始资金
            commission: 佣金率
        """
        self.cerebro = bt.Cerebro()
        self.cerebro.broker.setcash(initial_cash)
        self.cerebro.broker.setcommission(commission=commission)

        self.data_count = 0
        self.strategy_count = 0
        self.analyzer_configs = []

        # 自动添加常用分析器
        self.add_default_analyzers()

    def add_default_analyzers(self):
        """添加默认分析器"""
        self.analyzer_configs.extend([
            (bt.analyzers.SharpeRatio, {'riskfreerate': 0.03}),
            (bt.analyzers.DrawDown, {}),
            (bt.analyzers.Returns, {}),
            (bt.analyzers.TradeAnalyzer, {}),
        ])

    def add_data(
        self,
        data: pd.DataFrame,
        name: str = None,
        timeframe: bt.TimeFrame = bt.TimeFrame.Days
    ) -> 'QuickBacktest':
        """添加数据

        Args:
            data: 价格数据 (DataFrame with columns: datetime, open, high, low, close, volume)
            name: 数据名称
            timeframe: 时间周期

        Returns:
            self (支持链式调用)
        """
        data_feed = bt.feeds.PandasData(
            dataname=data,
            datetime='datetime' if 'datetime' in data.columns else None,
            open='open' if 'open' in data.columns else None,
            high='high' if 'high' in data.columns else None,
            low='low' if 'low' in data.columns else None,
            close='close' if 'close' in data.columns else None,
            volume='volume' if 'volume' in data.columns else None,
            timeframe=timeframe
        )
        self.cerebro.adddata(data_feed, name=name)
        self.data_count += 1
        return self

    def set_strategy(
        self,
        strategy_cls: Type[bt.Strategy],
        **kwargs
    ) -> 'QuickBacktest':
        """设置策略

        Args:
            strategy_cls: 策略类
            **kwargs: 策略参数

        Returns:
            self (支持链式调用)
        """
        self.cerebro.addstrategy(strategy_cls, **kwargs)
        self.strategy_count += 1
        return self

    def add_analyzer(
        self,
        analyzer_cls: Type[bt.Analyzer],
        **kwargs
    ) -> 'QuickBacktest':
        """添加分析器

        Args:
            analyzer_cls: 分析器类
            **kwargs: 分析器参数

        Returns:
            self (支持链式调用)
        """
        self.analyzer_configs.append((analyzer_cls, kwargs))
        return self

    def run(self) -> 'QuickBacktest':
        """运行回测

        Returns:
            self (支持链式调用)
        """
        # 添加所有分析器
        for analyzer_cls, kwargs in self.analyzer_configs:
            self.cerebro.addanalyzer(analyzer_cls, **kwargs)

        # 运行回测
        self.strategies = self.cerebro.run()
        return self

    def get_metrics(self) -> Dict[str, Any]:
        """获取回测指标

        Returns:
            指标字典
        """
        if not hasattr(self, 'strategies') or not self.strategies:
            return {}

        strat = self.strategies[0]
        broker_value = self.cerebro.broker.getvalue()
        starting_cash = self.cerebro.broker.starting_cash

        metrics = {
            'initial_cash': starting_cash,
            'final_value': broker_value,
            'total_return': (broker_value / starting_cash) - 1,
            'absolute_return': broker_value - starting_cash,
        }

        # 获取分析器结果
        for analyzer in strat.analyzers:
            analyzer_name = analyzer.__class__.__name__
            result = analyzer.get_analysis()

            if analyzer_name == 'SharpeRatio':
                metrics['sharpe_ratio'] = result.get('sharperatio', None)
            elif analyzer_name == 'DrawDown':
                metrics['max_drawdown'] = result.get('max', {}).get('drawdown', 0)
                metrics['max_drawdown_pct'] = metrics['max_drawdown'] / 100
            elif analyzer_name == 'Returns':
                metrics['avg_return'] = result.get('avg', 0)
            elif analyzer_name == 'TradeAnalyzer':
                total_trades = result.get('total', {})
                metrics['total_trades'] = total_trades.get('total', 0)
                metrics['won_trades'] = total_trades.get('won', 0)
                metrics['lost_trades'] = total_trades.get('lost', 0)
                win_rate = (metrics['won_trades'] / metrics['total_trades']
                           if metrics['total_trades'] > 0 else 0)
                metrics['win_rate'] = win_rate

        return metrics

    def print_metrics(self):
        """打印回测指标"""
        metrics = self.get_metrics()

        print("=" * 50)
        print("回测结果")
        print("=" * 50)
        print(f"初始资金: {metrics.get('initial_cash', 0):,.2f}")
        print(f"最终资金: {metrics.get('final_value', 0):,.2f}")
        print(f"总收益率: {metrics.get('total_return', 0):.2%}")
        print(f"夏普比率: {metrics.get('sharpe_ratio', 'N/A')}")
        print(f"最大回撤: {metrics.get('max_drawdown_pct', 0):.2%}")
        print(f"交易次数: {metrics.get('total_trades', 0)}")
        print(f"胜率: {metrics.get('win_rate', 0):.2%}")
        print("=" * 50)

    def plot(self, **kwargs):
        """绘制结果图表"""
        self.cerebro.plot(**kwargs)

# 便捷函数
def quick_backtest(
    strategy_cls: Type[bt.Strategy],
    data: pd.DataFrame,
    initial_cash: float = 100000,
    **strategy_params
) -> Dict[str, Any]:
    """快速回测函数

    Args:
        strategy_cls: 策略类
        data: 价格数据
        initial_cash: 初始资金
        **strategy_params: 策略参数

    Returns:
        回测指标字典

    Example:
        >>> result = quick_backtest(
        ...     CrossOverStrategy,
        ...     price_data,
        ...     fast_period=5,
        ...     slow_period=20
        ... )
        >>> print(f"收益率: {result['total_return']:.2%}")
    """
    return (QuickBacktest(initial_cash=initial_cash)
            .add_data(data)
            .set_strategy(strategy_cls, **strategy_params)
            .run()
            .get_metrics())
```

### 与现有Backtrader集成方案

#### 使用示例

```python
# 配置文件: config.yaml
mode: backtest

backtest:
  initial_cash: 100000
  commission: 0.0003

strategies:
  CrossOverStrategy:
    fast_period: 10
    slow_period: 30
    position_size: 100
    stop_loss: 0.05

risk:
  max_position_ratio: 0.3
  max_total_position: 0.8
  stop_loss_ratio: 0.05

# 使用个人量化模块
from backtrader.personal.config import ConfigManager
from backtrader.personal.strategies.templates import CrossOverStrategy
from backtrader.personal.quick.backtest import QuickBacktest
import backtrader as bt
import pandas as pd

# 加载配置
config = ConfigManager('config.yaml')

# 快速回测
data = pd.read_csv('price_data.csv')
result = (QuickBacktest(
                initial_cash=config.backtest.initial_cash,
                commission=config.backtest.commission
            )
            .add_data(data)
            .set_strategy(CrossOverStrategy, **config.get_strategy_config('CrossOverStrategy'))
            .run())

result.print_metrics()
```

### 实施计划

#### 第一阶段 (P0功能)
1. 实现ConfigManager基础功能
2. 实现TradingError异常体系
3. 实现常量枚举定义
4. 实现OutputManager基础输出
5. 实现SimpleStrategy简化基类

#### 第二阶段 (P1功能)
1. 实现配置验证器
2. 实现错误处理策略
3. 实现策略模板库
4. 实现资金管理模块
5. 实现QuickBacktest快速回测

#### 第三阶段 (P2功能)
1. 支持配置文件继承
2. 支持配置加密存储
3. 实现策略组合管理
4. 实现高级资金管理模型
5. 实现策略比较工具

---

## 总结

通过借鉴PersonalQuantSystem项目的设计理念，Backtrader可以扩展以下能力：

1. **统一配置管理**: 通过YAML配置文件实现参数外部化管理
2. **业务异常体系**: 提供清晰的错误分类和用户友好的错误消息
3. **简化策略接口**: 降低个人投资者的学习曲线
4. **快速回测工具**: 支持策略快速验证和参数优化
5. **个人化设计**: 面向个人投资者的友好界面和工具
6. **完善资金管理**: 提供多种仓位计算和风险控制方法

这些增强功能将使Backtrader：
- 更容易上手：简化策略开发流程
- 更专业：统一的配置和错误处理
- 更完整：从回测到实盘的无缝衔接
- 更友好：个人投资者友好的设计理念
