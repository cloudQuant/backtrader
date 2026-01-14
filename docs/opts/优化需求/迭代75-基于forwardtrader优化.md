### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/forwardtrader
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### forwardtrader项目简介
forwardtrader是一个前向测试框架，专注于策略的前向验证，具有以下核心特点：
- **前向测试**: 专注于策略前向验证
- **实时模拟**: 模拟实时交易环境
- **策略验证**: 验证回测策略的有效性
- **过拟合检测**: 帮助检测过拟合问题
- **回测对比**: 与历史回测结果对比
- **渐进验证**: 渐进式策略验证

### 重点借鉴方向
1. **前向测试**: 前向测试框架设计
2. **过拟合检测**: 过拟合检测机制
3. **实时模拟**: 实时交易模拟
4. **策略验证**: 策略验证流程
5. **结果对比**: 回测与前向结果对比
6. **渐进验证**: 滚动窗口验证

---

## 项目对比分析

### Backtrader vs ForwardTrader 架构对比

| 维度 | Backtrader | ForwardTrader |
|------|------------|---------------|
| **核心定位** | 回测和实盘框架 | 前向测试（模拟实盘） |
| **运行模式** | 回测/实盘分离 | 历史阶段+实盘阶段统一 |
| **数据粒度** | Bar级（K线） | Tick级聚合 |
| **连接管理** | 基础连接 | 智能重连机制 |
| **数据源** | 多种数据源 | 天勤API专用 |
| **时间管理** | 基础时间过滤 | SessionCalendar多时段管理 |
| **持仓管理** | 简单持仓 | 今昨仓分离 |
| **数据持久化** | Analyzer分析器 | 自动保存交易记录CSV |
| **过拟合检测** | 无 | 回测与前向结果对比 |
| **多档行情** | 无 | bid_price1/ask_price1等多档 |

### ForwardTrader可借鉴的核心优势

#### 1. 前向测试框架
- **双阶段运行**: 历史数据阶段跳过，实盘阶段正常执行
- **无缝切换**: 从历史数据平滑过渡到实时数据
- **策略一致性**: 同一套策略代码用于回测和前向测试

#### 2. 智能重连机制
- **固定时点重连**: 9:00、13:30、21:00定时重连
- **异常重连**: 连接断开时自动重连
- **重连记录**: 避免重复重连
- **每日重置**: 21:20清空重连记录

#### 3. Tick级数据处理
- **精确K线合成**: Tick数据精确聚合为分钟K线
- **多档行情支持**: bid_price1/ask_price1, bid_price2/ask_price2
- **价格序列缓存**: 确保数据完整性

#### 4. 交易时间管理
- **多品种时段**: 支持不同品种的交易时段配置
- **日夜盘识别**: 正确区分日盘和夜盘
- **交易日历**: 集成交易日历功能

#### 5. 数据持久化
- **自动保存**: 交易记录自动保存到CSV
- **完整记录**: 订单、成交、持仓、账户信息
- **便于分析**: 支持后续数据分析和对比

#### 6. 今昨仓管理
- **持仓分离**: 今仓和昨仓分别管理
- **优先平今**: 可配置平仓顺序
- **保证金计算**: 区分今昨仓保证金

---

## 需求文档

### 需求概述

借鉴forwardtrader项目的前向测试设计理念，为backtrader添加以下功能模块，提升策略验证能力和实盘交易稳定性：

### 功能需求

#### FR1: 前向测试框架

**FR1.1 双阶段运行模式**
- 需求描述: 支持历史数据阶段和实时数据阶段的统一运行
- 优先级: 高
- 验收标准:
  - 支持history_phase参数控制运行阶段
  - 历史阶段策略跳过执行（仅预热指标）
  - 实时阶段策略正常执行
  - 支持阶段自动切换

**FR1.2 无缝数据切换**
- 需求描述: 历史数据到实时数据的平滑过渡
- 优先级: 高
- 验收标准:
  - 历史数据自动预加载（可配置长度）
  - 切换点自动识别
  - 指标状态无缝衔接
  - 不产生数据缺口

**FR1.3 前向测试引擎**
- 需求描述: 专门的前向测试引擎
- 优先级: 中
- 验收标准:
  - 实现ForwardTestEngine类
  - 支持策略参数配置
  - 支持测试结果导出

#### FR2: 过拟合检测

**FR2.1 回测前向对比**
- 需求描述: 回测结果与前向测试结果对比
- 优先级: 高
- 验收标准:
  - 支持加载历史回测结果
  - 支持前向测试结果记录
  - 生成对比报告
  - 计算结果偏离度

**FR2.2 性能衰减检测**
- 需求描述: 检测策略性能衰减
- 优先级: 中
- 验收标准:
  - 计算收益率衰减
  - 计算夏普比率衰减
  - 计算最大回撤差异
  - 性能衰减预警

**FR2.3 稳定性评估**
- 需求描述: 评估策略稳定性
- 优先级: 中
- 验收标准:
  - 计算收益波动率
  - 计算胜率变化
  - 计算盈亏比变化
  - 生成稳定性评分

#### FR3: 智能重连机制

**FR3.1 固定时点重连**
- 需求描述: 在固定时点自动重连
- 优先级: 中
- 验收标准:
  - 支持配置重连时点
  - 到时自动触发重连
  - 重连前记录日志

**FR3.2 异常重连**
- 需求描述: 连接异常时自动重连
- 优先级: 高
- 验收标准:
  - 检测连接断开
  - 自动触发重连
  - 支持重连间隔配置
  - 支持最大重连次数

**FR3.3 重连管理**
- 需求描述: 管理重连状态和记录
- 优先级: 中
- 验收标准:
  - 记录重连历史
  - 避免重复重连
  - 每日定时重置
  - 重连状态查询

#### FR4: Tick级数据处理

**FR4.1 Tick数据源**
- 需求描述: 支持Tick级数据输入
- 优先级: 高
- 验收标准:
  - 实现TickDataFeed类
  - 支持实时Tick订阅
  - 支持Tick历史数据回放

