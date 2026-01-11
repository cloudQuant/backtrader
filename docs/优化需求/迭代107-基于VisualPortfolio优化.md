### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/VisualPortfolio
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### VisualPortfolio项目简介
VisualPortfolio是一个投资组合可视化分析工具，具有以下核心特点：
- **组合可视化**: 投资组合可视化
- **风险分析**: 风险指标可视化
- **收益分析**: 收益归因分析
- **资产配置**: 资产配置展示
- **交互图表**: 交互式图表
- **报表生成**: 可视化报表生成

### 重点借鉴方向
1. **可视化**: 投资组合可视化
2. **风险图表**: 风险指标图表
3. **收益归因**: 收益归因可视化
4. **资产配置**: 配置可视化
5. **交互设计**: 交互式图表
6. **报表设计**: 报表设计方法

---

# Backtrader优化需求文档 - 基于VisualPortfolio

## 1. 项目对比分析

### 1.1 架构对比

| 特性 | Backtrader (当前) | VisualPortfolio |
|------|-------------------|-----------------|
| 分析输出 | 控制台文本/简单图表 | 丰富的可视化图表 |
| 风险分析 | 基础指标 | 完整风险分析体系 |
| 回撤分析 | 数值 | 水下图+回撤期间高亮 |
| 收益分析 | 年化收益 | 月度热力图+年度柱状图 |
| 滚动指标 | 无 | 滚动Beta/Sharpe |
| 交易成本 | 不支持 | 支持交易成本建模 |
| 持仓分析 | 基础 | 完整持仓分析 |
| 换手率 | 无 | 换手率分析 |

### 1.2 VisualPortfolio核心优势

#### 1.2.1 Tear Sheet模式
```python
# 完整的分析报告
createPerformanceTearSheet(prices, benchmark='000300.zicn')
# 自动生成:
# - 性能指标表
# - 累计收益曲线
# - 回撤分析图
# - 滚动风险指标
# - 月度收益热力图
# - 年度收益柱状图
# - 收益分布直方图
```

#### 1.2.2 交易成本建模
```python
# 考虑交易成本的影响
aggregateReturns(returns, turn_over, tc_cost=0.001)
# 输出:
# - 扣除成本后的收益
# - 扣除成本前的收益
# - 成本影响对比
```

#### 1.2.3 回撤详细分析
```python
# 回撤分析
drawDown(returns)
# 返回:
# - draw_down: 回撤幅度
# - peak: 高点时间
# - valley: 低点时间
# - recovery: 恢复时间
```

#### 1.2.4 滚动风险指标
```python
# 滚动Beta和Sharpe
RollingBeta(returns, benchmarkReturns, [1, 3, 6], factor)
RollingSharp(returns, [1, 3, 6], factor)
# 多窗口滚动指标:
# - 1个月、3个月、6个月
```

#### 1.2.5 持仓分析
```python
# 持仓分析
createPostionTearSheet(positions)
# 生成:
# - 多空敞口图
# - Top 10持仓图
# - 持仓数量分析
# - 持仓自相关分析
```

---

## 2. 需求文档

### 2.1 功能需求

#### FR1: Tear Sheet报告系统
**描述**: 创建全面的组合性能分析报告

**需求详情**:
1. 性能指标汇总表
2. 累计收益曲线
3. 回撤期间分析
4. 月度收益热力图
5. 年度收益柱状图
6. 收益分布图
7. 滚动风险指标

**验收标准**:
- [ ] 一键生成完整报告
- [ ] 支持PNG/PDF导出
- [ ] 报告生成时间<5秒

#### FR2: 回撤分析增强
**描述**: 详细的回撤分析可视化

**需求详情**:
1. 水下图(Underwater Plot)
2. 最大回撤期间标记
3. 回撤恢复时间分析
4. 回撤统计表

**验收标准**:
- [ ] 支持Top N回撤期间标记
- [ ] 显示回撤恢复时长
- [ ] 回撤区间高亮显示

#### FR3: 滚动风险指标
**描述**: 动态滚动窗口风险指标计算

**需求详情**:
1. 滚动Sharpe比率
2. 滚动Sortino比率
3. 滚动Beta
4. 滚动Alpha
5. 可配置窗口期

**验收标准**:
- [ ] 支持1/3/6/12月窗口
- [ ] 滚动计算高效
- [ ] 图表清晰展示

#### FR4: 交易成本建模
**描述**: 交易成本对策略的影响分析

**需求详情**:
1. 成本参数配置
2. 扣除成本前后的收益对比
3. 换手率分析
4. 成本敏感性分析

**验收标准**:
- [ ] 支持固定/比例成本
- [ ] 成本对比可视化
- [ ] 换手率计算准确

#### FR5: 持仓分析系统
**描述**: 完整的持仓组合分析

**需求详情**:
1. 多空敞口分析
2. Top N持仓分析
3. 持仓数量统计
4. 持仓换手率
5. 持仓相关性分析

**验收标准**:
- [ ] 支持日/周/月频率
- [ ] 敞口计算准确
- [ ] 持仓权重归一化

#### FR6: 基准对比分析
**描述**: 与基准指数的对比分析

**需求详情**:
1. 超额收益计算
2. 相对回撤分析
3. Beta暴露分析
4. 信息比率计算

**验收标准**:
- [ ] 支持自定义基准
- [ ] 超额收益准确
- [ ] 相对分析图表清晰

### 2.2 非功能需求

#### NFR1: 性能
- 大数据量处理(10年日频数据<2秒)
- 图表渲染流畅
- 内存使用优化

#### NFR2: 可扩展性
- 模块化设计
- 自定义图表支持
- 插件式指标系统

#### NFR3: 易用性
- 一键生成报告
- 合理的默认参数
- 清晰的图表标注

#### NFR4: 兼容性
- 与现有Analyzer兼容
- 支持多种数据格式
- 导出多种格式

---

## 3. 设计文档

### 3.1 架构设计

#### 3.1.1 模块结构

```
backtrader/
├── analysis/                     # 分析模块
│   ├── __init__.py
│   ├── tearsheet.py             # Tear Sheet报告
│   ├── performance.py            # 性能指标计算
│   ├── drawdown.py               # 回撤分析
│   ├── rolling.py                # 滚动指标
│   ├── position.py               # 持仓分析
│   ├── transaction.py            # 交易分析
│   └── benchmark.py              # 基准对比
│
├── visualization/                # 可视化模块
│   ├── __init__.py
│   ├── context.py                # 绘图上下文
│   ├── plots.py                  # 基础绘图函数
│   ├── charts/                   # 图表类
│   │   ├── __init__.py
│   │   ├── return_chart.py       # 收益图表
│   │   ├── drawdown_chart.py     # 回撤图表
│   │   ├── rolling_chart.py      # 滚动指标图表
│   │   └── heatmap.py            # 热力图
│   └── themes/                   # 图表主题
│       ├── __init__.py
│       └── default.py
│
└── utils/                        # 工具模块
    ├── __init__.py
    ├── math.py                   # 数学工具
    ├── stats.py                  # 统计工具
    └── format.py                 # 格式化工具
```

### 3.2 类设计

#### 3.2.1 Tear Sheet报告

