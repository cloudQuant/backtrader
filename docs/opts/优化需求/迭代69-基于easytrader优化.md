### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/easytrader
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### easytrader项目简介
easytrader是一个A股自动化交易框架，通过客户端自动化实现交易，具有以下核心特点：
- **客户端自动化**: 通过模拟操作实现自动交易
- **多券商支持**: 支持多家券商客户端
- **简洁API**: 简洁的交易API接口
- **实时查询**: 实时查询持仓和余额
- **交易执行**: 自动化下单执行
- **跟单功能**: 支持跟单交易

### 重点借鉴方向
1. **交易接口**: 统一的交易接口抽象
2. **多券商**: 多券商适配器模式
3. **持仓查询**: 持仓和资金查询
4. **订单管理**: 订单提交和状态管理
5. **错误处理**: 交易错误处理机制
6. **日志系统**: 交易日志记录

---

## 项目对比分析

### Backtrader vs easytrader 架构对比

| 维度 | Backtrader | easytrader |
|------|------------|------------|
| **应用场景** | 回测和实盘交易框架 | A股客户端自动化交易 |
| **交易方式** | 通过API接口 | 通过GUI自动化 |
| **券商支持** | IB/OANDA等国际券商 | 国内多家券商客户端 |
| **接口抽象** | Broker基类 | IClientTrader/WebTrader |
| **持仓查询** | 通过Broker获取 | 通过GUI控件获取 |
| **订单管理** | Order/Trade类 | 弹窗+状态查询 |
| **错误处理** | 基础异常处理 | TradeError/NotLoginError |
| **日志系统** | 基础日志 | 详细的性能监控日志 |
| **跟单功能** | 无 | 支持多平台跟单 |
| **配置管理** | 参数系统 | 配置类+窗口ID映射 |
| **数据获取策略** | Line系统 | Copy/Xls/Dbf策略 |
| **性能监控** | 基础分析器 | perf_clock装饰器 |

### easytrader可借鉴的核心优势

#### 1. 多券商适配器模式
- **统一接口抽象**: IClientTrader和WebTrader定义统一接口
- **配置驱动**: 每个券商独立的配置类
- **工厂模式**: api.use()根据券商名创建对应交易器
- **窗口ID映射**: 通过配置映射GUI控件ID

#### 2. 策略模式的数据获取
- **可插拔策略**: Copy、Xls、Dbf多种数据获取方式
- **自动降级**: 策略失败时自动尝试其他方式
- **性能优化**: 选择最优的数据获取方式

#### 3. 错误处理机制
- **自定义异常类型**: TradeError、NotLoginError
- **弹窗处理**: 自动识别和响应交易确认弹窗
- **登录状态检查**: 自动检查和重新登录

#### 4. 性能监控
- **装饰器模式**: perf_clock记录操作耗时
- **详细日志**: 记录每个交易操作的执行时间
- **性能分析**: 方便定位性能瓶颈

#### 5. 跟单功能
- **多平台支持**: 聚米、米筐、雪球等平台
- **多用户跟踪**: 支持跟踪多个用户的交易
- **定时轮询**: 定时检查交易信号并执行

#### 6. 配置管理
- **配置类继承**: CommonConfig定义通用配置
- **窗口控件映射**: 通过ID定位GUI元素
- **路径配置**: 默认可执行文件路径配置

---

## 需求文档

### 需求概述

借鉴easytrader项目的设计理念，为backtrader添加以下功能模块，提升实盘交易能力和国内券商支持：

### 功能需求

#### FR1: 多券商适配器

**FR1.1 券商接口抽象**
- 需求描述: 建立统一的券商交易接口抽象
- 优先级: 高
- 验收标准:
  - 定义BrokerAdapter接口
  - 定义标准交易方法（买入、卖出、查询）
  - 定义事件回调接口

**FR1.2 配置驱动的适配器**
- 需求描述: 通过配置实现不同券商的适配
- 优先级: 高
- 验收标准:
  - 定义BrokerConfig配置基类
  - 支持券商特定配置
  - 支持配置文件加载

**FR1.3 工厂模式创建**
- 需求描述: 使用工厂模式创建券商适配器
- 优先级: 中
- 验收标准:
  - 实现BrokerFactory工厂类
  - 支持按券商名称创建适配器
  - 支持自动检测已安装客户端

#### FR2: 数据获取策略

**FR2.1 策略接口定义**
- 需求描述: 定义数据获取策略接口
- 优先级: 高
- 验收标准:
  - 定义DataFetchStrategy接口
  - 定义策略优先级
  - 支持策略降级

**FR2.2 多策略实现**
- 需求描述: 实现多种数据获取策略
- 优先级: 中
- 验收标准:
  - 实现APICopy策略（API复制）
  - 实现FileExport策略（文件导出）
  - 实现DirectQuery策略（直接查询）

**FR2.3 策略管理器**
- 需求描述: 管理和调度数据获取策略
- 优先级: 中
- 验收标准:
  - 实现StrategyManager
  - 支持策略优先级排序
  - 支持自动降级重试