**FR4.2 Tick聚合**
- 需求描述: Tick数据聚合为K线
- 优先级: 高
- 验收标准:
  - 支持自定义聚合周期
  - 支持秒级、分钟级聚合
  - OHLCV计算正确
  - 支持多档行情聚合

**FR4.3 多档行情**
- 需求描述: 支持买卖多档行情
- 优先级: 中
- 验收标准:
  - 支持bid_price1-5/ask_price1-5
  - 支持bid_volume1-5/ask_volume1-5
  - 策略可访问多档数据

#### FR5: 交易时间管理

**FR5.1 交易时段配置**
- 需求描述: 配置不同品种的交易时段
- 优先级: 中
- 验收标准:
  - 支持多时段配置
  - 支持日盘/夜盘区分
  - 支持品种差异化配置

**FR5.2 交易日历**
- 需求描述: 集成交易日历
- 优先级: 中
- 验收标准:
  - 支持交易日查询
  - 支持节假日过滤
  - 支持半日交易识别

**FR5.3 时间过滤**
- 需求描述: 自动过滤非交易时段数据
- 优先级: 低
- 验收标准:
  - 自动识别交易时段
  - 过滤非交易时段数据
  - 正确处理跨日数据

#### FR6: 今昨仓管理

**FR6.1 持仓分离**
- 需求描述: 今仓和昨仓分别管理
- 优先级: 中
- 验收标准:
  - 区分today_volume/yesterday_volume
  - 支持查询今昨仓
  - 持仓明细记录

**FR6.2 平仓优先级**
- 需求描述: 配置平仓顺序
- 优先级: 中
- 验收标准:
  - 支持优先平今/平昨配置
  - 自动判断可平持仓
  - 平仓记录完整

**FR6.3 保证金计算**
- 需求描述: 区分今昨仓保证金
- 优先级: 低
- 验收标准:
  - 今仓保证金计算
  - 昨仓保证金计算
  - 总保证金汇总

#### FR7: 数据持久化

**FR7.1 交易记录**
- 需求描述: 自动保存交易记录
- 优先级: 中
- 验收标准:
  - 订单记录CSV导出
  - 成交记录CSV导出
  - 持仓记录CSV导出
  - 账户记录CSV导出

**FR7.2 性能数据**
- 需求描述: 保存性能分析数据
- 优先级: 中
- 验收标准:
  - 净值曲线数据
  - 回撤数据
  - 交易统计数据

**FR7.3 数据查询**
- 需求描述: 支持历史数据查询
- 优先级: 低
- 验收标准:
  - 按日期查询
  - 按品种查询
  - 数据导入导出

### 非功能需求

#### NFR1: 性能
- Tick数据处理延迟 < 10ms
- K线聚合计算 < 5ms
- 重连响应时间 < 3s
- 数据持久化写入 < 100ms

#### NFR2: 可靠性
- 连接断开检测 < 5s
- 重连成功率 > 95%
- 数据完整性 100%
- 系统可用性 > 99%

#### NFR3: 兼容性
- 保持与现有backtrader API兼容
- 支持Windows/Linux/MacOS
- 支持Python 3.7+

---

## 设计文档

### 整体架构设计

#### 新增模块结构

```
backtrader/
├── backtrader/
│   ├── forward/            # 新增：前向测试模块
│   │   ├── __init__.py
│   │   ├── engine.py       # 前向测试引擎
│   │   ├── phase.py        # 运行阶段管理
│   │   └── config.py       # 前向测试配置
│   ├── overfitting/        # 新增：过拟合检测模块
│   │   ├── __init__.py
│   │   ├── detector.py     # 过拟合检测器
│   │   ├── comparator.py   # 结果对比器
│   │   └── metrics.py      # 检测指标
│   ├── connection/         # 新增：连接管理模块
│   │   ├── __init__.py
│   │   ├── manager.py      # 连接管理器
│   │   ├── reconnect.py    # 重连策略
│   │   └── state.py        # 连接状态
│   ├── tick/               # 新增：Tick数据处理模块
│   │   ├── __init__.py
│   │   ├── feed.py         # Tick数据源
│   │   ├── aggregator.py   # Tick聚合器
│   │   └── quote.py        # 多档行情
│   ├── session/            # 新增：交易时间管理
│   │   ├── __init__.py
│   │   ├── calendar.py     # 交易日历
│   │   ├── schedule.py     # 交易时段
│   │   └── filter.py       # 时间过滤器
│   ├── position/           # 增强：持仓管理
│   │   ├── __init__.py
│   │   ├── manager.py      # 持仓管理器
│   │   ├── today.py        # 今仓管理
│   │   └── yesterday.py    # 昨仓管理
│   └── persistence/        # 新增：数据持久化
│       ├── __init__.py
│       ├── recorder.py     # 记录器
│       ├── exporter.py     # 导出器
│       └── storage.py      # 存储接口
```

### 详细设计

#### 1. 前向测试引擎

**1.1 运行阶段管理**

```python
# backtrader/forward/phase.py
from enum import Enum
from datetime import datetime

class PhaseType(Enum):
    """运行阶段类型"""
    HISTORY = "history"      # 历史数据阶段
    FORWARD = "forward"      # 前向测试阶段
    LIVE = "live"           # 实盘交易阶段

class PhaseManager:
    """阶段管理器"""

    def __init__(self, switch_time: datetime = None):
        self.switch_time = switch_time    # 切换时间点
        self.current_phase = PhaseType.HISTORY
        self._switched = False

    @property
    def history_phase(self) -> bool:
        """是否为历史阶段"""
        return self.current_phase == PhaseType.HISTORY

    @property
    def forward_phase(self) -> bool:
        """是否为前向阶段"""
        return self.current_phase == PhaseType.FORWARD

    def check_switch(self, current_time: datetime) -> bool:
        """检查是否需要切换阶段"""
        if self._switched:
            return False

        if self.switch_time and current_time >= self.switch_time:
            self.switch_phase()
            return True
        return False

    def switch_phase(self):
        """切换到前向阶段"""
        self.current_phase = PhaseType.FORWARD
        self._switched = True
```