```python
# backtrader/analysis/tearsheet.py

"""
Tear Sheet报告生成模块

生成全面的策略性能分析报告,包括:
- 性能指标汇总
- 收益分析图表
- 回撤分析图表
- 风险指标图表
"""

import backtrader as bt
from backtrader.analyzers import returns, drawdown, sharpe, tradeanalyzer
from backtrader.analysis.performance import PerformanceCalculator
from backtrader.visualization import plotting_context, PlotManager
from backtrader.utils.stats import group_returns


class TearSheet:
    """Tear Sheet报告生成器

    生成全面的策略性能分析报告

    示例:
        >>> ts = TearSheet(cerebro)
        >>> ts.create_full_report()
    """

    def __init__(self, cerebro=None, strategy=None):
        """初始化Tear Sheet

        Args:
            cerebro: Cerebro实例
            strategy: 策略实例(可选)
        """
        self.cerebro = cerebro
        self.strategy = strategy

        # 数据存储
        self.returns = None
        self.benchmark_returns = None
        self.equity = None
        self.positions = None
        self.trades = None

        # 计算器
        self.perf_calc = PerformanceCalculator()

        # 绘图管理器
        self.plot_mgr = PlotManager()

    def create_full_report(self, benchmark=None, tc_cost=0.0, figsize=(16, 14)):
        """创建完整的Tear Sheet报告

        Args:
            benchmark: 基准指数代码或数据
            tc_cost: 交易成本
            figsize: 图表大小

        Returns:
            Figure对象
        """
        # 提取数据
        self._extract_data()

        # 计算性能指标
        metrics = self._calculate_metrics()

        # 创建图表
        return self._create_report_figure(metrics, benchmark, tc_cost, figsize)

    def create_performance_tearsheet(self, benchmark=None, tc_cost=0.0, figsize=(16, 10)):
        """创建性能分析部分

        包含:
        - 累计收益曲线
        - 回撤分析
        - 月度收益热力图
        - 年度收益柱状图
        """
        return self._create_performance_figure(benchmark, tc_cost, figsize)

    def create_risk_tearsheet(self, benchmark=None, figsize=(16, 10)):
        """创建风险分析部分

        包含:
        - 滚动Sharpe比率
        - 滚动Beta
        - 滚动波动率
        """
        return self._create_risk_figure(benchmark, figsize)

    def create_position_tearsheet(self, freq='M', figsize=(16, 10)):
        """创建持仓分析部分

        包含:
        - 多空敞口
        - Top持仓
        - 持仓数量
        - 持仓换手率
        """
        return self._create_position_figure(freq, figsize)

    def _extract_data(self):
        """从Cerebro提取数据"""
        if self.cerebro is None:
            return

        # 获取净值曲线
        self.equity = self._get_equity_curve()

        # 计算收益率
        if self.equity is not None:
            self.returns = self.perf_calc.calculate_returns(self.equity)

        # 获取持仓数据
        self.positions = self._get_positions()

        # 获取交易数据
        self.trades = self._get_trades()

    def _get_equity_curve(self):
        """获取净值曲线"""
        if not self.cerebro:
            return None

        # 从策略中提取净值历史
        # 这里需要配合策略的记录功能
        equity_values = []
        dates = []

        strategy = self.strategy or self.cerebro.strats[0]

        if hasattr(strategy, 'equity_curve'):
            return strategy.equity_curve

        # 从broker获取
        for i in range(len(strategy.datas[0])):
            strategy.next()
            equity_values.append(self.cerebro.broker.getvalue())
            dates.append(strategy.datas[0].datetime.datetime(0))

        import pandas as pd
        return pd.Series(equity_values, index=dates)

    def _get_positions(self):
        """获取持仓数据"""
        if not self.cerebro:
            return None

        positions = {}
        strategy = self.strategy or self.cerebro.strats[0]

        for i, data in enumerate(strategy.datas):
            pos = strategy.getposition(data)
            if pos.size != 0:
                positions[data._name] = pos.size

        return positions

    def _get_trades(self):
        """获取交易记录"""
        if not self.cerebro:
            return None

        # 从tradeanalyzer获取
        strategy = self.strategy or self.cerebro.strats[0]
        if hasattr(strategy, 'analyzers'):
            trade_analyzer = strategy.analyzers.byname('tradeanalyzer')
            if trade_analyzer:
                return trade_analyzer.get_analysis()

        return None

    def _calculate_metrics(self):
        """计算性能指标"""
        import pandas as pd

        metrics = {}

        if self.returns is None or len(self.returns) == 0:
            return metrics

        # 基础指标
        metrics['total_return'] = self.perf_calc.total_return(self.returns)
        metrics['annual_return'] = self.perf_calc.annual_return(self.returns)
        metrics['annual_volatility'] = self.perf_calc.annual_volatility(self.returns)
        metrics['sharpe_ratio'] = self.perf_calc.sharpe_ratio(self.returns)
        metrics['sortino_ratio'] = self.perf_calc.sortino_ratio(self.returns)
        metrics['max_drawdown'] = self.perf_calc.max_drawdown(self.returns)
        metrics['calmar_ratio'] = self.perf_calc.calmar_ratio(self.returns)

        # 交易统计
        if self.trades:
            metrics['total_trades'] = self.trades.get('total', {}).get('total', 0)
            metrics['winning_trades'] = self.trades.get('won', {}).get('total', 0)
            metrics['losing_trades'] = self.trades.get('lost', {}).get('total', 0)
            metrics['win_rate'] = (metrics['winning_trades'] / metrics['total_trades']
                                  if metrics['total_trades'] > 0 else 0)

        return metrics

    def _create_report_figure(self, metrics, benchmark, tc_cost, figsize):
        """创建完整报告图表"""
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec

        fig = plt.figure(figsize=figsize)
        gs = gridspec.GridSpec(3, 3, hspace=0.3, wspace=0.3)

        # 第一行: 累计收益和回撤
        ax_returns = plt.subplot(gs[0, :])
        ax_drawdown = plt.subplot(gs[1, :])

        self.plot_mgr.plot_cumulative_returns(
            self.returns,
            self.benchmark_returns,
            ax=ax_returns
        )

        self.plot_mgr.plot_drawdown(
            self.returns,
            ax=ax_drawdown
        )

        # 第二行: 性能指标
        ax_metrics = plt.subplot(gs[2, 0])
        self._plot_metrics_table(metrics, ax_metrics)

        # 月度热力图
        ax_heatmap = plt.subplot(gs[2, 1])
        self.plot_mgr.plot_monthly_heatmap(self.returns, ax=ax_heatmap)

        # 年度收益
        ax_annual = plt.subplot(gs[2, 2])
        self.plot_mgr.plot_annual_returns(self.returns, ax=ax_annual)

        return fig

    def _create_performance_figure(self, benchmark, tc_cost, figsize):
        """创建性能分析图表"""
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec

        fig = plt.figure(figsize=figsize)
        gs = gridspec.GridSpec(2, 3, hspace=0.3, wspace=0.3)

        # 累计收益
        ax_returns = plt.subplot(gs[0, :])
        self.plot_mgr.plot_cumulative_returns(
            self.returns,
            self.benchmark_returns,
            ax=ax_returns
        )

        # 回撤分析
        ax_drawdown = plt.subplot(gs[1, 0])
        ax_underwater = plt.subplot(gs[1, 1])
        ax_heatmap = plt.subplot(gs[1, 2])

        self.plot_mgr.plot_drawdown_periods(self.returns, ax=ax_drawdown)
        self.plot_mgr.plot_underwater(self.returns, ax=ax_underwater)
        self.plot_mgr.plot_monthly_heatmap(self.returns, ax=ax_heatmap)

        return fig

    def _create_risk_figure(self, benchmark, figsize):
        """创建风险分析图表"""
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec

        fig = plt.figure(figsize=figsize)
        gs = gridspec.GridSpec(2, 1, hspace=0.3)

        # 滚动Sharpe
        ax_sharpe = plt.subplot(gs[0, :])
        self.plot_mgr.plot_rolling_sharpe(self.returns, ax=ax_sharpe)

        # 滚动Beta
        if self.benchmark_returns is not None:
            ax_beta = plt.subplot(gs[1, :])
            self.plot_mgr.plot_rolling_beta(
                self.returns,
                self.benchmark_returns,
                ax=ax_beta
            )

        return fig

    def _create_position_figure(self, freq, figsize):
        """创建持仓分析图表"""
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec

        fig = plt.figure(figsize=figsize)
        gs = gridspec.GridSpec(2, 2, hspace=0.3, wspace=0.3)

        # 多空敞口
        ax_exposure = plt.subplot(gs[0, :])
        self.plot_mgr.plot_exposure(self.positions, ax=ax_exposure)

        # Top持仓
        ax_top = plt.subplot(gs[1, 0])
        self.plot_mgr.plot_top_positions(self.positions, ax=ax_top)

        # 持仓数量
        ax_count = plt.subplot(gs[1, 1])
        self.plot_mgr.plot_position_count(self.positions, freq, ax=ax_count)

        return fig

    def _plot_metrics_table(self, metrics, ax):
        """绘制指标表格"""
        import pandas as pd

        # 格式化指标
        formatted_metrics = {}
        for key, value in metrics.items():
            if 'return' in key or 'ratio' in key:
                formatted_metrics[key] = f"{value:.4f}"
            elif 'volatility' in key or 'drawdown' in key:
                formatted_metrics[key] = f"{value:.2%}"
            else:
                formatted_metrics[key] = f"{value}"

        # 创建表格
        df = pd.DataFrame.from_dict(formatted_metrics, orient='index', columns=['Value'])
        df.columns.name = 'Metric'

        ax.axis('off')
        table = ax.table(
            cellText=df.values,
            rowLabels=df.index,
            colLabels=df.columns,
            loc='center',
            cellLoc='right'
        )
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 2)

        ax.set_title('Performance Metrics', pad=20)


class TearSheetParams:
    """Tear Sheet参数配置

    可配置的参数:
    - figsize: 图表大小
    - dpi: 分辨率
    - style: 图表风格
    - colors: 颜色配置
    - top_drawdowns: 显示的回撤期间数量
    - rolling_windows: 滚动窗口列表
    """

    params = (
        ('figsize', (16, 12)),
        ('dpi', 100),
        ('style', 'seaborn-v0_8-darkgrid'),
        ('top_drawdowns', 5),
        ('rolling_windows', [1, 3, 6, 12]),
        ('color_scheme', 'default'),
        ('show_benchmark', True),
        ('fill_alpha', 0.3),
        ('linewidth', 2),
    )
```