#### FR3: 错误处理增强

**FR3.1 自定义异常类型**
- 需求描述: 定义交易相关的异常类型
- 优先级: 高
- 验收标准:
  - 定义TradeError异常基类
  - 定义NotLoginError异常
  - 定义OrderRejectError异常
  - 定义NetworkError异常

**FR3.2 弹窗处理机制**
- 需求描述: 实现弹窗自动处理
- 优先级: 中
- 验收标准:
  - 支持弹窗检测
  - 支持弹窗自动关闭
  - 支持弹窗内容识别

**FR3.3 登录状态管理**
- 需求描述: 实现登录状态检查和自动重连
- 优先级: 高
- 验收标准:
  - 支持登录状态检测
  - 支持自动重新登录
  - 支持登录失败重试

#### FR4: 性能监控

**FR4.1 性能装饰器**
- 需求描述: 实现性能监控装饰器
- 优先级: 中
- 验收标准:
  - 实现perf_clock装饰器
  - 记录函数执行时间
  - 输出性能日志

**FR4.2 交易统计**
- 需求描述: 统计交易操作性能
- 优先级: 低
- 验收标准:
  - 统计订单提交耗时
  - 统计数据查询耗时
  - 生成性能报告

**FR4.3 性能预警**
- 需求描述: 性能异常预警
- 优先级: 低
- 验收标准:
  - 支持性能阈值设置
  - 超时自动告警
  - 记录性能异常

#### FR5: 跟单功能

**FR5.1 跟单基类**
- 需求描述: 定义跟单功能基类
- 优先级: 中
- 验收标准:
  - 定义FollowerBase基类
  - 定义跟单接口
  - 支持多策略跟踪

**FR5.2 信号源适配器**
- 需求描述: 实现信号源适配器
- 优先级: 中
- 验收标准:
  - 支持聚米跟单
  - 支持米筐跟单
  - 支持雪球跟单

**FR5.3 信号过滤**
- 需求描述: 实现信号过滤机制
- 优先级: 低
- 验收标准:
  - 支持股票代码过滤
  - 支持交易方向过滤
  - 支持金额过滤

#### FR6: 日志系统增强

**FR6.1 结构化日志**
- 需求描述: 实现结构化交易日志
- 优先级: 中
- 验收标准:
  - 支持JSON格式日志
  - 支持日志文件分离
  - 支持日志按日期轮转

**FR6.2 交易审计**
- 需求描述: 记录完整交易审计日志
- 优先级: 中
- 验收标准:
  - 记录所有订单操作
  - 记录所有查询操作
  - 支持日志查询和回放

**FR6.3 敏感信息保护**
- 需求描述: 保护日志中的敏感信息
- 优先级: 中
- 验收标准:
  - 自动脱敏密码
  - 自动脱敏账号
  - 可配置脱敏规则

### 非功能需求

#### NFR1: 性能
- 订单提交响应时间 < 500ms
- 持仓查询响应时间 < 1s
- 登录状态检查 < 100ms

#### NFR2: 可靠性
- 自动重连成功率 > 95%
- 订单提交成功率 > 99%
- 异常恢复时间 < 5s

#### NFR3: 兼容性
- 支持Windows 7/10/11
- 支持主流券商客户端
- 保持与现有backtrader API兼容

---

## 设计文档

### 整体架构设计

#### 新增模块结构

```
backtrader/
├── backtrader/
│   ├── brokers/            # 增强：券商适配器
│   │   ├── __init__.py
│   │   ├── base.py         # 券商适配器基类
│   │   ├── factory.py      # 券商工厂
│   │   ├── config/         # 券商配置
│   │   │   ├── __init__.py
│   │   │   ├── base.py     # 配置基类
│   │   │   ├── ths.py      # 同花顺配置
│   │   │   ├── ht.py       # 华泰配置
│   │   │   └── yh.py       # 银河配置
│   │   ├── ths.py          # 同花顺适配器
│   │   ├── ht.py           # 华泰适配器
│   │   └── yh.py           # 银河适配器
│   ├── data/               # 增强：数据获取策略
│   │   ├── __init__.py
│   │   ├── strategies/     # 数据获取策略
│   │   │   ├── __init__.py
│   │   │   ├── base.py     # 策略基类
│   │   │   ├── copy.py     # 复制策略
│   │   │   ├── file.py     # 文件策略
│   │   │   └── api.py      # API策略
│   │   └── manager.py      # 策略管理器
│   ├── exceptions/         # 新增：异常定义
│   │   ├── __init__.py
│   │   ├── trade.py        # 交易异常
│   │   ├── login.py        # 登录异常
│   │   └── network.py      # 网络异常
│   ├── monitor/            # 新增：性能监控
│   │   ├── __init__.py
│   │   ├── perf.py         # 性能监控装饰器
│   │   ├── stats.py        # 性能统计
│   │   └── alert.py        # 性能预警
│   ├── follower/           # 新增：跟单功能
│   │   ├── __init__.py
│   │   ├── base.py         # 跟单基类
│   │   ├── signal.py       # 信号源适配器
│   │   ├── filter.py       # 信号过滤器
│   │   ├── joinquant.py    # 聚米跟单
│   │   ├── rq.py           # 米筐跟单
│   │   └── xq.py           # 雪球跟单
│   ├── ui/                 # 新增：UI自动化
│   │   ├── __init__.py
│   │   ├── dialog.py       # 弹窗处理
│   │   ├── window.py       # 窗口管理
│   │   └── clipboard.py    # 剪贴板操作
│   └── utils/
│       └── logging/        # 增强：日志系统
│           ├── __init__.py
│           ├── logger.py   # 日志配置
│           ├── audit.py    # 审计日志
│           └── mask.py     # 敏感信息脱敏
```