**1.2 前向测试引擎**

```python
# backtrader/forward/engine.py
from backtrader import Cerebro
from .phase import PhaseManager, PhaseType
from .config import ForwardConfig

class ForwardTestEngine:
    """前向测试引擎"""

    def __init__(self, config: ForwardConfig = None):
        self.config = config or ForwardConfig()
        self.cerebro = Cerebro()
        self.phase_manager = PhaseManager()
        self._setup()

    def _setup(self):
        """设置引擎"""
        # 添加数据源
        for data_config in self.config.data_configs:
            data_feed = self._create_data_feed(data_config)
            self.cerebro.adddata(data_feed)

        # 添加策略
        for strategy_config in self.config.strategy_configs:
            self.cerebro.addstrategy(
                strategy_config.cls,
                **strategy_config.params
            )

        # 设置阶段切换时间
        if self.config.switch_time:
            self.phase_manager.switch_time = self.config.switch_time

    def add_strategy(self, strategy_cls, **params):
        """添加策略"""
        self.cerebro.addstrategy(strategy_cls, phase_manager=self.phase_manager, **params)

    def add_data(self, data):
        """添加数据源"""
        self.cerebro.adddata(data)

    def run(self):
        """运行前向测试"""
        # 第一阶段：历史数据预热
        if self.config.history_length:
            self._run_history_phase()

        # 第二阶段：前向测试
        self._run_forward_phase()

        return {
            'history': self.history_results,
            'forward': self.forward_results
        }

    def _run_history_phase(self):
        """运行历史阶段"""
        self.phase_manager.current_phase = PhaseType.HISTORY
        # 设置数据长度限制
        # 执行但不交易
        self.history_results = []

    def _run_forward_phase(self):
        """运行前向阶段"""
        self.phase_manager.switch_phase()
        self.forward_results = self.cerebro.run()

    def get_comparison(self):
        """获取对比结果"""
        from overfitting.comparator import ResultComparator
        comparator = ResultComparator()
        return comparator.compare(
            self.history_results,
            self.forward_results
        )
```

**1.3 前向测试配置**

```python
# backtrader/forward/config.py
from dataclasses import dataclass, field
from typing import List, Dict, Any
from datetime import datetime, time

@dataclass
class DataConfig:
    """数据配置"""
    symbol: str
    start: datetime = None
    end: datetime = None
    history_length: int = 10000    # 历史数据长度
    from_datetime: datetime = None # 切换时间点

@dataclass
class StrategyConfig:
    """策略配置"""
    cls: type
    params: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ForwardConfig:
    """前向测试配置"""
    # 数据配置
    data_configs: List[DataConfig] = field(default_factory=list)

    # 策略配置
    strategy_configs: List[StrategyConfig] = field(default_factory=list)

    # 时间配置
    switch_time: datetime = None    # 阶段切换时间
    history_length: int = 10000     # 历史数据长度

    # 交易配置
    cash: float = 100000.0
    commission: float = 0.0003

    # 输出配置
    output_dir: str = "./forward_results"
    save_records: bool = True
```

#### 2. 过拟合检测

**2.1 过拟合检测器**

```python
# backtrader/overfitting/detector.py
from typing import Dict, List, Tuple
from .metrics import DecayMetrics, StabilityMetrics

class OverfittingDetector:
    """过拟合检测器"""

    def __init__(self):
        self.decay_metrics = DecayMetrics()
        self.stability_metrics = StabilityMetrics()

    def detect(self, backtest_result: Dict, forward_result: Dict) -> Dict:
        """检测过拟合"""
        return {
            'decay': self._detect_decay(backtest_result, forward_result),
            'stability': self._detect_stability(forward_result),
            'verdict': self._make_verdict()
        }

    def _detect_decay(self, backtest: Dict, forward: Dict) -> Dict:
        """检测性能衰减"""
        return {
            'return_decay': self.decay_metrics.return_decay(backtest, forward),
            'sharpe_decay': self.decay_metrics.sharpe_decay(backtest, forward),
            'drawdown_delta': self.decay_metrics.drawdown_delta(backtest, forward),
        }

    def _detect_stability(self, forward: Dict) -> Dict:
        """检测稳定性"""
        return {
            'volatility': self.stability_metrics.volatility(forward),
            'win_rate_change': self.stability_metrics.win_rate_change(forward),
            'profit_loss_ratio': self.stability_metrics.profit_loss_ratio(forward),
        }

    def _make_verdict(self) -> str:
        """给出判断结论"""
        # 综合判断逻辑
        return "unknown"
```

**2.2 结果对比器**