#### 3.2.2 性能计算器

```python
# backtrader/analysis/performance.py

"""
性能指标计算模块

提供全面的策略性能指标计算
"""

import numpy as np
import pandas as pd
from typing import Optional, Union, Tuple
from enum import Enum


class Period(Enum):
    """时间周期枚举"""
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'
    YEARLY = 'yearly'


class PerformanceCalculator:
    """性能指标计算器

    提供全面的性能指标计算功能:
    - 收益率指标
    - 风险指标
    - 风险调整收益指标
    - 回撤指标
    """

    # 交易日常数
    APPROX_BDAYS_PER_MONTH = 21
    APPROX_BDAYS_PER_YEAR = 252

    def __init__(self, risk_free_rate: float = 0.0):
        """初始化计算器

        Args:
            risk_free_rate: 无风险利率(年化)
        """
        self.risk_free_rate = risk_free_rate

    def calculate_returns(self, prices: pd.Series) -> pd.Series:
        """计算收益率序列

        Args:
            prices: 价格序列

        Returns:
            收益率序列
        """
        returns = np.log(prices / prices.shift(1))
        returns = returns.fillna(0)
        returns = returns.replace([np.inf, -np.inf], 0)
        return returns

    def total_return(self, returns: pd.Series) -> float:
        """计算总收益率

        Args:
            returns: 收益率序列

        Returns:
            总收益率
        """
        if len(returns) == 0:
            return 0.0
        return np.exp(returns.sum()) - 1.0

    def annual_return(self, returns: pd.Series) -> float:
        """计算年化收益率

        Args:
            returns: 收益率序列

        Returns:
            年化收益率
        """
        if len(returns) == 0:
            return 0.0
        return returns.mean() * self.APPROX_BDAYS_PER_YEAR

    def annual_volatility(self, returns: pd.Series) -> float:
        """计算年化波动率

        Args:
            returns: 收益率序列

        Returns:
            年化波动率
        """
        if len(returns) < 2:
            return 0.0
        return returns.std() * np.sqrt(self.APPROX_BDAYS_PER_YEAR)

    def sharpe_ratio(self, returns: pd.Series) -> float:
        """计算Sharpe比率

        Args:
            returns: 收益率序列

        Returns:
            Sharpe比率
        """
        annual_ret = self.annual_return(returns)
        annual_vol = self.annual_volatility(returns)

        if annual_vol == 0:
            return np.nan

        excess_return = annual_ret - self.risk_free_rate
        return excess_return / annual_vol

    def sortino_ratio(self, returns: pd.Series) -> float:
        """计算Sortino比率

        Args:
            returns: 收益率序列

        Returns:
            Sortino比率
        """
        annual_ret = self.annual_return(returns)
        downside_returns = returns[returns < 0]
        annual_downside_vol = self.annual_volatility(downside_returns)

        if annual_downside_vol == 0:
            return np.nan

        excess_return = annual_ret - self.risk_free_rate
        return excess_return / annual_downside_vol

    def calmar_ratio(self, returns: pd.Series) -> float:
        """计算Calmar比率

        Args:
            returns: 收益率序列

        Returns:
            Calmar比率
        """
        annual_ret = self.annual_return(returns)
        max_dd = abs(self.max_drawdown(returns))

        if max_dd == 0:
            return np.nan

        return annual_ret / max_dd

    def max_drawdown(self, returns: pd.Series) -> float:
        """计算最大回撤

        Args:
            returns: 收益率序列

        Returns:
            最大回撤(负数)
        """
        if len(returns) == 0:
            return 0.0

        cumulative = np.exp(returns.cumsum())
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max
        return drawdown.min()

    def omega_ratio(self, returns: pd.Series, threshold: float = 0.0) -> float:
        """计算Omega比率

        Args:
            returns: 收益率序列
            threshold: 目标阈值

        Returns:
            Omega比率
        """
        gains = returns[returns > threshold] - threshold
        losses = threshold - returns[returns <= threshold]

        if losses.sum() == 0:
            return np.nan

        return gains.sum() / losses.sum()

    def win_rate(self, returns: pd.Series) -> float:
        """计算胜率

        Args:
            returns: 收益率序列

        Returns:
            胜率
        """
        if len(returns) == 0:
            return 0.0
        return (returns > 0).sum() / len(returns)

    def profit_loss_ratio(self, returns: pd.Series) -> float:
        """计算盈亏比

        Args:
            returns: 收益率序列

        Returns:
            盈亏比
        """
        gains = returns[returns > 0]
        losses = returns[returns < 0]

        if losses.sum() == 0 or len(gains) == 0:
            return np.nan

        avg_gain = gains.mean()
        avg_loss = abs(losses.mean())

        return avg_gain / avg_loss if avg_loss != 0 else np.nan

    def value_at_risk(self, returns: pd.Series, level: float = 0.05) -> float:
        """计算VaR (Value at Risk)

        Args:
            returns: 收益率序列
            level: 显著性水平

        Returns:
            VaR值
        """
        return np.percentile(returns, level * 100)

    def conditional_var(self, returns: pd.Series, level: float = 0.05) -> float:
        """计算CVaR (Conditional Value at Risk)

        Args:
            returns: 收益率序列
            level: 显著性水平

        Returns:
            CVaR值
        """
        var = self.value_at_risk(returns, level)
        return returns[returns <= var].mean()

    def aggregate_returns(self,
                         returns: pd.Series,
                         period: Period = Period.MONTHLY,
                         convert: str = 'returns') -> pd.Series:
        """聚合收益率

        Args:
            returns: 日收益率序列
            period: 聚合周期
            convert: 转换方式 ('returns' 或 'cumsum')

        Returns:
            聚合后的收益率
        """
        if period == Period.DAILY:
            group = returns.groupby([returns.index.year, returns.index.month, returns.index.day])
        elif period == Period.WEEKLY:
            group = returns.groupby([returns.index.year, returns.index.isocalendar().week])
        elif period == Period.MONTHLY:
            group = returns.groupby([returns.index.year, returns.index.month])
        elif period == Period.YEARLY:
            group = returns.groupby(returns.index.year)
        else:
            raise ValueError(f"Unknown period: {period}")

        if convert == 'returns':
            return group.sum()
        elif convert == 'cumsum':
            return group.sum().cumsum()
        else:
            raise ValueError(f"Unknown convert: {convert}")

    def monthly_returns(self, returns: pd.Series) -> pd.DataFrame:
        """计算月度收益率矩阵

        Args:
            returns: 日收益率序列

        Returns:
            月度收益率DataFrame (年份 x 月份)
        """
        monthly = self.aggregate_returns(returns, Period.MONTHLY)
        df = monthly.unstack()
        df.columns = df.columns.droplevel(0)
        return df

    def annual_returns(self, returns: pd.Series) -> pd.Series:
        """计算年度收益率

        Args:
            returns: 日收益率序列

        Returns:
            年度收益率序列
        """
        return self.aggregate_returns(returns, Period.YEARLY)
```