### 详细设计

#### 1. 券商适配器

**1.1 适配器基类**

```python
# backtrader/brokers/base.py
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class OrderResult:
    """订单结果"""
    order_id: str
    status: str
    message: str = ""
    timestamp: float = None

@dataclass
class Position:
    """持仓信息"""
    symbol: str
    volume: int
    available: int
    price: float
    cost: float
    profit: float = 0.0

@dataclass
class Balance:
    """资金信息"""
    total: float
    available: float
    market_value: float
    frozen: float = 0.0

class BrokerAdapter(ABC):
    """券商适配器基类"""

    def __init__(self, config):
        self.config = config
        self._logged_in = False
        self._session = None

    @property
    @abstractmethod
    def balance(self) -> Balance:
        """获取资金信息"""
        pass

    @property
    @abstractmethod
    def position(self) -> Dict[str, Position]:
        """获取持仓信息"""
        pass

    @abstractmethod
    def login(self, user: str, password: str, **kwargs) -> bool:
        """登录"""
        pass

    @abstractmethod
    def logout(self) -> bool:
        """登出"""
        pass

    @abstractmethod
    def buy(self, symbol: str, price: float, volume: int, **kwargs) -> OrderResult:
        """买入"""
        pass

    @abstractmethod
    def sell(self, symbol: str, price: float, volume: int, **kwargs) -> OrderResult:
        """卖出"""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        pass

    @abstractmethod
    def query_orders(self, **kwargs) -> List[Dict]:
        """查询委托"""
        pass

    @abstractmethod
    def query_deals(self, **kwargs) -> List[Dict]:
        """查询成交"""
        pass

    def is_logged_in(self) -> bool:
        """检查登录状态"""
        return self._logged_in

    def keep_alive(self) -> bool:
        """保持连接"""
        if not self.is_logged_in():
            return False
        # 子类实现具体保活逻辑
        return True
```

**1.2 工厂类**

```python
# backtrader/brokers/factory.py
from typing import Dict, Type, Optional
from .base import BrokerAdapter
from .config.base import BrokerConfig
from .ths import THSBroker
from .ht import HTBroker
from .yh import YHBroker

class BrokerFactory:
    """券商工厂"""

    _brokers: Dict[str, Type[BrokerAdapter]] = {
        'ths': THSBroker,
        'tonghuashun': THSBroker,
        'ht': HTBroker,
        'huatai': HTBroker,
        'yh': YHBroker,
        'yinhe': YHBroker,
    }

    _configs: Dict[str, Type[BrokerConfig]] = {
        'ths': THSConfig,
        'tonghuashun': THSConfig,
        'ht': HTConfig,
        'huatai': HTConfig,
        'yh': YHConfig,
        'yinhe': YHConfig,
    }

    @classmethod
    def register(cls, name: str, broker_class: Type[BrokerAdapter],
                 config_class: Type[BrokerConfig] = None):
        """注册券商"""
        cls._brokers[name.lower()] = broker_class
        if config_class:
            cls._configs[name.lower()] = config_class

    @classmethod
    def create(cls, broker: str, config: Optional[BrokerConfig] = None,
               auto_detect: bool = False) -> BrokerAdapter:
        """创建券商适配器"""
        broker = broker.lower()
        if broker not in cls._brokers:
            raise ValueError(f"Unknown broker: {broker}")

        broker_class = cls._brokers[broker]

        # 自动检测配置
        if config is None:
            config_class = cls._configs.get(broker)
            if config_class:
                config = config_class()
            else:
                config = BrokerConfig()

        # 自动检测客户端
        if auto_detect:
            config.detect_executable()

        return broker_class(config)

    @classmethod
    def list_available(cls) -> List[str]:
        """列出可用的券商"""
        return list(cls._brokers.keys())

def use(broker: str, **kwargs) -> BrokerAdapter:
    """便捷函数：创建券商适配器"""
    return BrokerFactory.create(broker, **kwargs)
```

**1.3 配置基类**