```python
# backtrader/overfitting/comparator.py
from typing import Dict, List
import pandas as pd

class ResultComparator:
    """结果对比器"""

    def compare(self, backtest_result: Dict, forward_result: Dict) -> Dict:
        """对比回测和前向结果"""
        return {
            'summary': self._summary_comparison(backtest_result, forward_result),
            'returns': self._returns_comparison(backtest_result, forward_result),
            'drawdowns': self._drawdowns_comparison(backtest_result, forward_result),
            'trades': self._trades_comparison(backtest_result, forward_result),
        }

    def _summary_comparison(self, backtest: Dict, forward: Dict) -> Dict:
        """汇总对比"""
        return {
            'backtest_return': backtest.get('total_return', 0),
            'forward_return': forward.get('total_return', 0),
            'return_delta': forward.get('total_return', 0) - backtest.get('total_return', 0),
            'return_ratio': forward.get('total_return', 0) / backtest.get('total_return', 1),
        }

    def _returns_comparison(self, backtest: Dict, forward: Dict) -> Dict:
        """收益对比"""
        backtest_returns = backtest.get('returns_curve', [])
        forward_returns = forward.get('returns_curve', [])

        return {
            'correlation': self._correlation(backtest_returns, forward_returns),
            'mean_delta': forward.get('mean_return', 0) - backtest.get('mean_return', 0),
            'std_delta': forward.get('std_return', 0) - backtest.get('std_return', 0),
        }

    def _drawdowns_comparison(self, backtest: Dict, forward: Dict) -> Dict:
        """回撤对比"""
        return {
            'backtest_max_dd': backtest.get('max_drawdown', 0),
            'forward_max_dd': forward.get('max_drawdown', 0),
            'dd_delta': forward.get('max_drawdown', 0) - backtest.get('max_drawdown', 0),
        }

    def _trades_comparison(self, backtest: Dict, forward: Dict) -> Dict:
        """交易对比"""
        return {
            'backtest_trades': backtest.get('total_trades', 0),
            'forward_trades': forward.get('total_trades', 0),
            'win_rate_delta': forward.get('win_rate', 0) - backtest.get('win_rate', 0),
        }

    def _correlation(self, a: List[float], b: List[float]) -> float:
        """计算相关系数"""
        # 实现相关系数计算
        pass

    def generate_report(self, comparison: Dict) -> str:
        """生成对比报告"""
        report = []
        report.append("=" * 60)
        report.append("前向测试对比报告")
        report.append("=" * 60)

        summary = comparison['summary']
        report.append(f"\n回测收益率: {summary['backtest_return']:.2%}")
        report.append(f"前向收益率: {summary['forward_return']:.2%}")
        report.append(f"收益率差异: {summary['return_delta']:.2%}")
        report.append(f"收益率比率: {summary['return_ratio']:.2%}")

        return "\n".join(report)
```

**2.3 检测指标**

```python
# backtrader/overfitting/metrics.py
from typing import Dict, List
import numpy as np

class DecayMetrics:
    """性能衰减指标"""

    def return_decay(self, backtest: Dict, forward: Dict) -> float:
        """收益率衰减"""
        backtest_return = backtest.get('total_return', 0)
        forward_return = forward.get('total_return', 0)
        if backtest_return == 0:
            return 0
        return (backtest_return - forward_return) / abs(backtest_return)

    def sharpe_decay(self, backtest: Dict, forward: Dict) -> float:
        """夏普比率衰减"""
        backtest_sharpe = backtest.get('sharpe_ratio', 0)
        forward_sharpe = forward.get('sharpe_ratio', 0)
        return backtest_sharpe - forward_sharpe

    def drawdown_delta(self, backtest: Dict, forward: Dict) -> float:
        """回撤差异"""
        backtest_dd = backtest.get('max_drawdown', 0)
        forward_dd = forward.get('max_drawdown', 0)
        return forward_dd - backtest_dd

class StabilityMetrics:
    """稳定性指标"""

    def volatility(self, forward: Dict) -> float:
        """收益波动率"""
        returns = forward.get('returns_curve', [])
        if not returns:
            return 0
        return np.std(returns) * np.sqrt(252)

    def win_rate_change(self, forward: Dict) -> float:
        """胜率变化"""
        # 计算胜率的时间变化
        trades = forward.get('trades', [])
        if len(trades) < 10:
            return 0

        # 分段计算胜率
        mid = len(trades) // 2
        first_half_win_rate = sum(1 for t in trades[:mid] if t.get('pnl', 0) > 0) / mid
        second_half_win_rate = sum(1 for t in trades[mid:] if t.get('pnl', 0) > 0) / (len(trades) - mid)

        return second_half_win_rate - first_half_win_rate

    def profit_loss_ratio(self, forward: Dict) -> float:
        """盈亏比"""
        trades = forward.get('trades', [])
        profits = [t.get('pnl', 0) for t in trades if t.get('pnl', 0) > 0]
        losses = [abs(t.get('pnl', 0)) for t in trades if t.get('pnl', 0) < 0]

        if not profits or not losses:
            return 0

        return np.mean(profits) / np.mean(losses)
```

#### 3. 智能重连机制

**3.1 连接管理器**

```python
# backtrader/connection/manager.py
from typing import Callable, List, Dict
from datetime import datetime, time
from .state import ConnectionState
from .reconnect import ReconnectStrategy

class ConnectionManager:
    """连接管理器"""

    def __init__(self):
        self.state = ConnectionState.DISCONNECTED
        self.reconnect_strategy = ReconnectStrategy()
        self.reconnect_times: List[datetime] = []
        self._callbacks: Dict[str, List[Callable]] = {}

    def connect(self, connect_func: Callable) -> bool:
        """建立连接"""
        try:
            result = connect_func()
            if result:
                self.state = ConnectionState.CONNECTED
                self._emit('connected')
                return True
        except Exception as e:
            self._emit('error', e)
        return False

    def disconnect(self):
        """断开连接"""
        self.state = ConnectionState.DISCONNECTED
        self._emit('disconnected')

    def check_connection(self) -> bool:
        """检查连接状态"""
        return self.state == ConnectionState.CONNECTED

    def should_reconnect(self, current_time: datetime = None) -> bool:
        """判断是否需要重连"""
        return self.reconnect_strategy.should_reconnect(
            self.state,
            self.reconnect_times,
            current_time or datetime.now()
        )

    def reconnect(self, connect_func: Callable) -> bool:
        """执行重连"""
        now = datetime.now()

        # 检查是否需要重连
        if not self.should_reconnect(now):
            return False

        # 执行重连
        if self.connect(connect_func):
            self.reconnect_times.append(now)
            self._emit('reconnected')
            return True

        return False

    def on(self, event: str, callback: Callable):
        """注册事件回调"""
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _emit(self, event: str, *args):
        """触发事件"""
        if event in self._callbacks:
            for callback in self._callbacks[event]:
                callback(*args)

    def reset_daily(self, reset_time: time = time(21, 20)):
        """每日重置重连记录"""
        now = datetime.now()
        if now.time() >= reset_time:
            self.reconnect_times.clear()
            self._emit('reset')
```