#### 3.2.3 回撤分析器

```python
# backtrader/analysis/drawdown.py

"""
回撤分析模块

提供详细的回撤分析和可视化
"""

import numpy as np
import pandas as pd
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass


@dataclass
class DrawdownPeriod:
    """回撤期间数据类"""
    start: pd.Timestamp           # 回撤开始时间
    peak: pd.Timestamp            # 最高点时间
    valley: pd.Timestamp          # 最低点时间
    end: Optional[pd.Timestamp]   # 恢复时间
    drawdown: float               # 回撤幅度
    recovery_days: int            # 恢复天数
    peak_val: float               # 最高点值
    valley_val: float             # 最低点值


class DrawdownAnalyzer:
    """回撤分析器

    提供详细的回撤分析功能:
    - 最大回撤计算
    - 回撤期间识别
    - 回撤统计
    """

    def __init__(self, returns: Optional[pd.Series] = None):
        """初始化回撤分析器

        Args:
            returns: 收益率序列
        """
        self.returns = returns
        self.cum_returns = None
        self.drawdowns = None

        if returns is not None:
            self._calculate()

    def calculate(self, returns: pd.Series):
        """计算回撤

        Args:
            returns: 收益率序列
        """
        self.returns = returns
        self._calculate()

    def _calculate(self):
        """执行计算"""
        if self.returns is None:
            return

        # 计算累计收益
        self.cum_returns = np.exp(self.returns.cumsum())

        # 计算回撤序列
        running_max = self.cum_returns.cummax()
        self.drawdowns = (self.cum_returns - running_max) / running_max

    def max_drawdown(self) -> float:
        """获取最大回撤

        Returns:
            最大回撤(负数)
        """
        if self.drawdowns is None:
            return 0.0
        return self.drawdowns.min()

    def max_drawdown_period(self) -> Optional[DrawdownPeriod]:
        """获取最大回撤期间

        Returns:
            最大回撤期间数据
        """
        periods = self.get_drawdown_periods()
        if not periods:
            return None
        return max(periods, key=lambda x: abs(x.drawdown))

    def get_drawdown_periods(self, top: int = None) -> List[DrawdownPeriod]:
        """获取回撤期间列表

        Args:
            top: 返回前N个回撤期间

        Returns:
            回撤期间列表
        """
        if self.drawdowns is None:
            return []

        periods = []
        in_drawdown = False
        start_idx = None
        peak_idx = None

        for i in range(len(self.drawdowns)):
            dd = self.drawdowns.iloc[i]

            if not in_drawdown and dd < 0:
                # 进入回撤
                in_drawdown = True
                start_idx = i
                peak_idx = self._find_peak_before(i)

            elif in_drawdown and dd >= 0:
                # 回撤结束
                in_drawdown = False
                valley_idx = self._find_valley_between(start_idx, i)
                end_idx = i

                period = DrawdownPeriod(
                    start=self.cum_returns.index[start_idx],
                    peak=self.cum_returns.index[peak_idx],
                    valley=self.cum_returns.index[valley_idx],
                    end=self.cum_returns.index[end_idx],
                    drawdown=self.drawdowns.iloc[valley_idx],
                    recovery_days=(end_idx - peak_idx),
                    peak_val=self.cum_returns.iloc[peak_idx],
                    valley_val=self.cum_returns.iloc[valley_idx]
                )
                periods.append(period)

        # 处理最后一个回撤
        if in_drawdown:
            valley_idx = self._find_valley_between(start_idx, len(self.drawdowns))
            period = DrawdownPeriod(
                start=self.cum_returns.index[start_idx],
                peak=self.cum_returns.index[peak_idx],
                valley=self.cum_returns.index[valley_idx],
                end=None,  # 未恢复
                drawdown=self.drawdowns.iloc[valley_idx],
                recovery_days=None,
                peak_val=self.cum_returns.iloc[peak_idx],
                valley_val=self.cum_returns.iloc[valley_idx]
            )
            periods.append(period)

        # 按回撤幅度排序
        periods.sort(key=lambda x: abs(x.drawdown), reverse=True)

        if top is not None:
            return periods[:top]
        return periods

    def _find_peak_before(self, idx: int) -> int:
        """查找指定位置之前的峰值索引"""
        peak_val = -np.inf
        peak_idx = idx

        for i in range(idx, -1, -1):
            if self.cum_returns.iloc[i] > peak_val:
                peak_val = self.cum_returns.iloc[i]
                peak_idx = i

        return peak_idx

    def _find_valley_between(self, start: int, end: int) -> int:
        """查找两个位置之间的谷值索引"""
        valley_val = 0.0
        valley_idx = start

        for i in range(start, min(end, len(self.cum_returns))):
            dd = self.drawdowns.iloc[i]
            if dd < valley_val:
                valley_val = dd
                valley_idx = i

        return valley_idx

    def get_drawdown_series(self) -> pd.Series:
        """获取回撤序列

        Returns:
            回撤序列
        """
        return self.drawdowns

    def average_drawdown(self) -> float:
        """计算平均回撤

        Returns:
            平均回撤
        """
        periods = self.get_drawdown_periods()
        if not periods:
            return 0.0
        return np.mean([abs(p.drawdown) for p in periods])

    def recovery_time_stats(self) -> Dict[str, float]:
        """计算恢复时间统计

        Returns:
            恢复时间统计字典
        """
        periods = self.get_drawdown_periods()
        completed = [p for p in periods if p.recovery_days is not None]

        if not completed:
            return {
                'avg_recovery_days': 0,
                'max_recovery_days': 0,
                'min_recovery_days': 0
            }

        recovery_days = [p.recovery_days for p in completed]

        return {
            'avg_recovery_days': np.mean(recovery_days),
            'max_recovery_days': np.max(recovery_days),
            'min_recovery_days': np.min(recovery_days)
        }
```