```python
# backtrader/brokers/config/base.py
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional
import win32gui
import win32con

class BrokerConfig(ABC):
    """券商配置基类"""

    # 默认可执行文件路径
    DEFAULT_EXE_PATH: str = None

    # 主窗口标题
    WINDOW_TITLE: str = None

    # 交易控件ID
    TRADE_SECURITY_CTRL_ID: int = 1032
    TRADE_PRICE_CTRL_ID: int = 1033
    TRADE_AMOUNT_CTRL_ID: int = 1034
    TRADE_BUY_BTN_ID: int = 1005
    TRADE_SELL_BTN_ID: int = 1006

    # 查询控件ID
    BALANCE_CTRL_GROUP: Dict[str, int] = None
    POSITION_CTRL_ID: int = 1054

    # 菜单路径
    MENU_PATH_POSITION: List[str] = None
    MENU_PATH_BALANCE: List[str] = None

    def __init__(self, exe_path: str = None):
        self.exe_path = exe_path or self.DEFAULT_EXE_PATH
        self.window_title = self.WINDOW_TITLE

    def detect_executable(self) -> bool:
        """检测可执行文件"""
        if self.exe_path and Path(self.exe_path).exists():
            return True

        # 常见安装路径检测
        common_paths = [
            Path("C:/") / "Program Files" / "券商软件",
            Path("C:/") / "Program Files (x86)" / "券商软件",
        ]

        for path in common_paths:
            if path.exists():
                for exe in path.rglob("*.exe"):
                    if self._is_valid_executable(exe):
                        self.exe_path = str(exe)
                        return True
        return False

    def _is_valid_executable(self, exe_path: Path) -> bool:
        """判断是否为有效的可执行文件"""
        # 子类实现具体逻辑
        return False

    def find_window(self) -> Optional[int]:
        """查找主窗口句柄"""
        if not self.window_title:
            return None

        def callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd) and self.window_title in win32gui.GetWindowText(hwnd):
                windows.append(hwnd)
            return True

        windows = []
        win32gui.EnumWindows(callback, windows)
        return windows[0] if windows else None

class THSConfig(BrokerConfig):
    """同花顺配置"""
    DEFAULT_EXE_PATH = r"C:\同花顺软件\同花顺\TdxW.exe"
    WINDOW_TITLE = "同花顺"

class HTConfig(BrokerConfig):
    """华泰配置"""
    DEFAULT_EXE_PATH = r"C:\华泰证券\涨乐财富通\HTClient.exe"
    WINDOW_TITLE = "涨乐财富通"

class YHConfig(BrokerConfig):
    """银河配置"""
    DEFAULT_EXE_PATH = r"C:\双子星-中国银河证券\Binarystar.exe"
    WINDOW_TITLE = "中国银河证券"
```

#### 2. 数据获取策略

**2.1 策略基类**

```python
# backtrader/data/strategies/base.py
from abc import ABC, abstractmethod
from typing import Any, Optional
from enum import Enum

class FetchPriority(Enum):
    """策略优先级"""
    HIGH = 1
    MEDIUM = 2
    LOW = 3

class DataFetchStrategy(ABC):
    """数据获取策略基类"""

    name: str = None
    priority: FetchPriority = FetchPriority.MEDIUM

    def __init__(self, context):
        self.context = context

    @abstractmethod
    def fetch(self, **kwargs) -> Optional[Any]:
        """获取数据"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查策略是否可用"""
        pass

    def on_success(self, data):
        """成功回调"""
        pass

    def on_failure(self, error):
        """失败回调"""
        pass
```

**2.2 具体策略实现**

```python
# backtrader/data/strategies/copy.py
import win32clipboard
import win32con
from .base import DataFetchStrategy, FetchPriority

class CopyStrategy(DataFetchStrategy):
    """剪贴板复制策略"""

    name = "copy"
    priority = FetchPriority.HIGH

    def fetch(self, window=None, grid_ctrl_id=None, **kwargs):
        """通过剪贴板复制获取数据"""
        try:
            # 选中文本
            if window and grid_ctrl_id:
                grid = window[grid_ctrl_id]
                grid.type_keys("^A^C", set_foreground=False)

            # 获取剪贴板数据
            win32clipboard.OpenClipboard()
            try:
                data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()

            return self._parse_data(data)
        except Exception as e:
            self.on_failure(e)
            return None

    def is_available(self) -> bool:
        """检查剪贴板是否可用"""
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.CloseClipboard()
            return True
        except:
            return False

    def _parse_data(self, data: str):
        """解析数据"""
        # 解析剪贴板文本数据
        lines = data.strip().split('\n')
        return [line.split('\t') for line in lines]

# backtrader/data/strategies/file.py
from .base import DataFetchStrategy, FetchPriority
import pandas as pd
from pathlib import Path
import time

class FileExportStrategy(DataFetchStrategy):
    """文件导出策略"""

    name = "file"
    priority = FetchPriority.MEDIUM

    def fetch(self, window=None, export_btn_id=None, **kwargs):
        """通过文件导出获取数据"""
        temp_file = Path("temp_export.csv")

        try:
            # 点击导出按钮
            if window and export_btn_id:
                window[export_btn_id].click()

            # 等待文件生成
            for _ in range(10):
                if temp_file.exists():
                    break
                time.sleep(0.5)

            # 读取数据
            if temp_file.exists():
                data = pd.read_csv(temp_file)
                temp_file.unlink()  # 删除临时文件
                return data.to_dict('records')
        except Exception as e:
            self.on_failure(e)
        finally:
            if temp_file.exists():
                temp_file.unlink()
        return None

    def is_available(self) -> bool:
        """检查文件操作是否可用"""
        return True

# backtrader/data/strategies/api.py
from .base import DataFetchStrategy, FetchPriority

class DirectApiStrategy(DataFetchStrategy):
    """直接API策略"""

    name = "api"
    priority = FetchPriority.HIGH

    def fetch(self, api_obj=None, method=None, **kwargs):
        """通过直接API调用获取数据"""
        try:
            if api_obj and method:
                data = getattr(api_obj, method)(**kwargs)
                return self._parse_data(data)
        except Exception as e:
            self.on_failure(e)
        return None

    def is_available(self) -> bool:
        """检查API是否可用"""
        return self.context.api is not None

    def _parse_data(self, data):
        """解析数据"""
        return data
```