**3.2 重连策略**

```python
# backtrader/connection/reconnect.py
from datetime import datetime, time
from typing import List

class ReconnectStrategy:
    """重连策略"""

    def __init__(self):
        # 固定重连时点
        self.fixed_times = [
            time(9, 0),    # 9:00
            time(13, 30),  # 13:30
            time(21, 0),   # 21:00
        ]

        # 异常重连配置
        self.max_retries = 3
        self.retry_interval = 5  # 秒
        self.cooldown_interval = 60  # 冷却时间

        # 每日重置时间
        self.daily_reset_time = time(21, 20)

    def should_reconnect(self, state: 'ConnectionState',
                        reconnect_times: List[datetime],
                        current_time: datetime) -> bool:
        """判断是否需要重连"""
        # 连接正常则不需要重连
        if state == ConnectionState.CONNECTED:
            return False

        # 检查固定时点重连
        if self._should_fixed_reconnect(current_time):
            return True

        # 检查异常重连
        if self._should_error_reconnect(reconnect_times, current_time):
            return True

        return False

    def _should_fixed_reconnect(self, current_time: datetime) -> bool:
        """检查固定时点重连"""
        current_time_only = current_time.time()
        for fixed_time in self.fixed_times:
            # 允许5分钟误差
            if abs((current_time_only.hour - fixed_time.hour) * 60 +
                   current_time_only.minute - fixed_time.minute) <= 5:
                return True
        return False

    def _should_error_reconnect(self, reconnect_times: List[datetime],
                               current_time: datetime) -> bool:
        """检查异常重连"""
        if not reconnect_times:
            return True

        # 检查重连次数
        if len(reconnect_times) >= self.max_retries:
            return False

        # 检查冷却时间
        last_reconnect = reconnect_times[-1]
        if (current_time - last_reconnect).total_seconds() < self.cooldown_interval:
            return False

        return True
```

**3.3 连接状态**

```python
# backtrader/connection/state.py
from enum import Enum

class ConnectionState(Enum):
    """连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
```

#### 4. Tick级数据处理

**4.1 Tick数据源**

```python
# backtrader/tick/feed.py
from backtrader.feed import DataBase
from backtrader import date2num
from .aggregator import TickAggregator
from .quote import MultiLevelQuote

class TickData(DataBase):
    """Tick数据源"""

    params = (
        ('aggregator', None),      # Tick聚合器
        ('aggregate_period', 60),  # 聚合周期（秒）
    )

    def __init__(self):
        super().__init__()
        self.aggregator = self.p.aggregator or TickAggregator(self.p.aggregate_period)
        self.current_bar = None

    def _load(self):
        """加载Tick数据并聚合为K线"""
        # 获取新的Tick
        tick = self._get_next_tick()
        if tick is None:
            return False

        # 添加到聚合器
        self.aggregator.add_tick(tick)

        # 检查是否生成新的K线
        if self.aggregator.is_bar_ready():
            bar = self.aggregator.get_bar()
            self.lines.datetime[0] = date2num(bar.datetime)
            self.lines.open[0] = bar.open
            self.lines.high[0] = bar.high
            self.lines.low[0] = bar.low
            self.lines.close[0] = bar.close
            self.lines.volume[0] = bar.volume

            # 多档行情
            if hasattr(self.lines, 'bid1'):
                self.lines.bid1[0] = bar.quote.bid_price1
                self.lines.ask1[0] = bar.quote.ask_price1

            return True

        return False

    def _get_next_tick(self):
        """获取下一个Tick（子类实现）"""
        pass
```

**4.2 Tick聚合器**

```python
# backtrader/tick/aggregator.py
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List
from .quote import MultiLevelQuote

@dataclass
class Tick:
    """Tick数据"""
    datetime: datetime
    price: float
    volume: int
    bid_price1: float = 0
    ask_price1: float = 0
    bid_volume1: int = 0
    ask_volume1: int = 0
    # 更多档位...
    quote: MultiLevelQuote = None

@dataclass
class Bar:
    """K线数据"""
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    quote: MultiLevelQuote = None

class TickAggregator:
    """Tick聚合器"""

    def __init__(self, period: int = 60):
        self.period = period  # 聚合周期（秒）
        self.ticks: List[Tick] = []
        self.current_bar_start: datetime = None

    def add_tick(self, tick: Tick):
        """添加Tick数据"""
        if self.current_bar_start is None:
            self.current_bar_start = tick.datetime

        self.ticks.append(tick)

    def is_bar_ready(self) -> bool:
        """检查是否生成新K线"""
        if not self.ticks:
            return False

        last_tick = self.ticks[-1]
        elapsed = (last_tick.datetime - self.current_bar_start).total_seconds()

        return elapsed >= self.period

    def get_bar(self) -> Bar:
        """获取聚合后的K线"""
        if not self.ticks:
            return None

        prices = [t.price for t in self.ticks]
        volumes = [t.volume for t in self.ticks]

        bar = Bar(
            datetime=self.current_bar_start,
            open=prices[0],
            high=max(prices),
            low=min(prices),
            close=prices[-1],
            volume=sum(volumes),
            quote=self._aggregate_quotes()
        )

        # 重置
        self.ticks.clear()
        self.current_bar_start = None

        return bar

    def _aggregate_quotes(self) -> MultiLevelQuote:
        """聚合多档行情"""
        if not self.ticks:
            return None

        # 使用最后一个Tick的报价
        return self.ticks[-1].quote
```

**4.3 多档行情**