#### 3.2.4 滚动指标计算器

```python
# backtrader/analysis/rolling.py

"""
滚动指标计算模块

提供滚动窗口的风险调整收益指标计算
"""

import numpy as np
import pandas as pd
from typing import List, Union, Optional
from enum import Enum


class RollingMetric:
    """滚动指标基类"""

    def __init__(self, window: int, min_periods: Optional[int] = None):
        """初始化滚动指标

        Args:
            window: 窗口大小
            min_periods: 最小观测值数量
        """
        self.window = window
        self.min_periods = min_periods or window

    def calculate(self, data: pd.Series) -> pd.Series:
        """计算滚动指标

        Args:
            data: 数据序列

        Returns:
            指标序列
        """
        raise NotImplementedError


class RollingSharp(RollingMetric):
    """滚动Sharpe比率计算器

    Args:
        window: 窗口大小(交易日)
        min_periods: 最小观测值数量
        risk_free_rate: 无风险利率(年化)
    """

    def __init__(self,
                 window: int,
                 min_periods: Optional[int] = None,
                 risk_free_rate: float = 0.0):
        super().__init__(window, min_periods)
        self.risk_free_rate = risk_free_rate
        self.APPROX_BDAYS_PER_YEAR = 252

    def calculate(self, returns: pd.Series) -> pd.Series:
        """计算滚动Sharpe比率

        Args:
            returns: 收益率序列

        Returns:
            滚动Sharpe比率序列
        """
        rolling_mean = returns.rolling(
            window=self.window,
            min_periods=self.min_periods
        ).mean()

        rolling_std = returns.rolling(
            window=self.window,
            min_periods=self.min_periods
        ).std()

        # 年化
        annual_mean = rolling_mean * self.APPROX_BDAYS_PER_YEAR
        annual_std = rolling_std * np.sqrt(self.APPROX_BDAYS_PER_YEAR)

        sharpe = (annual_mean - self.risk_free_rate) / annual_std
        return sharpe


class RollingSortino(RollingMetric):
    """滚动Sortino比率计算器"""

    def __init__(self,
                 window: int,
                 min_periods: Optional[int] = None,
                 risk_free_rate: float = 0.0):
        super().__init__(window, min_periods)
        self.risk_free_rate = risk_free_rate
        self.APPROX_BDAYS_PER_YEAR = 252

    def calculate(self, returns: pd.Series) -> pd.Series:
        """计算滚动Sortino比率

        Args:
            returns: 收益率序列

        Returns:
            滚动Sortino比率序列
        """
        def downside_std(series):
            """计算下行标准差"""
            downside = series[series < 0]
            if len(downside) == 0:
                return np.nan
            return downside.std()

        rolling_mean = returns.rolling(
            window=self.window,
            min_periods=self.min_periods
        ).mean()

        rolling_downside_std = returns.rolling(
            window=self.window,
            min_periods=self.min_periods
        ).apply(downside_std)

        # 年化
        annual_mean = rolling_mean * self.APPROX_BDAYS_PER_YEAR
        annual_downside_std = rolling_downside_std * np.sqrt(self.APPROX_BDAYS_PER_YEAR)

        sortino = (annual_mean - self.risk_free_rate) / annual_downside_std
        return sortino


class RollingBeta(RollingMetric):
    """滚动Beta计算器

    Args:
        window: 窗口大小(交易日)
        min_periods: 最小观测值数量
    """

    def __init__(self, window: int, min_periods: Optional[int] = None):
        super().__init__(window, min_periods)

    def calculate(self,
                  returns: pd.Series,
                  benchmark_returns: pd.Series) -> pd.Series:
        """计算滚动Beta

        Args:
            returns: 策略收益率序列
            benchmark_returns: 基准收益率序列

        Returns:
            滚动Beta序列
        """
        # 对齐数据
        aligned_returns, aligned_benchmark = returns.align(benchmark_returns, join='inner')

        # 计算协方差和方差
        cov = aligned_returns.rolling(
            window=self.window,
            min_periods=self.min_periods
        ).cov(aligned_benchmark)

        var = aligned_benchmark.rolling(
            window=self.window,
            min_periods=self.min_periods
        ).var()

        beta = cov / var
        return beta


class RollingAlpha(RollingMetric):
    """滚动Alpha计算器"""

    def __init__(self,
                 window: int,
                 min_periods: Optional[int] = None,
                 risk_free_rate: float = 0.0):
        super().__init__(window, min_periods)
        self.risk_free_rate = risk_free_rate
        self.APPROX_BDAYS_PER_YEAR = 252

    def calculate(self,
                  returns: pd.Series,
                  benchmark_returns: pd.Series) -> pd.Series:
        """计算滚动Alpha

        Args:
            returns: 策略收益率序列
            benchmark_returns: 基准收益率序列

        Returns:
            滚动Alpha序列
        """
        # Alpha = Rp - (Rf + Beta * (Rm - Rf))
        rolling_beta_calc = RollingBeta(self.window, self.min_periods)
        beta = rolling_beta_calc.calculate(returns, benchmark_returns)

        annual_return = returns.rolling(
            window=self.window,
            min_periods=self.min_periods
        ).mean() * self.APPROX_BDAYS_PER_YEAR

        annual_benchmark_return = benchmark_returns.rolling(
            window=self.window,
            min_periods=self.min_periods
        ).mean() * self.APPROX_BDAYS_PER_YEAR

        alpha = annual_return - (self.risk_free_rate + beta * (annual_benchmark_return - self.risk_free_rate))
        return alpha


class RollingVolatility(RollingMetric):
    """滚动波动率计算器"""

    def __init__(self, window: int, min_periods: Optional[int] = None):
        super().__init__(window, min_periods)
        self.APPROX_BDAYS_PER_YEAR = 252

    def calculate(self, returns: pd.Series) -> pd.Series:
        """计算滚动波动率

        Args:
            returns: 收益率序列

        Returns:
            滚动年化波动率序列
        """
        rolling_std = returns.rolling(
            window=self.window,
            min_periods=self.min_periods
        ).std()

        annual_vol = rolling_std * np.sqrt(self.APPROX_BDAYS_PER_YEAR)
        return annual_vol


def calculate_rolling_metrics(returns: pd.Series,
                               windows: List[int] = [21, 63, 126, 252],
                               benchmark_returns: Optional[pd.Series] = None,
                               risk_free_rate: float = 0.0) -> pd.DataFrame:
    """计算多个滚动指标

    Args:
        returns: 收益率序列
        windows: 窗口大小列表
        benchmark_returns: 基准收益率序列
        risk_free_rate: 无风险利率

    Returns:
        滚动指标DataFrame
    """
    results = {}

    for window in windows:
        # Sharpe比率
        sharp_calc = RollingSharp(window, risk_free_rate=risk_free_rate)
        results[f'sharpe_{window}d'] = sharp_calc.calculate(returns)

        # Sortino比率
        sortino_calc = RollingSortino(window, risk_free_rate=risk_free_rate)
        results[f'sortino_{window}d'] = sortino_calc.calculate(returns)

        # 波动率
        vol_calc = RollingVolatility(window)
        results[f'volatility_{window}d'] = vol_calc.calculate(returns)

        # Beta和Alpha (需要基准)
        if benchmark_returns is not None:
            beta_calc = RollingBeta(window)
            results[f'beta_{window}d'] = beta_calc.calculate(returns, benchmark_returns)

            alpha_calc = RollingAlpha(window, risk_free_rate=risk_free_rate)
            results[f'alpha_{window}d'] = alpha_calc.calculate(returns, benchmark_returns)

    return pd.DataFrame(results)
```