**2.3 策略管理器**

```python
# backtrader/data/manager.py
from typing import List, Optional, Any
from .strategies.base import DataFetchStrategy, FetchPriority

class StrategyManager:
    """数据获取策略管理器"""

    def __init__(self):
        self._strategies: List[DataFetchStrategy] = []
        self._last_success: Optional[str] = None

    def register(self, strategy: DataFetchStrategy):
        """注册策略"""
        self._strategies.append(strategy)
        # 按优先级排序
        self._strategies.sort(key=lambda s: s.priority.value)

    def unregister(self, strategy_name: str):
        """取消注册策略"""
        self._strategies = [s for s in self._strategies if s.name != strategy_name]

    def fetch(self, **kwargs) -> Optional[Any]:
        """使用策略获取数据"""
        # 优先使用上次成功的策略
        if self._last_success:
            for strategy in self._strategies:
                if strategy.name == self._last_success and strategy.is_available():
                    data = strategy.fetch(**kwargs)
                    if data is not None:
                        return data

        # 按优先级尝试所有策略
        for strategy in self._strategies:
            if not strategy.is_available():
                continue

            try:
                data = strategy.fetch(**kwargs)
                if data is not None:
                    self._last_success = strategy.name
                    strategy.on_success(data)
                    return data
            except Exception as e:
                strategy.on_failure(e)
                continue

        return None

    @property
    def strategies(self) -> List[DataFetchStrategy]:
        """获取所有策略"""
        return list(self._strategies)
```

#### 3. 异常处理

**3.1 异常定义**

```python
# backtrader/exceptions/__init__.py
class BacktraderError(Exception):
    """Backtrader基础异常"""
    pass

# backtrader/exceptions/trade.py
class TradeError(BacktraderError):
    """交易错误基类"""
    def __init__(self, message: str, code: str = None, order_id: str = None):
        super().__init__(message)
        self.code = code
        self.order_id = order_id

class OrderRejectError(TradeError):
    """订单被拒绝"""
    pass

class OrderTimeoutError(TradeError):
    """订单超时"""
    pass

# backtrader/exceptions/login.py
class LoginError(BacktraderError):
    """登录错误基类"""
    pass

class NotLoginError(LoginError):
    """未登录异常"""
    pass

class LoginFailedError(LoginError):
    """登录失败异常"""
    def __init__(self, message: str, retry: int = 0):
        super().__init__(message)
        self.retry = retry

# backtrader/exceptions/network.py
class NetworkError(BacktraderError):
    """网络错误"""
    pass

class ConnectionError(NetworkError):
    """连接错误"""
    pass

class TimeoutError(NetworkError):
    """超时错误"""
    pass
```

#### 4. 性能监控

**4.1 性能装饰器**

```python
# backtrader/monitor/perf.py
import time
import logging
from functools import wraps
from typing import Callable

logger = logging.getLogger("backtrader.perf")

def perf_clock(func: Callable) -> Callable:
    """性能监控装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"{func.__name__} executed in {elapsed:.4f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"{func.__name__} failed after {elapsed:.4f}s: {e}")
            raise
    return wrapper

def perf_async(func: Callable) -> Callable:
    """异步性能监控装饰器"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"{func.__name__} executed in {elapsed:.4f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"{func.__name__} failed after {elapsed:.4f}s: {e}")
            raise
    return wrapper

class PerformanceMonitor:
    """性能监控器"""

    def __init__(self):
        self._records: dict = {}

    def record(self, name: str, duration: float):
        """记录性能"""
        if name not in self._records:
            self._records[name] = []
        self._records[name].append(duration)

    def get_stats(self, name: str) -> dict:
        """获取统计信息"""
        if name not in self._records:
            return {}

        records = self._records[name]
        return {
            'count': len(records),
            'total': sum(records),
            'avg': sum(records) / len(records),
            'min': min(records),
            'max': max(records),
        }

    def get_all_stats(self) -> dict:
        """获取所有统计"""
        return {name: self.get_stats(name) for name in self._records}

    def reset(self):
        """重置记录"""
        self._records.clear()

# 全局性能监控器
perf_monitor = PerformanceMonitor()
```