```python
# backtrader/tick/quote.py
from dataclasses import dataclass

@dataclass
class MultiLevelQuote:
    """多档行情"""
    # 买档
    bid_price1: float = 0
    bid_price2: float = 0
    bid_price3: float = 0
    bid_price4: float = 0
    bid_price5: float = 0

    bid_volume1: int = 0
    bid_volume2: int = 0
    bid_volume3: int = 0
    bid_volume4: int = 0
    bid_volume5: int = 0

    # 卖档
    ask_price1: float = 0
    ask_price2: float = 0
    ask_price3: float = 0
    ask_price4: float = 0
    ask_price5: float = 0

    ask_volume1: int = 0
    ask_volume2: int = 0
    ask_volume3: int = 0
    ask_volume4: int = 0
    ask_volume5: int = 0

    def spread(self) -> float:
        """买卖价差"""
        if self.ask_price1 > 0 and self.bid_price1 > 0:
            return self.ask_price1 - self.bid_price1
        return 0

    def mid_price(self) -> float:
        """中间价"""
        if self.ask_price1 > 0 and self.bid_price1 > 0:
            return (self.ask_price1 + self.bid_price1) / 2
        return 0
```

#### 5. 交易时间管理

**5.1 交易日历**

```python
# backtrader/session/calendar.py
from datetime import date, time, datetime, timedelta
from typing import List, Dict, Tuple, Optional

class TradingCalendar:
    """交易日历"""

    def __init__(self):
        self._trading_days = set()
        self._holidays = set()
        self._half_days = set()

    def add_trading_day(self, day: date):
        """添加交易日"""
        self._trading_days.add(day)

    def add_holiday(self, day: date):
        """添加节假日"""
        self._holidays.add(day)

    def add_half_day(self, day: date):
        """添加半日"""
        self._half_days.add(day)

    def is_trading_day(self, day: date) -> bool:
        """判断是否为交易日"""
        # 周末
        if day.weekday() >= 5:
            return False

        # 节假日
        if day in self._holidays:
            return False

        return True

    def is_half_day(self, day: date) -> bool:
        """判断是否为半日"""
        return day in self._half_days

    def get_trading_days(self, start: date, end: date) -> List[date]:
        """获取交易日列表"""
        days = []
        current = start
        while current <= end:
            if self.is_trading_day(current):
                days.append(current)
            current += timedelta(days=1)
        return days

    def next_trading_day(self, day: date) -> Optional[date]:
        """获取下一个交易日"""
        current = day + timedelta(days=1)
        max_days = 10  # 最多查找10天
        count = 0

        while count < max_days:
            if self.is_trading_day(current):
                return current
            current += timedelta(days=1)
            count += 1

        return None
```

**5.2 交易时段**

```python
# backtrader/session/schedule.py
from datetime import time, datetime
from typing import List, Dict, Tuple, Optional

class TradingSession:
    """交易时段"""

    def __init__(self, name: str, start: time, end: time):
        self.name = name
        self.start = start
        self.end = end

    def contains(self, check_time: time) -> bool:
        """检查时间是否在时段内"""
        if self.start <= self.end:
            return self.start <= check_time <= self.end
        else:  # 跨日时段（如夜盘）
            return check_time >= self.start or check_time <= self.end

class TradingSchedule:
    """交易时段管理"""

    def __init__(self):
        self._sessions: Dict[str, List[TradingSession]] = {}

    def add_session(self, symbol: str, session: TradingSession):
        """添加交易时段"""
        if symbol not in self._sessions:
            self._sessions[symbol] = []
        self._sessions[symbol].append(session)

    def get_sessions(self, symbol: str) -> List[TradingSession]:
        """获取品种的交易时段"""
        return self._sessions.get(symbol, self._get_default_sessions())

    def _get_default_sessions(self) -> List[TradingSession]:
        """获取默认交易时段"""
        return [
            TradingSession("day", time(9, 30), time(11, 30)),
            TradingSession("day", time(13, 0), time(15, 0)),
        ]

    def is_trading_time(self, symbol: str, check_time: datetime) -> bool:
        """检查是否为交易时间"""
        sessions = self.get_sessions(symbol)
        check_time_only = check_time.time()

        for session in sessions:
            if session.contains(check_time_only):
                return True

        return False

    def get_session_name(self, symbol: str, check_time: datetime) -> Optional[str]:
        """获取当前时段名称"""
        sessions = self.get_sessions(symbol)
        check_time_only = check_time.time()

        for session in sessions:
            if session.contains(check_time_only):
                return session.name

        return None

    def is_day_session(self, symbol: str, check_time: datetime) -> bool:
        """判断是否为日盘"""
        return self.get_session_name(symbol, check_time) == "day"

    def is_night_session(self, symbol: str, check_time: datetime) -> bool:
        """判断是否为夜盘"""
        return self.get_session_name(symbol, check_time) == "night"
```

**5.3 时间过滤器**

```python
# backtrader/session/filter.py
from datetime import datetime
from .calendar import TradingCalendar
from .schedule import TradingSchedule

class TimeFilter:
    """时间过滤器"""

    def __init__(self, calendar: TradingCalendar = None, schedule: TradingSchedule = None):
        self.calendar = calendar or TradingCalendar()
        self.schedule = schedule or TradingSchedule()

    def should_filter(self, dt: datetime, symbol: str = None) -> bool:
        """判断是否应该过滤该时间点"""
        # 检查是否为交易日
        if not self.calendar.is_trading_day(dt.date()):
            return True

        # 检查是否为交易时间
        if symbol and not self.schedule.is_trading_time(symbol, dt):
            return True

        return False

    def filter_data(self, data: List[dict], symbol: str = None) -> List[dict]:
        """过滤数据列表"""
        return [
            d for d in data
            if not self.should_filter(d['datetime'], symbol)
        ]
```

#### 6. 今昨仓管理

**6.1 持仓管理器**