#### 3.2.5 可视化管理器

```python
# backtrader/visualization/plots.py

"""
绘图模块

提供全面的策略可视化功能
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sns
from matplotlib.ticker import FuncFormatter
from matplotlib.patches import Rectangle
from typing import Optional, List, Dict, Tuple
from functools import wraps


# === 绘图上下文管理 ===

def plotting_context(func):
    """绘图上下文装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        set_context = kwargs.pop('set_context', True)
        if set_context:
            with _default_context():
                return func(*args, **kwargs)
        else:
            return func(*args, **kwargs)
    return wrapper


def _default_context(context='notebook', font_scale=1.2, rc=None):
    """创建默认绘图上下文"""
    if rc is None:
        rc = {}

    rc_default = {
        'lines.linewidth': 1.5,
        'axes.facecolor': '0.995',
        'figure.facecolor': '0.97',
        'font.family': ['DejaVu Sans'],
        'axes.labelsize': 10,
        'axes.titlesize': 12,
        'legend.fontsize': 9,
    }

    for name, val in rc_default.items():
        rc.setdefault(name, val)

    return sns.plotting_context(context=context, font_scale=font_scale, rc=rc)


class PlotManager:
    """绘图管理器

    统一管理所有绘图功能
    """

    # 颜色方案
    COLORS = {
        'strategy': '#2E8B57',      # SeaGreen
        'strategy_w_tc': '#DC143C',  # Crimson
        'benchmark': '#808080',      # Gray
        'positive': '#26A69A',       # Teal
        'negative': '#EF5350',       # Red
        'sharpe_1m': '#4682B4',      # SteelBlue
        'sharpe_3m': '#9E9E9E',      # Gray
        'sharpe_6m': '#FFC107',      # Amber
        'drawdown': '#FFA07A',       # LightSalmon
    }

    def __init__(self, figsize=(16, 10), dpi=100):
        """初始化绘图管理器

        Args:
            figsize: 默认图表大小
            dpi: 分辨率
        """
        self.figsize = figsize
        self.dpi = dpi

    @plotting_context
    def plot_cumulative_returns(self,
                                  returns: pd.Series,
                                  benchmark_returns: Optional[pd.Series] = None,
                                  returns_wo_tc: Optional[pd.Series] = None,
                                  title: str = 'Cumulative Returns',
                                  ax: Optional[plt.Axes] = None) -> plt.Axes:
        """绘制累计收益曲线

        Args:
            returns: 收益率序列
            benchmark_returns: 基准收益率序列
            returns_wo_tc: 不含交易成本的收益率序列
            title: 图表标题
            ax: Axes对象

        Returns:
            Axes对象
        """
        if ax is None:
            _, ax = plt.subplots(figsize=self.figsize)

        # 计算累计收益
        cum_returns = np.exp(returns.cumsum()) - 1

        # 绘制策略收益
        cum_returns.plot(
            ax=ax,
            lw=2.5,
            color=self.COLORS['strategy'],
            alpha=0.8,
            label='Strategy'
        )

        # 绘制不含成本的收益
        if returns_wo_tc is not None:
            cum_returns_wo_tc = np.exp(returns_wo_tc.cumsum()) - 1
            cum_returns_wo_tc.plot(
                ax=ax,
                lw=2.5,
                color=self.COLORS['strategy_w_tc'],
                alpha=0.8,
                label='Strategy (w/o TC)',
                linestyle='--'
            )

        # 绘制基准收益
        if benchmark_returns is not None:
            cum_benchmark = np.exp(benchmark_returns.cumsum()) - 1
            cum_benchmark.plot(
                ax=ax,
                lw=2,
                color=self.COLORS['benchmark'],
                alpha=0.6,
                label='Benchmark'
            )

        # 零线
        ax.axhline(0.0, color='black', linestyle='-', lw=1)

        # 格式化Y轴
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{x:.2%}'))

        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_ylabel('Cumulative Returns')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)

        return ax

    @plotting_context
    def plot_drawdown_periods(self,
                               returns: pd.Series,
                               top: int = 5,
                               title: str = 'Top Drawdown Periods',
                               ax: Optional[plt.Axes] = None) -> plt.Axes:
        """绘制回撤期间

        Args:
            returns: 收益率序列
            top: 显示的回撤期间数量
            title: 图表标题
            ax: Axes对象

        Returns:
            Axes对象
        """
        from backtrader.analysis.drawdown import DrawdownAnalyzer

        if ax is None:
            _, ax = plt.subplots(figsize=self.figsize)

        # 计算累计收益
        cum_returns = np.exp(returns.cumsum()) - 1

        # 绘制累计收益
        cum_returns.plot(ax=ax, color='steelblue', lw=2, label='Cumulative Returns')

        # 获取回撤期间
        dd_analyzer = DrawdownAnalyzer(returns)
        periods = dd_analyzer.get_drawdown_periods(top=top)

        # 绘制回撤区域
        colors = sns.cubehelix_palette(top, start=0.3, rot=-0.5)[::-1]
        lim = ax.get_ylim()

        for i, period in enumerate(periods):
            if period.end is not None:
                ax.fill_between(
                    [period.peak, period.end],
                    lim[0],
                    lim[1],
                    alpha=0.3,
                    color=colors[i],
                    label=f'DD {abs(period.drawdown):.1%}'
                )

        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{x:.2%}'))
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_ylabel('Cumulative Returns')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)

        return ax

    @plotting_context
    def plot_underwater(self,
                        returns: pd.Series,
                        title: str = 'Underwater Plot',
                        ax: Optional[plt.Axes] = None) -> plt.Axes:
        """绘制水下图

        Args:
            returns: 收益率序列
            title: 图表标题
            ax: Axes对象

        Returns:
            Axes对象
        """
        from backtrader.analysis.drawdown import DrawdownAnalyzer

        if ax is None:
            _, ax = plt.subplots(figsize=self.figsize)

        # 计算回撤序列
        dd_analyzer = DrawdownAnalyzer(returns)
        drawdown_series = dd_analyzer.get_drawdown_series()

        # 绘制水下图
        ax.fill_between(
            drawdown_series.index,
            drawdown_series.values,
            0,
            color=self.COLORS['drawdown'],
            alpha=0.7
        )

        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{x:.1%}'))
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_ylabel('Drawdown')
        ax.grid(True, alpha=0.3)

        return ax

    @plotting_context
    def plot_monthly_heatmap(self,
                              returns: pd.Series,
                              title: str = 'Monthly Returns (%)',
                              ax: Optional[plt.Axes] = None) -> plt.Axes:
        """绘制月度收益热力图

        Args:
            returns: 收益率序列
            title: 图表标题
            ax: Axes对象

        Returns:
            Axes对象
        """
        from backtrader.analysis.performance import PerformanceCalculator

        if ax is None:
            _, ax = plt.subplots(figsize=(12, 8))

        # 计算月度收益
        perf_calc = PerformanceCalculator()
        monthly_df = perf_calc.monthly_returns(returns)

        # 转换为百分比
        monthly_pct = (np.exp(monthly_df) - 1) * 100

        # 绘制热力图
        sns.heatmap(
            monthly_pct,
            annot=True,
            fmt='.1f',
            annot_kws={'size': 8},
            cmap='RdYlGn_r',
            center=0.0,
            cbar_kws={'label': 'Returns (%)'},
            ax=ax
        )

        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_ylabel('Year')
        ax.set_xlabel('Month')

        return ax

    @plotting_context
    def plot_annual_returns(self,
                            returns: pd.Series,
                            title: str = 'Annual Returns',
                            ax: Optional[plt.Axes] = None) -> plt.Axes:
        """绘制年度收益柱状图

        Args:
            returns: 收益率序列
            title: 图表标题
            ax: Axes对象

        Returns:
            Axes对象
        """
        from backtrader.analysis.performance import PerformanceCalculator

        if ax is None:
            _, ax = plt.subplots(figsize=(10, 6))

        # 计算年度收益
        perf_calc = PerformanceCalculator()
        annual_returns = perf_calc.annual_returns(returns)
        annual_pct = (np.exp(annual_returns) - 1) * 100

        # 按年份排序
        annual_pct = annual_pct.sort_index(ascending=False)

        # 绘制柱状图
        colors = [self.COLORS['positive'] if v >= 0 else self.COLORS['negative']
                  for v in annual_pct.values]

        annual_pct.plot(
            kind='barh',
            ax=ax,
            color=colors,
            alpha=0.7,
            edgecolor='black',
            linewidth=0.5
        )

        # 平均线
        mean_return = annual_pct.mean()
        ax.axvline(mean_return, color='steelblue', linestyle='--', lw=2, alpha=0.7, label='Mean')

        ax.axvline(0, color='black', linestyle='-', lw=1)

        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{x:.0f}%'))
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_xlabel('Annual Returns (%)')
        ax.set_ylabel('Year')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3, axis='x')

        return ax

    @plotting_context
    def plot_rolling_sharpe(self,
                            returns: pd.Series,
                            windows: List[int] = [21, 63, 126],
                            title: str = 'Rolling Sharpe Ratio',
                            ax: Optional[plt.Axes] = None) -> plt.Axes:
        """绘制滚动Sharpe比率

        Args:
            returns: 收益率序列
            windows: 窗口大小列表
            title: 图表标题
            ax: Axes对象

        Returns:
            Axes对象
        """
        from backtrader.analysis.rolling import RollingSharp

        if ax is None:
            _, ax = plt.subplots(figsize=self.figsize)

        colors = [self.COLORS['sharpe_1m'], self.COLORS['sharpe_3m'], self.COLORS['sharpe_6m']]

        for i, window in enumerate(windows):
            sharp_calc = RollingSharp(window)
            sharp_series = sharp_calc.calculate(returns)

            sharp_series.plot(
                ax=ax,
                lw=2 if i == 0 else 1.5,
                color=colors[i % len(colors)],
                alpha=0.8 if i == 0 else 0.5,
                label=f'{window}D'
            )

            # 平均线
            if i == 0:
                mean_sharp = sharp_series.mean()
                ax.axhline(mean_sharp, color=colors[0], linestyle='--', lw=2, alpha=0.6)

        ax.axhline(0, color='black', linestyle='-', lw=1)

        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_ylabel('Sharpe Ratio')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)

        return ax

    @plotting_context
    def plot_rolling_beta(self,
                          returns: pd.Series,
                          benchmark_returns: pd.Series,
                          windows: List[int] = [21, 63, 126],
                          title: str = 'Rolling Beta',
                          ax: Optional[plt.Axes] = None) -> plt.Axes:
        """绘制滚动Beta

        Args:
            returns: 收益率序列
            benchmark_returns: 基准收益率序列
            windows: 窗口大小列表
            title: 图表标题
            ax: Axes对象

        Returns:
            Axes对象
        """
        from backtrader.analysis.rolling import RollingBeta

        if ax is None:
            _, ax = plt.subplots(figsize=self.figsize)

        for i, window in enumerate(windows):
            beta_calc = RollingBeta(window)
            beta_series = beta_calc.calculate(returns, benchmark_returns)

            beta_series.plot(
                ax=ax,
                lw=2 if i == 0 else 1.5,
                color=colors[i % len(colors)],
                alpha=0.8 if i == 0 else 0.5,
                label=f'{window}D'
            )

            # 平均线
            if i == 0:
                mean_beta = beta_series.mean()
                ax.axhline(mean_beta, color=colors[0], linestyle='--', lw=2, alpha=0.6)

        ax.axhline(1.0, color='black', linestyle=':', lw=1, alpha=0.5)

        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_ylabel('Beta')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)

        return ax

    @plotting_context
    def plot_exposure(self,
                      positions: pd.DataFrame,
                      title: str = 'Portfolio Exposure (%)',
                      ax: Optional[plt.Axes] = None) -> plt.Axes:
        """绘制持仓敞口

        Args:
            positions: 持仓DataFrame
            title: 图表标题
            ax: Axes对象

        Returns:
            Axes对象
        """
        if ax is None:
            _, ax = plt.subplots(figsize=self.figsize)

        # 计算多空敞口
        if 'cash' in positions.columns:
            positions_wo_cash = positions.drop('cash', axis=1)
        else:
            positions_wo_cash = positions

        longs = positions_wo_cash[positions_wo_cash > 0].sum(axis=1).fillna(0) * 100
        shorts = positions_wo_cash[positions_wo_cash < 0].abs().sum(axis=1).fillna(0) * 100

        # 绘制堆叠面积图
        df_exposure = pd.DataFrame({'long': longs, 'short': shorts})
        df_exposure.plot(
            kind='area',
            stacked=True,
            color=['blue', 'red'],
            alpha=0.5,
            linewidth=0,
            ax=ax
        )

        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_ylabel('Exposure (%)')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)

        return ax

    @plotting_context
    def plot_monthly_return_dist(self,
                                 returns: pd.Series,
                                 title: str = 'Monthly Return Distribution',
                                 ax: Optional[plt.Axes] = None) -> plt.Axes:
        """绘制月度收益分布

        Args:
            returns: 收益率序列
            title: 图表标题
            ax: Axes对象

        Returns:
            Axes对象
        """
        from backtrader.analysis.performance import PerformanceCalculator

        if ax is None:
            _, ax = plt.subplots(figsize=(10, 6))

        # 计算月度收益
        perf_calc = PerformanceCalculator()
        monthly_returns = perf_calc.aggregate_returns(returns, Period.MONTHLY)
        monthly_pct = (np.exp(monthly_returns) - 1) * 100

        # 绘制直方图
        ax.hist(
            monthly_pct,
            bins=20,
            color='steelblue',
            alpha=0.7,
            edgecolor='black',
            linewidth=0.5
        )

        # 平均线
        mean_return = monthly_pct.mean()
        ax.axvline(mean_return, color='red', linestyle='--', lw=2, label=f'Mean: {mean_return:.1f}%')

        ax.axvline(0, color='black', linestyle='-', lw=1)

        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{x:.0f}%'))
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_xlabel('Monthly Return (%)')
        ax.set_ylabel('Frequency')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3, axis='y')

        return ax

    def create_full_report(self,
                          returns: pd.Series,
                          benchmark_returns: Optional[pd.Series] = None,
                          save_path: Optional[str] = None) -> plt.Figure:
        """创建完整报告

        Args:
            returns: 收益率序列
            benchmark_returns: 基准收益率序列
            save_path: 保存路径

        Returns:
            Figure对象
        """
        fig = plt.figure(figsize=(16, 12))
        gs = gridspec.GridSpec(3, 3, hspace=0.3, wspace=0.3)

        # 第一行: 累计收益和回撤
        ax_returns = fig.add_subplot(gs[0, :])
        ax_drawdown = fig.add_subplot(gs[1, :])

        self.plot_cumulative_returns(returns, benchmark_returns, ax=ax_returns)
        self.plot_drawdown_periods(returns, ax=ax_drawdown)

        # 第二行: 各种分析图
        ax_underwater = fig.add_subplot(gs[2, 0])
        ax_heatmap = fig.add_subplot(gs[2, 1])
        ax_annual = fig.add_subplot(gs[2, 2])

        self.plot_underwater(returns, ax=ax_underwater)
        self.plot_monthly_heatmap(returns, ax=ax_heatmap)
        self.plot_annual_returns(returns, ax=ax_annual)

        if save_path:
            fig.savefig(save_path, dpi=self.dpi, bbox_inches='tight')

        return fig
```