**4.2 性能预警**

```python
# backtrader/monitor/alert.py
import logging
from typing import Callable, Optional

logger = logging.getLogger("backtrader.alert")

class PerformanceAlert:
    """性能预警"""

    def __init__(self, threshold: float = 1.0,
                 on_alert: Optional[Callable] = None):
        self.threshold = threshold
        self.on_alert = on_alert or self._default_alert

    def check(self, name: str, duration: float):
        """检查是否需要预警"""
        if duration > self.threshold:
            self.on_alert(name, duration)

    def _default_alert(self, name: str, duration: float):
        """默认预警处理"""
        logger.warning(f"Performance alert: {name} took {duration:.4f}s "
                      f"(threshold: {self.threshold:.4f}s)")
```

#### 5. 跟单功能

**5.1 跟单基类**

```python
# backtrader/follower/base.py
from abc import ABC, abstractmethod
from typing import List, Dict, Callable
import time
import threading

class FollowerBase(ABC):
    """跟单基类"""

    def __init__(self, broker_adapter):
        self.broker = broker_adapter
        self._running = False
        self._thread = None

    @abstractmethod
    def login(self, user: str, password: str, **kwargs) -> bool:
        """登录信号源"""
        pass

    @abstractmethod
    def fetch_signals(self, **kwargs) -> List[Dict]:
        """获取交易信号"""
        pass

    def follow(self, users: List[str] = None,
               strategies: List[str] = None,
               track_interval: int = 5,
               signal_filter: Callable = None):
        """启动跟单"""
        self._running = True
        self._thread = threading.Thread(
            target=self._follow_loop,
            args=(users, strategies, track_interval, signal_filter),
            daemon=True
        )
        self._thread.start()

    def stop(self):
        """停止跟单"""
        self._running = False
        if self._thread:
            self._thread.join()

    def _follow_loop(self, users: List[str], strategies: List[str],
                     interval: int, signal_filter: Callable):
        """跟单主循环"""
        last_signals = {}

        while self._running:
            try:
                signals = self.fetch_signals(users=users, strategies=strategies)

                for signal in signals:
                    signal_id = self._get_signal_id(signal)

                    # 跳过已处理的信号
                    if signal_id in last_signals:
                        continue

                    # 应用过滤器
                    if signal_filter and not signal_filter(signal):
                        continue

                    # 执行交易
                    self._execute_signal(signal)
                    last_signals[signal_id] = True

                time.sleep(interval)
            except Exception as e:
                logger.error(f"Follow error: {e}")

    def _get_signal_id(self, signal: Dict) -> str:
        """获取信号ID"""
        return f"{signal.get('user')}_{signal.get('time')}_{signal.get('symbol')}"

    def _execute_signal(self, signal: Dict):
        """执行交易信号"""
        action = signal.get('action')
        symbol = signal.get('symbol')
        price = signal.get('price')
        amount = signal.get('amount')

        if action == 'buy':
            self.broker.buy(symbol, price, amount)
        elif action == 'sell':
            self.broker.sell(symbol, price, amount)
```

**5.2 信号过滤器**

```python
# backtrader/follower/filter.py
from typing import Dict, List, Callable

class SignalFilter:
    """信号过滤器"""

    def __init__(self):
        self._filters: List[Callable] = []

    def add_filter(self, filter_func: Callable):
        """添加过滤器"""
        self._filters.append(filter_func)

    def remove_filter(self, filter_func: Callable):
        """移除过滤器"""
        if filter_func in self._filters:
            self._filters.remove(filter_func)

    def apply(self, signal: Dict) -> bool:
        """应用所有过滤器，返回True表示通过"""
        for filter_func in self._filters:
            if not filter_func(signal):
                return False
        return True

# 预定义过滤器
def symbol_filter(allowed_symbols: List[str]):
    """股票代码过滤"""
    def filter_func(signal: Dict) -> bool:
        return signal.get('symbol') in allowed_symbols
    return filter_func

def amount_filter(min_amount: int = 100, max_amount: int = 100000):
    """金额过滤"""
    def filter_func(signal: Dict) -> bool:
        amount = signal.get('amount', 0)
        return min_amount <= amount <= max_amount
    return filter_func

def direction_filter(allowed_directions: List[str]):
    """交易方向过滤"""
    def filter_func(signal: Dict) -> bool:
        return signal.get('action') in allowed_directions
    return filter_func
```

#### 6. UI自动化

**6.1 弹窗处理**