```python
# backtrader/position/manager.py
from typing import Dict, Optional
from .today import TodayPosition
from .yesterday import YesterdayPosition

class PositionManager:
    """持仓管理器"""

    def __init__(self):
        self.today_positions: Dict[str, TodayPosition] = {}
        self.yesterday_positions: Dict[str, YesterdayPosition] = {}

    def get_position(self, symbol: str) -> Dict:
        """获取完整持仓信息"""
        today = self.today_positions.get(symbol, TodayPosition(symbol))
        yesterday = self.yesterday_positions.get(symbol, YesterdayPosition(symbol))

        return {
            'symbol': symbol,
            'today_long': today.long_volume,
            'today_short': today.short_volume,
            'yesterday_long': yesterday.long_volume,
            'yesterday_short': yesterday.short_volume,
            'total_long': today.long_volume + yesterday.long_volume,
            'total_short': today.short_volume + yesterday.short_volume,
        }

    def update_today(self, symbol: str, long_change: int, short_change: int):
        """更新今仓"""
        if symbol not in self.today_positions:
            self.today_positions[symbol] = TodayPosition(symbol)
        self.today_positions[symbol].update(long_change, short_change)

    def set_yesterday(self, symbol: str, long_volume: int, short_volume: int):
        """设置昨仓"""
        self.yesterday_positions[symbol] = YesterdayPosition(
            symbol, long_volume, short_volume
        )

    def get_available_close(self, symbol: str, direction: str,
                           close_today_first: bool = True) -> int:
        """获取可平持仓数量"""
        position = self.get_position(symbol)

        if direction == 'long':
            if close_today_first:
                return position['today_long'] + position['yesterday_long']
            else:
                return position['yesterday_long'] + position['today_long']
        else:  # short
            if close_today_first:
                return position['today_short'] + position['yesterday_short']
            else:
                return position['yesterday_short'] + position['today_short']
```

**6.2 今仓管理**

```python
# backtrader/position/today.py
from dataclasses import dataclass, field

@dataclass
class TodayPosition:
    """今仓"""

    symbol: str
    long_volume: int = 0
    short_volume: int = 0
    long_open_price: float = 0
    short_open_price: float = 0
    long_cost: float = 0
    short_cost: float = 0

    def update(self, long_change: int, short_change: int, price: float = 0):
        """更新今仓"""
        if long_change > 0:  # 开多
            self.long_volume += long_change
            self.long_open_price = ((self.long_open_price * (self.long_volume - long_change) +
                                     price * long_change) / self.long_volume
                                    if self.long_volume > 0 else price)
        elif long_change < 0:  # 平多
            self.long_volume += long_change  # long_change是负数

        if short_change > 0:  # 开空
            self.short_volume += short_change
            self.short_open_price = ((self.short_open_price * (self.short_volume - short_change) +
                                      price * short_change) / self.short_volume
                                     if self.short_volume > 0 else price)
        elif short_change < 0:  # 平空
            self.short_volume += short_change  # short_change是负数

    @property
    def total_volume(self) -> int:
        """总持仓量（绝对值）"""
        return abs(self.long_volume) + abs(self.short_volume)

    @property
    def net_volume(self) -> int:
        """净持仓（多-空）"""
        return self.long_volume - self.short_volume
```

**6.3 昨仓管理**

```python
# backtrader/position/yesterday.py
from dataclasses import dataclass

@dataclass
class YesterdayPosition:
    """昨仓"""

    symbol: str
    long_volume: int = 0
    short_volume: int = 0
    long_settle_price: float = 0  # 昨结算价
    short_settle_price: float = 0

    @property
    def total_volume(self) -> int:
        """总持仓量"""
        return abs(self.long_volume) + abs(self.short_volume)

    @property
    def net_volume(self) -> int:
        """净持仓"""
        return self.long_volume - self.short_volume
```

#### 7. 数据持久化

**7.1 记录器**

```python
# backtrader/persistence/recorder.py
from datetime import datetime
from pathlib import Path
from typing import Dict, List
import csv

class TradeRecorder:
    """交易记录器"""

    def __init__(self, output_dir: str = "./records"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.date_str = datetime.now().strftime("%Y%m%d")

    def record_order(self, order: Dict):
        """记录订单"""
        filename = self.output_dir / f"orders_{self.date_str}.csv"
        fieldnames = ['datetime', 'symbol', 'direction', 'volume', 'price', 'status']

        self._append_to_csv(filename, fieldnames, {
            'datetime': order.get('datetime', datetime.now()).isoformat(),
            'symbol': order.get('symbol'),
            'direction': order.get('direction'),
            'volume': order.get('volume'),
            'price': order.get('price'),
            'status': order.get('status'),
        })

    def record_trade(self, trade: Dict):
        """记录成交"""
        filename = self.output_dir / f"trades_{self.date_str}.csv"
        fieldnames = ['datetime', 'symbol', 'direction', 'volume', 'price', 'commission']

        self._append_to_csv(filename, fieldnames, {
            'datetime': trade.get('datetime', datetime.now()).isoformat(),
            'symbol': trade.get('symbol'),
            'direction': trade.get('direction'),
            'volume': trade.get('volume'),
            'price': trade.get('price'),
            'commission': trade.get('commission', 0),
        })

    def record_position(self, position: Dict):
        """记录持仓"""
        filename = self.output_dir / f"positions_{self.date_str}.csv"
        fieldnames = ['datetime', 'symbol', 'long_volume', 'short_volume', 'cost', 'profit']

        self._append_to_csv(filename, fieldnames, {
            'datetime': datetime.now().isoformat(),
            'symbol': position.get('symbol'),
            'long_volume': position.get('long_volume', 0),
            'short_volume': position.get('short_volume', 0),
            'cost': position.get('cost', 0),
            'profit': position.get('profit', 0),
        })

    def record_account(self, account: Dict):
        """记录账户"""
        filename = self.output_dir / f"account_{self.date_str}.csv"
        fieldnames = ['datetime', 'cash', 'value', 'margin', 'available']

        self._append_to_csv(filename, fieldnames, {
            'datetime': datetime.now().isoformat(),
            'cash': account.get('cash', 0),
            'value': account.get('value', 0),
            'margin': account.get('margin', 0),
            'available': account.get('available', 0),
        })

    def _append_to_csv(self, filename: Path, fieldnames: List[str], row: Dict):
        """追加到CSV"""
        file_exists = filename.exists()

        with open(filename, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
```