### 3.3 使用示例

```python
# 基础用法
import backtrader as bt
from backtrader.analysis import TearSheet

# 创建策略
cerebro = bt.Cerebro()
cerebro.addstrategy(MyStrategy)
cerebro.adddata(data)

# 运行回测
results = cerebro.run()

# 创建Tear Sheet
ts = TearSheet(cerebro)
ts.create_full_report()
plt.show()

# 高级用法: 自定义分析
from backtrader.analysis.performance import PerformanceCalculator
from backtrader.analysis.drawdown import DrawdownAnalyzer
from backtrader.analysis.rolling import calculate_rolling_metrics

# 计算性能指标
perf_calc = PerformanceCalculator()
returns = perf_calc.calculate_returns(prices)

print(f"总收益率: {perf_calc.total_return(returns):.2%}")
print(f"年化收益: {perf_calc.annual_return(returns):.2%}")
print(f"夏普比率: {perf_calc.sharpe_ratio(returns):.2f}")
print(f"最大回撤: {perf_calc.max_drawdown(returns):.2%}")

# 回撤分析
dd_analyzer = DrawdownAnalyzer(returns)
periods = dd_analyzer.get_drawdown_periods(top=5)

for i, period in enumerate(periods, 1):
    print(f"回撤{i}: {period.peak} -> {period.valley}, "
          f"幅度: {period.drawdown:.2%}, 恢复: {period.recovery_days}天")

# 滚动指标
rolling_metrics = calculate_rolling_metrics(
    returns,
    windows=[21, 63, 126],
    benchmark_returns=benchmark_returns
)

# 绘制滚动Sharpe
fig, axes = plt.subplots(2, 1, figsize=(14, 10))

rolling_metrics['sharpe_21d'].plot(ax=axes[0], label='21-Day Sharpe')
rolling_metrics['sharpe_63d'].plot(ax=axes[0], label='63-Day Sharpe')
rolling_metrics['sharpe_126d'].plot(ax=axes[0], label='126-Day Sharpe')
axes[0].set_title('Rolling Sharpe Ratio')
axes[0].legend()
axes[0].grid(True)

rolling_metrics['beta_21d'].plot(ax=axes[1], label='21-Day Beta')
rolling_metrics['beta_63d'].plot(ax=axes[1], label='63-Day Beta')
rolling_metrics['beta_126d'].plot(ax=axes[1], label='126-Day Beta')
axes[1].set_title('Rolling Beta')
axes[1].legend()
axes[1].grid(True)

plt.tight_layout()
plt.show()
```