```python
# backtrader/ui/dialog.py
import win32gui
import win32con
from typing import Optional, List

class DialogHandler:
    """弹窗处理器"""

    # 常见弹窗标题
    WARNING_TITLES = ["提示", "警告", "确认", "提示信息"]
    CONFIRM_TITLES = ["委托确认", "交易确认"]

    def __init__(self):
        self._handled: List[int] = []

    def check_pop_dialog(self) -> Optional[dict]:
        """检查是否有弹窗"""
        def callback(hwnd, dialogs):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                # 检查是否是目标弹窗
                if self._is_target_dialog(title):
                    dialogs.append({
                        'hwnd': hwnd,
                        'title': title,
                        'text': self._get_dialog_text(hwnd)
                    })
            return True

        dialogs = []
        win32gui.EnumWindows(callback, dialogs)
        return dialogs[0] if dialogs else None

    def close_dialog(self, hwnd: int, button: str = "确定"):
        """关闭弹窗"""
        try:
            # 查找按钮
            btn_hwnd = self._find_button(hwnd, button)
            if btn_hwnd:
                win32gui.PostMessage(btn_hwnd, win32con.BM_CLICK, 0, 0)
                self._handled.append(hwnd)
                return True
        except Exception as e:
            logger.error(f"Close dialog failed: {e}")
        return False

    def confirm_dialog(self, hwnd: int):
        """确认弹窗"""
        return self.close_dialog(hwnd, "确定")

    def cancel_dialog(self, hwnd: int):
        """取消弹窗"""
        return self.close_dialog(hwnd, "取消")

    def _is_target_dialog(self, title: str) -> bool:
        """判断是否是目标弹窗"""
        all_titles = self.WARNING_TITLES + self.CONFIRM_TITLES
        return any(t in title for t in all_titles)

    def _get_dialog_text(self, hwnd: int) -> str:
        """获取弹窗文本"""
        # 获取弹窗中的文本内容
        pass

    def _find_button(self, hwnd: int, text: str) -> Optional[int]:
        """查找按钮"""
        def callback(btn_hwnd, buttons):
            if text in win32gui.GetWindowText(btn_hwnd):
                buttons.append(btn_hwnd)
            return True

        buttons = []
        win32gui.EnumChildWindows(hwnd, callback, buttons)
        return buttons[0] if buttons else None
```

**6.2 窗口管理**

```python
# backtrader/ui/window.py
import win32gui
import win32con
from typing import Optional

class WindowManager:
    """窗口管理器"""

    @staticmethod
    def find_window(title: str = None, class_name: str = None) -> Optional[int]:
        """查找窗口"""
        def callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                match = True
                if title:
                    match = match and title in win32gui.GetWindowText(hwnd)
                if class_name:
                    match = match and class_name in win32gui.GetClassName(hwnd)
                if match:
                    windows.append(hwnd)
            return True

        windows = []
        win32gui.EnumWindows(callback, windows)
        return windows[0] if windows else None

    @staticmethod
    def set_foreground(hwnd: int):
        """设置窗口前置"""
        try:
            if win32gui.IsIconic(hwnd):  # 最小化
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        except Exception as e:
            logger.error(f"Set foreground failed: {e}")

    @staticmethod
    def is_minimized(hwnd: int) -> bool:
        """检查是否最小化"""
        return win32gui.IsIconic(hwnd)

    @staticmethod
    def get_window_rect(hwnd: int) -> tuple:
        """获取窗口位置"""
        return win32gui.GetWindowRect(hwnd)
```

#### 7. 日志系统

**7.1 审计日志**

```python
# backtrader/utils/logging/audit.py
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
from .mask import mask_sensitive_info

class AuditLogger:
    """审计日志记录器"""

    def __init__(self, log_dir: str = "logs/audit"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("backtrader.audit")

    def log_order(self, order: Dict[str, Any]):
        """记录订单"""
        self._write_log("order", order)

    def log_query(self, query_type: str, result: Dict[str, Any]):
        """记录查询"""
        self._write_log("query", {
            'type': query_type,
            'result': result
        })

    def log_login(self, user: str, success: bool, error: str = None):
        """记录登录"""
        self._write_log("login", {
            'user': mask_sensitive_info(user),
            'success': success,
            'error': error
        })

    def log_error(self, error: Exception, context: Dict[str, Any] = None):
        """记录错误"""
        self._write_log("error", {
            'type': type(error).__name__,
            'message': str(error),
            'context': context or {}
        })

    def _write_log(self, log_type: str, data: Dict[str, Any]):
        """写入日志"""
        # 脱敏处理
        data = mask_sensitive_info(data)

        # 添加时间戳
        data['timestamp'] = datetime.now().isoformat()
        data['type'] = log_type

        # 按日期分文件
        date_str = datetime.now().strftime("%Y%m%d")
        log_file = self.log_dir / f"{date_str}.jsonl"

        # 追加写入
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(data, ensure_ascii=False) + '\n')

# 全局审计日志记录器
audit_logger = AuditLogger()
```

**7.2 敏感信息脱敏**