**7.2 导出器**

```python
# backtrader/persistence/exporter.py
from datetime import datetime
from pathlib import Path
from typing import Dict
import json

class ResultExporter:
    """结果导出器"""

    def __init__(self, output_dir: str = "./results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_backtest(self, result: Dict, name: str = None):
        """导出回测结果"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self.output_dir / f"backtest_{name or timestamp}.json"

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return filename

    def export_forward_test(self, result: Dict, comparison: Dict = None):
        """导出前向测试结果"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self.output_dir / f"forward_{timestamp}.json"

        export_data = {
            'timestamp': timestamp,
            'result': result,
            'comparison': comparison,
        }

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        return filename

    def export_comparison_report(self, comparison: Dict, name: str = None):
        """导出对比报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self.output_dir / f"comparison_{name or timestamp}.txt"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(self._format_report(comparison))

        return filename

    def _format_report(self, comparison: Dict) -> str:
        """格式化报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("前向测试对比报告")
        lines.append("=" * 60)

        if 'summary' in comparison:
            s = comparison['summary']
            lines.append(f"\n收益率对比:")
            lines.append(f"  回测: {s.get('backtest_return', 0):.2%}")
            lines.append(f"  前向: {s.get('forward_return', 0):.2%}")
            lines.append(f"  差异: {s.get('return_delta', 0):.2%}")

        if 'decay' in comparison:
            d = comparison['decay']
            lines.append(f"\n性能衰减:")
            lines.append(f"  收益率衰减: {d.get('return_decay', 0):.2%}")
            lines.append(f"  夏普衰减: {d.get('sharpe_decay', 0):.2f}")

        lines.append("\n" + "=" * 60)

        return "\n".join(lines)
```

### 实现计划

#### 第一阶段：前向测试框架（优先级：高）
1. 实现PhaseManager阶段管理器
2. 实现ForwardTestEngine前向测试引擎
3. 实现ForwardConfig配置类
4. 集成到Cerebro引擎

#### 第二阶段：过拟合检测（优先级：高）
1. 实现OverfittingDetector检测器
2. 实现ResultComparator对比器
3. 实现DecayMetrics和StabilityMetrics
4. 生成对比报告

#### 第三阶段：智能重连（优先级：高）
1. 实现ConnectionManager连接管理器
2. 实现ReconnectStrategy重连策略
3. 实现ConnectionState状态管理
4. 集成异常检测

#### 第四阶段：Tick数据处理（优先级：中）
1. 实现TickData数据源
2. 实现TickAggregator聚合器
3. 实现MultiLevelQuote多档行情
4. 支持多周期聚合

#### 第五阶段：交易时间管理（优先级：中）
1. 实现TradingCalendar交易日历
2. 实现TradingSchedule时段管理
3. 实现TimeFilter时间过滤器
4. 支持多品种配置

#### 第六阶段：今昨仓管理（优先级：中）
1. 实现PositionManager持仓管理器
2. 实现TodayPosition今仓管理
3. 实现YesterdayPosition昨仓管理
4. 支持平仓优先级配置

#### 第七阶段：数据持久化（优先级：中）
1. 实现TradeRecorder记录器
2. 实现ResultExporter导出器
3. 支持CSV和JSON格式
4. 自动文件管理

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
from backtrader.forward import ForwardTestEngine

engine = ForwardTestEngine()
engine.add_strategy(MyStrategy)
engine.add_data(data)
result = engine.run()

# 获取对比报告
comparison = engine.get_comparison()
print(comparison.generate_report())
```

### 使用示例

**前向测试使用示例：**

```python
from backtrader.forward import ForwardTestEngine, ForwardConfig, DataConfig, StrategyConfig
from backtrader.overfitting import OverfittingDetector

# 创建配置
config = ForwardConfig(
    data_configs=[
        DataConfig(
            symbol="rb2305",
            from_datetime=datetime(2023, 1, 1, 9, 0),
            history_length=10000
        )
    ],
    strategy_configs=[
        StrategyConfig(cls=MyStrategy, params={'period': 20})
    ],
    switch_time=datetime(2023, 2, 1, 9, 0),
    cash=100000,
    output_dir="./forward_results"
)

# 创建引擎
engine = ForwardTestEngine(config)

# 运行前向测试
results = engine.run()

# 过拟合检测
detector = OverfittingDetector()
detection = detector.detect(results['history'], results['forward'])
print(f"过拟合检测结果: {detection['verdict']}")
```

**Tick数据处理示例：**

```python
from backtrader.tick import TickData, TickAggregator

# 创建Tick数据源
tick_feed = TickData(
    aggregator=TickAggregator(period=60),
    aggregate_period=60
)

cerebro = bt.Cerebro()
cerebro.adddata(tick_feed)

# 策略中访问多档行情
class MyStrategy(bt.Strategy):
    def next(self):
        # 访问多档行情
        if hasattr(self.data, 'bid1'):
            spread = self.data.ask1[0] - self.data.bid1[0]
            if spread < self.p.max_spread:
                self.buy()
```

**连接管理使用示例：**

```python
from backtrader.connection import ConnectionManager

manager = ConnectionManager()

# 注册事件
manager.on('connected', lambda: print("Connected!"))
manager.on('reconnected', lambda: print("Reconnected!"))
manager.on('disconnected', lambda: print("Disconnected!"))

# 建立连接
manager.connect(lambda: api.connect())

# 检查连接
if not manager.check_connection():
    manager.reconnect(lambda: api.connect())

# 每日重置
manager.reset_daily(reset_time=time(21, 20))
```

### 测试策略

1. **单元测试**: 每个新增模块的单元测试覆盖率 > 80%
2. **集成测试**: 与现有功能的集成测试
3. **前向测试测试**: 模拟实盘环境测试
4. **性能测试**: Tick数据处理延迟 < 10ms
5. **兼容性测试**: 确保现有代码无需修改即可运行