### 3.4 实施计划

#### 阶段1: 核心计算模块 (优先级: 高)
1. PerformanceCalculator实现
2. DrawdownAnalyzer实现
3. 滚动指标计算器
4. 单元测试

#### 阶段2: 可视化模块 (优先级: 高)
1. PlotManager实现
2. 各类图表绘制函数
3. 主题和样式配置
4. 导出功能

#### 阶段3: Tear Sheet集成 (优先级: 高)
1. TearSheet主类实现
2. 报告模板
3. 参数配置系统
4. 文档和示例

#### 阶段4: 高级功能 (优先级: 中)
1. 交易成本建模
2. 持仓分析
3. 换手率分析
4. 基准对比

#### 阶段5: 优化完善 (优先级: 低)
1. 性能优化
2. 更多图表类型
3. 交互式图表(Plotly)
4. Web界面集成

---

## 4. 测试策略

### 4.1 单元测试
- 性能指标计算准确性
- 回撤分析正确性
- 滚动指标计算

### 4.2 集成测试
- 完整报告生成
- 与backtrader集成

### 4.3 对比测试
- 与VisualPortfolio结果对比
- 与pyfolio结果对比

---

## 5. 总结

通过借鉴VisualPortfolio的设计，backtrader可以实现:

1. **专业的Tear Sheet报告**: 一键生成全面的性能分析报告
2. **详细的回撤分析**: 水下图和回撤期间高亮
3. **滚动风险指标**: 动态的风险调整收益指标
4. **交易成本建模**: 真实的成本影响分析
5. **持仓分析**: 完整的持仓组合分析
6. **丰富的可视化**: 专业级金融图表

这将大大提升backtrader的分析和展示能力,使其更适合专业的量化交易分析场景。