```python
# backtrader/utils/logging/mask.py
import re
from typing import Any, Dict

# 默认脱敏规则
DEFAULT_MASK_RULES = [
    ('password', '***'),
    ('passwd', '***'),
    ('pwd', '***'),
    ('account', '***'),
    ('user', '***'),
]

def mask_value(value: str, mask: str = '***') -> str:
    """脱敏单个值"""
    if not value:
        return value

    # 保留部分信息
    if len(value) <= 4:
        return mask
    return value[:2] + mask + value[-2:]

def mask_sensitive_info(data: Any, rules: list = None) -> Any:
    """脱敏敏感信息"""
    rules = rules or DEFAULT_MASK_RULES

    if isinstance(data, dict):
        return {k: _mask_dict_value(k, v, rules) for k, v in data.items()}
    elif isinstance(data, list):
        return [mask_sensitive_info(item, rules) for item in data]
    else:
        return data

def _mask_dict_value(key: str, value: Any, rules: list) -> Any:
    """脱敏字典值"""
    # 检查是否需要脱敏
    for pattern, mask in rules:
        if pattern in key.lower():
            if isinstance(value, str):
                return mask_value(value, mask)
            return mask

    # 递归处理嵌套结构
    return mask_sensitive_info(value, rules)
```

### 实现计划

#### 第一阶段：券商适配器（优先级：高）
1. 实现BrokerAdapter基类
2. 实现BrokerFactory工厂类
3. 实现配置管理系统
4. 实现华泰/同花顺/银河适配器

#### 第二阶段：数据获取策略（优先级：中）
1. 实现DataFetchStrategy基类
2. 实现Copy/File/API策略
3. 实现StrategyManager管理器

#### 第三阶段：异常处理（优先级：高）
1. 实现自定义异常类型
2. 实现弹窗处理器
3. 实现登录状态管理

#### 第四阶段：性能监控（优先级：中）
1. 实现perf_clock装饰器
2. 实现性能监控器
3. 实现性能预警

#### 第五阶段：跟单功能（优先级：中）
1. 实现FollowerBase基类
2. 实现信号过滤器
3. 实现聚米/米筐跟单

#### 第六阶段：UI自动化（优先级：低）
1. 实现弹窗处理器
2. 实现窗口管理器
3. 实现剪贴板操作

#### 第七阶段：日志系统（优先级：中）
1. 实现审计日志
2. 实现敏感信息脱敏
3. 实现日志查询和回放

### API兼容性保证

所有新增功能保持与现有backtrader API的兼容性：

1. **向后兼容**: 现有代码无需修改即可运行
2. **可选启用**: 新功能通过选择使用
3. **渐进增强**: 用户可以选择使用新功能或保持原有方式

```python
# 示例：传统方式（保持不变）
import backtrader as bt

cerebro = bt.Cerebro()
cerebro.setbroker(bt.brokers.BackBroker())
result = cerebro.run()

# 示例：新方式（可选）
from backtrader.brokers.factory import use

# 创建券商适配器
broker = use('ht')  # 华泰证券
broker.login('user', 'password')

# 使用适配器
cerebro = bt.Cerebro()
cerebro.set_broker(broker)
result = cerebro.run()
```

### 使用示例

**券商适配器使用示例：**

```python
from backtrader.brokers.factory import use

# 创建华泰证券适配器
broker = use('ht')
broker.login('username', 'password')

# 查询资金
balance = broker.balance
print(f"总资产: {balance.total}, 可用: {balance.available}")

# 查询持仓
positions = broker.position
for symbol, pos in positions.items():
    print(f"{symbol}: {pos.volume}股")

# 买入
result = broker.buy('600000', 10.0, 100)
print(f"订单ID: {result.order_id}")

# 卖出
result = broker.sell('600000', 10.5, 100)
```

**跟单功能使用示例：**

```python
from backtrader.follower.joinquant import JoinQuantFollower
from backtrader.brokers.factory import use
from backtrader.follower.filter import symbol_filter, amount_filter

# 创建券商适配器
broker = use('ht')
broker.login('user', 'password')

# 创建跟单器
follower = JoinQuantFollower(broker)
follower.login('jq_user', 'jq_password')

# 创建过滤器
signal_filter = symbol_filter(['600000', '000001'])

# 启动跟单
follower.follow(
    users=['target_user'],
    strategies=['target_strategy'],
    track_interval=5,
    signal_filter=signal_filter
)
```

**性能监控使用示例：**

```python
from backtrader.monitor.perf import perf_clock, perf_monitor

class MyBroker:
    @perf_clock
    def buy(self, symbol, price, amount):
        # 交易逻辑
        pass

# 查看性能统计
stats = perf_monitor.get_all_stats()
for name, stat in stats.items():
    print(f"{name}: 平均 {stat['avg']:.4f}s")
```

### 测试策略

1. **单元测试**: 每个新增模块的单元测试覆盖率 > 80%
2. **集成测试**: 与现有功能的集成测试
3. **模拟测试**: 使用模拟客户端测试GUI自动化
4. **性能测试**: 性能监控开销 < 5%
5. **兼容性测试**: 确保现有代码无需修改即可运行
