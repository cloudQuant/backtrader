### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/Time_Series_Backtesting
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### Time_Series_Backtesting项目简介
Time_Series_Backtesting是一个时间序列回测框架，具有以下核心特点：
- **时间序列**: 专注于时间序列分析
- **交叉验证**: 时间序列交叉验证
- **Walk-forward**: Walk-forward分析
- **过拟合检测**: 过拟合检测方法
- **统计检验**: 统计显著性检验
- **稳健性测试**: 策略稳健性测试

### 重点借鉴方向
1. **时序验证**: 时间序列验证方法
2. **交叉验证**: 时序交叉验证
3. **Walk-forward**: Walk-forward分析
4. **过拟合检测**: 过拟合检测
5. **稳健性**: 稳健性测试方法
6. **统计检验**: 统计显著性检验

---

## 项目对比分析

### Backtrader vs Time_Series_Backtesting

| 维度 | Backtrader | Time_Series_Backtesting |
|------|-----------|-------------------------|
| **核心定位** | 通用回测框架 | 时间序列分析专用框架 |
| **交叉验证** | 无内置支持 | 固定窗口回测 |
| **Walk-forward** | 无 | 无（但框架设计支持） |
| **过拟合检测** | 基础 | 蒙特卡洛模拟 |
| **统计检验** | 无 | Bootstrap检验 |
| **稳健性测试** | 基础 | 多资产/多频率测试 |
| **前瞻偏差预防** | 用户自行处理 | 严格数据分离 |
| **参数敏感性** | 无 | 参数敏感性分析 |
| **多频率支持** | 支持 | 1分钟-8小时全支持 |

### Backtrader可借鉴的优势

1. **时间序列交叉验证**：K-fold时序交叉验证、滚动窗口验证
2. **Walk-forward分析**：动态参数优化、滚动回测
3. **过拟合检测体系**：White's Reality Check、PCS检验
4. **统计显著性检验**：Bootstrap、Permutation Test
5. **稳健性测试框架**：市场环境切换、交易成本敏感性
6. **前瞻偏差预防**：数据分片器、严格数据管道
7. **参数敏感性分析**：热力图、扰动分析

---

## 功能需求文档

### FR-01 时间序列交叉验证器 [高优先级]

**描述**: 实现专门针对时间序列的交叉验证方法

**需求**:
- FR-01.1 K-fold时序交叉验证
- FR-01.2 滚动窗口交叉验证
- FR-01.3 扩展窗口交叉验证
- FR-01.4 自定义分割策略
- FR-01.5 分割结果可视化

**验收标准**:
- 支持3种以上时序交叉验证方法
- 确保无数据泄露
- 支持多资产并行验证

### FR-02 Walk-forward分析引擎 [高优先级]

**描述**: 实现Walk-forward滚动分析功能

**需求**:
- FR-02.1 滚动优化窗口
- FR-02.2 滚动测试窗口
- FR-02.3 动态参数再优化
- FR-02.4 Walk-forward绩效统计
- FR-02.5 参数稳定性分析

**验收标准**:
- 支持自定义窗口大小和步长
- 每期参数独立优化
- 生成完整Walk-forward报告

### FR-03 过拟合检测系统 [高优先级]

**描述**: 建立完整的过拟合检测体系

**需求**:
- FR-03.1 White's Reality Check
- FR-03.2 依赖调整的PCS检验
- FR-03.3 蒙特卡洛模拟
- FR-03.4 参数敏感性分析
- FR-03.5 训练/测试性能对比

**验收标准**:
- 支持3种以上过拟合检测方法
- 输出p值和置信区间
- 可视化过拟合风险

### FR-04 统计显著性检验 [中优先级]

**描述**: 实现策略绩效的统计检验

**需求**:
- FR-04.1 Bootstrap置信区间
- FR-04.2 Permutation Test
- FR-04.3 多重比较修正（Bonferroni/BH）
- FR-04.4 Sharpe比率显著性检验
- FR-04.5 收益率分布检验

**验收标准**:
- 支持5种以上统计检验方法
- 输出95%置信区间
- FDR控制

### FR-05 稳健性测试框架 [中优先级]

**描述**: 测试策略在不同条件下的稳健性

**需求**:
- FR-05.1 牛熊市切换测试
- FR-05.2 交易成本敏感性
- FR-05.3 滑点敏感性
- FR-05.4 数据频率敏感性
- FR-05.5 参数扰动测试

**验收标准**:
- 支持5种以上稳健性测试
- 生成稳健性评分
- 可视化稳健性结果

### FR-06 前瞻偏差预防器 [高优先级]

**描述**: 防止回测中的前瞻偏差

**需求**:
- FR-06.1 严格数据分片器
- FR-06.2 信号延迟模拟
- FR-06.3 未来信息检测
- FR-06.4 数据泄露检测
- FR-06.5 时间戳验证

**验收标准**:
- 自动检测潜在前瞻偏差
- 阻止使用未来数据
- 生成偏差报告

### FR-07 参数优化器 [中优先级]

**描述**: 智能参数优化工具

**需求**:
- FR-07.1 网格搜索
- FR-07.2 贝叶斯优化
- FR-07.3 遗传算法
- FR-07.4 参数重要性分析
- FR-07.5 过拟合防护机制

**验收标准**:
- 支持3种以上优化算法
- 自动检测过拟合
- 生成参数报告

### FR-08 绩效分析增强 [中优先级]

**描述**: 增强绩效分析功能

**需求**:
- FR-08.1 月度/年度绩效分解
- FR-08.2 滚动绩效指标
- FR-08.3 相对基准分析
- FR-08.4 尾部风险分析
- FR-08.5 增量收益分析

**验收标准**:
- 支持15+项绩效指标
- 滚动窗口计算
- 多基准对比

---

## 设计文档

### 1. 时间序列交叉验证器设计

```python
from typing import List, Tuple, Callable, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import pandas as pd
import numpy as np
import backtrader as bt

@dataclass
class TimeSeriesSplit:
    """时间序列分割结果"""
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_indices: slice
    test_indices: slice

class TimeSeriesCV:
    """时间序列交叉验证器"""

    def __init__(self,
                 method: str = 'rolling',
                 n_splits: int = 5,
                 train_size: Optional[float] = None,
                 test_size: Optional[float] = None,
                 gap: int = 0):
        """
        Args:
            method: 分割方法 ('rolling', 'expanding', 'kfold')
            n_splits: 分割数量
            train_size: 训练集大小（比例或绝对值）
            test_size: 测试集大小（比例或绝对值）
            gap: 训练集和测试集之间的间隔
        """
        self.method = method
        self.n_splits = n_splits
        self.train_size = train_size
        self.test_size = test_size
        self.gap = gap

    def split(self, data: pd.DataFrame) -> List[TimeSeriesSplit]:
        """
        生成时间序列分割

        Args:
            data: 包含datetime索引的数据

        Returns:
            分割结果列表
        """
        n_samples = len(data)

        if self.method == 'rolling':
            return self._rolling_split(n_samples, data.index)
        elif self.method == 'expanding':
            return self._expanding_split(n_samples, data.index)
        elif self.method == 'kfold':
            return self._kfold_split(n_samples, data.index)
        else:
            raise ValueError(f"Unknown method: {self.method}")

    def _rolling_split(self, n_samples: int,
                      index: pd.DatetimeIndex) -> List[TimeSeriesSplit]:
        """滚动窗口分割"""
        splits = []

        # 计算窗口大小
        if self.train_size is None:
            train_size = n_samples // (self.n_splits + 1)
        else:
            train_size = int(self.train_size if self.train_size > 1
                            else self.train_size * n_samples)

        if self.test_size is None:
            test_size = train_size
        else:
            test_size = int(self.test_size if self.test_size > 1
                           else self.test_size * n_samples)

        # 计算步长
        step = max(1, (n_samples - train_size - test_size) // self.n_splits)

        for i in range(self.n_splits):
            train_start = i * step
            train_end = train_start + train_size
            test_start = train_end + self.gap
            test_end = test_start + test_size

            if test_end > n_samples:
                break

            splits.append(TimeSeriesSplit(
                train_start=index[train_start],
                train_end=index[train_end - 1],
                test_start=index[test_start],
                test_end=index[test_end - 1],
                train_indices=slice(train_start, train_end),
                test_indices=slice(test_start, test_end)
            ))

        return splits

    def _expanding_split(self, n_samples: int,
                         index: pd.DatetimeIndex) -> List[TimeSeriesSplit]:
        """扩展窗口分割"""
        splits = []

        if self.test_size is None:
            test_size = n_samples // (self.n_splits + 1)
        else:
            test_size = int(self.test_size if self.test_size > 1
                           else self.test_size * n_samples)

        train_end = n_samples // (self.n_splits + 1)

        for i in range(self.n_splits):
            test_start = train_end + self.gap
            test_end = test_start + test_size

            if test_end > n_samples:
                test_end = n_samples

            splits.append(TimeSeriesSplit(
                train_start=index[0],
                train_end=index[train_end - 1],
                test_start=index[test_start],
                test_end=index[test_end - 1],
                train_indices=slice(0, train_end),
                test_indices=slice(test_start, test_end)
            ))

            # 扩展训练集
            train_end = test_end

        return splits

    def _kfold_split(self, n_samples: int,
                     index: pd.DatetimeIndex) -> List[TimeSeriesSplit]:
        """K-fold时序分割"""
        splits = []

        fold_size = n_samples // (self.n_splits + 1)

        for i in range(1, self.n_splits + 1):
            train_end = i * fold_size
            test_end = (i + 1) * fold_size if i < self.n_splits else n_samples

            splits.append(TimeSeriesSplit(
                train_start=index[0],
                train_end=index[train_end - 1],
                test_start=index[train_end],
                test_end=index[test_end - 1],
                train_indices=slice(0, train_end),
                test_indices=slice(train_end, test_end)
            ))

        return splits

    def visualize_splits(self, data: pd.DataFrame, save_path: str = None):
        """可视化分割结果"""
        import matplotlib.pyplot as plt

        splits = self.split(data)
        fig, ax = plt.subplots(figsize=(12, len(splits) * 0.5))

        for i, split in enumerate(splits):
            # 训练集
            train_data = data.iloc[split.train_indices]
            ax.barh(i, len(train_data), left=0,
                   height=0.8, color='blue', alpha=0.3, label='Train' if i == 0 else '')

            # 测试集
            test_data = data.iloc[split.test_indices]
            ax.barh(i, len(test_data), left=split.test_indices.start,
                   height=0.8, color='red', alpha=0.3, label='Test' if i == 0 else '')

        ax.set_yticks(range(len(splits)))
        ax.set_yticklabels([f'Fold {i+1}' for i in range(len(splits))])
        ax.set_xlabel('Sample Index')
        ax.set_title('Time Series Cross-Validation Splits')
        ax.legend()

        plt.tight_layout()
        if save_path:
            plt.savefig(save_path)
        plt.show()
```

### 2. Walk-forward分析引擎设计

```python
from typing import Dict, List, Any, Callable, Optional
from dataclasses import dataclass
import pandas as pd
import numpy as np
from itertools import product
from concurrent.futures import ProcessPoolExecutor

@dataclass
class WalkForwardResult:
    """单次Walk-forward结果"""
    period: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    best_params: Dict[str, Any]
    train_metrics: Dict[str, float]
    test_metrics: Dict[str, float]

@dataclass
class WalkForwardSummary:
    """Walk-forward汇总结果"""
    results: List[WalkForwardResult]
    aggregate_metrics: Dict[str, float]
    param_stability: Dict[str, float]
    performance_consistency: Dict[str, float]

class WalkForwardAnalyzer:
    """Walk-forward分析引擎"""

    def __init__(self,
                 train_size: int = 252,
                 test_size: int = 63,
                 step_size: int = 21,
                 optimization_metric: str = 'sharpe'):
        """
        Args:
            train_size: 训练窗口大小（交易日）
            test_size: 测试窗口大小（交易日）
            step_size: 步长（交易日）
            optimization_metric: 优化目标指标
        """
        self.train_size = train_size
        self.test_size = test_size
        self.step_size = step_size
        self.optimization_metric = optimization_metric

    def run(self,
            data: pd.DataFrame,
            strategy_class: type,
            param_grid: Dict[str, List[Any]],
            **kwargs) -> WalkForwardSummary:
        """
        执行Walk-forward分析

        Args:
            data: 回测数据
            strategy_class: 策略类
            param_grid: 参数网格
            **kwargs: 其他回测参数

        Returns:
            Walk-forward汇总结果
        """
        results = []
        period = 0

        # 计算总窗口数
        total_length = len(data)
        max_start = total_length - self.train_size - self.test_size

        for train_start in range(0, max_start + 1, self.step_size):
            train_end = train_start + self.train_size
            test_start = train_end
            test_end = test_start + self.test_size

            if test_end > total_length:
                break

            period += 1

            # 分割数据
            train_data = data.iloc[train_start:train_end]
            test_data = data.iloc[test_start:test_end]

            # 参数优化
            best_params, train_metrics = self._optimize_parameters(
                train_data, strategy_class, param_grid, **kwargs
            )

            # 测试期验证
            test_metrics = self._test_period(
                test_data, strategy_class, best_params, **kwargs
            )

            results.append(WalkForwardResult(
                period=period,
                train_start=train_data.index[0],
                train_end=train_data.index[-1],
                test_start=test_data.index[0],
                test_end=test_data.index[-1],
                best_params=best_params,
                train_metrics=train_metrics,
                test_metrics=test_metrics
            ))

        # 计算汇总统计
        summary = self._compute_summary(results)

        return summary

    def _optimize_parameters(self,
                           train_data: pd.DataFrame,
                           strategy_class: type,
                           param_grid: Dict[str, List[Any]],
                           **kwargs) -> tuple:
        """优化参数"""
        # 生成参数组合
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        param_combinations = list(product(*param_values))

        best_score = -np.inf
        best_params = None
        best_metrics = None

        # 网格搜索
        for params in param_combinations:
            param_dict = dict(zip(param_names, params))

            try:
                # 运行回测
                metrics = self._run_backtest(
                    train_data, strategy_class, param_dict, **kwargs
                )

                # 获取优化目标
                score = metrics.get(self.optimization_metric, -np.inf)

                if score > best_score:
                    best_score = score
                    best_params = param_dict
                    best_metrics = metrics

            except Exception as e:
                continue

        return best_params or {}, best_metrics or {}

    def _test_period(self,
                   test_data: pd.DataFrame,
                   strategy_class: type,
                   params: Dict[str, Any],
                   **kwargs) -> Dict[str, float]:
        """在测试期验证"""
        metrics = self._run_backtest(
            test_data, strategy_class, params, **kwargs
        )
        return metrics

    def _run_backtest(self,
                     data: pd.DataFrame,
                     strategy_class: type,
                     params: Dict[str, Any],
                     **kwargs) -> Dict[str, float]:
        """运行单次回测"""
        cerebro = bt.Cerebro()

        # 添加策略
        cerebro.addstrategy(strategy_class, **params)

        # 添加数据
        data_feed = bt.feeds.PandasData(dataname=data)
        cerebro.adddata(data_feed)

        # 设置初始资金和手续费
        cerebro.broker.setcash(kwargs.get('cash', 100000))
        cerebro.broker.setcommission(kwargs.get('commission', 0.001))

        # 添加分析器
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

        # 运行
        results = cerebro.run()
        strat = results[0]

        # 提取指标
        sharpe = strat.analyzers.sharpe.get_analysis()
        drawdown = strat.analyzers.drawdown.get_analysis()
        returns = strat.analyzers.returns.get_analysis()
        trades = strat.analyzers.trades.get_analysis()

        return {
            'sharpe': sharpe.get('sharperatio', 0),
            'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
            'total_return': returns.get('rtot', 0),
            'annual_return': returns.get('rnorm', 0),
            'total_trades': trades.get('total', {}).get('total', 0)
        }

    def _compute_summary(self, results: List[WalkForwardResult]) -> WalkForwardSummary:
        """计算汇总统计"""
        # 提取测试期指标
        test_returns = [r.test_metrics.get('total_return', 0) for r in results]
        test_sharpe = [r.test_metrics.get('sharpe', 0) for r in results]
        test_dd = [r.test_metrics.get('max_drawdown', 0) for r in results]

        aggregate_metrics = {
            'mean_return': np.mean(test_returns),
            'std_return': np.std(test_returns),
            'mean_sharpe': np.mean(test_sharpe),
            'mean_drawdown': np.mean(test_dd),
            'win_rate': sum(r > 0 for r in test_returns) / len(test_returns)
        }

        # 参数稳定性分析
        param_stability = self._analyze_param_stability(results)

        # 性能一致性
        performance_consistency = {
            'return_consistency': np.std(test_returns) / (np.abs(np.mean(test_returns)) + 1e-6),
            'sharpe_consistency': np.std(test_sharpe) / (np.abs(np.mean(test_sharpe)) + 1e-6)
        }

        return WalkForwardSummary(
            results=results,
            aggregate_metrics=aggregate_metrics,
            param_stability=param_stability,
            performance_consistency=performance_consistency
        )

    def _analyze_param_stability(self,
                                 results: List[WalkForwardResult]) -> Dict[str, float]:
        """分析参数稳定性"""
        # 收集所有参数
        all_params = {}
        for result in results:
            for key, value in result.best_params.items():
                if key not in all_params:
                    all_params[key] = []
                all_params[key].append(value)

        # 计算变异系数
        stability = {}
        for key, values in all_params.items():
            if len(set(values)) > 1:
                # 参数变化的比例
                stability[key] = len(set(values)) / len(values)
            else:
                stability[key] = 0  # 完全稳定

        return stability
```

### 3. 过拟合检测系统设计

```python
from typing import List, Dict, Optional, Callable
import numpy as np
from scipy import stats
from dataclasses import dataclass

@dataclass
class OverfittingResult:
    """过拟合检测结果"""
    is_overfitted: bool
    p_value: float
    confidence_interval: tuple
    test_statistic: float
    method: str

class OverfittingDetector:
    """过拟合检测器"""

    def __init__(self, n_simulations: int = 1000):
        """
        Args:
            n_simulations: 模拟次数
        """
        self.n_simulations = n_simulations

    def whites_reality_check(self,
                            strategy_returns: np.ndarray,
                            benchmark_returns: Optional[np.ndarray] = None,
                            alternative: str = 'two-sided') -> OverfittingResult:
        """
        White's Reality Check

        检测策略收益是否显著优于随机策略

        Args:
            strategy_returns: 策略收益率序列
            benchmark_returns: 基准收益率序列（可选）
            alternative: 备择假设类型 ('two-sided', 'greater', 'less')

        Returns:
            过拟合检测结果
        """
        # 原策略的最大收益（或夏普比率）
        original_stat = np.mean(strategy_returns) / (np.std(strategy_returns) + 1e-6)

        # 生成零分布
        null_distribution = []

        for _ in range(self.n_simulations):
            # 随机打乱收益率
            shuffled_returns = np.random.permutation(strategy_returns)
            test_stat = np.mean(shuffled_returns) / (np.std(shuffled_returns) + 1e-6)
            null_distribution.append(test_stat)

        null_distribution = np.array(null_distribution)

        # 计算p值
        if alternative == 'two-sided':
            p_value = np.mean(np.abs(null_distribution) >= np.abs(original_stat))
        elif alternative == 'greater':
            p_value = np.mean(null_distribution >= original_stat)
        else:  # 'less'
            p_value = np.mean(null_distribution <= original_stat)

        # 置信区间
        ci_lower = np.percentile(null_distribution, 2.5)
        ci_upper = np.percentile(null_distribution, 97.5)

        return OverfittingResult(
            is_overfitted=p_value < 0.05,
            p_value=p_value,
            confidence_interval=(ci_lower, ci_upper),
            test_statistic=original_stat,
            method='White Reality Check'
        )

    def bootstrap_test(self,
                      returns: np.ndarray,
                      metric: str = 'sharpe',
                      alpha: float = 0.05) -> OverfittingResult:
        """
        Bootstrap检验

        Args:
            returns: 收益率序列
            metric: 检验指标 ('sharpe', 'mean', 'sortino')
            alpha: 显著性水平

        Returns:
            过拟合检测结果
        """
        # 计算原始指标
        if metric == 'sharpe':
            original_stat = np.mean(returns) / (np.std(returns) + 1e-6)
        elif metric == 'mean':
            original_stat = np.mean(returns)
        elif metric == 'sortino':
            downside_returns = returns[returns < 0]
            original_stat = (np.mean(returns) /
                           (np.std(downside_returns) + 1e-6) if len(downside_returns) > 0 else 0)
        else:
            original_stat = np.mean(returns)

        # Bootstrap重采样
        bootstrap_stats = []
        for _ in range(self.n_simulations):
            bootstrap_sample = np.random.choice(returns, size=len(returns), replace=True)

            if metric == 'sharpe':
                stat = np.mean(bootstrap_sample) / (np.std(bootstrap_sample) + 1e-6)
            elif metric == 'mean':
                stat = np.mean(bootstrap_sample)
            elif metric == 'sortino':
                downside = bootstrap_sample[bootstrap_sample < 0]
                stat = (np.mean(bootstrap_sample) /
                       (np.std(downside) + 1e-6) if len(downside) > 0 else 0)
            else:
                stat = np.mean(bootstrap_sample)

            bootstrap_stats.append(stat)

        bootstrap_stats = np.array(bootstrap_stats)

        # 计算置信区间
        ci_lower = np.percentile(bootstrap_stats, alpha / 2 * 100)
        ci_upper = np.percentile(bootstrap_stats, (1 - alpha / 2) * 100)

        # 计算p值
        if original_stat >= 0:
            p_value = np.mean(bootstrap_stats >= original_stat)
        else:
            p_value = np.mean(bootstrap_stats <= original_stat)

        return OverfittingResult(
            is_overfitted=original_stat < ci_lower or original_stat > ci_upper,
            p_value=p_value,
            confidence_interval=(ci_lower, ci_upper),
            test_statistic=original_stat,
            method=f'Bootstrap ({metric})'
        )

    def permutation_test(self,
                        strategy_returns: np.ndarray,
                        benchmark_returns: np.ndarray,
                        n_simulations: int = 1000) -> OverfittingResult:
        """
        排列检验

        检验策略收益与基准收益的差异是否显著

        Args:
            strategy_returns: 策略收益率
            benchmark_returns: 基准收益率
            n_simulations: 模拟次数

        Returns:
            过拟合检测结果
        """
        # 原始差异
        original_diff = np.mean(strategy_returns) - np.mean(benchmark_returns)

        # 生成零分布
        null_distribution = []
        combined = np.concatenate([strategy_returns, benchmark_returns])
        n = len(strategy_returns)

        for _ in range(n_simulations):
            # 随机分配
            np.random.shuffle(combined)
            perm_strategy = combined[:n]
            perm_benchmark = combined[n:]

            diff = np.mean(perm_strategy) - np.mean(perm_benchmark)
            null_distribution.append(diff)

        null_distribution = np.array(null_distribution)

        # 计算p值（双尾）
        p_value = np.mean(np.abs(null_distribution) >= np.abs(original_diff))

        # 置信区间
        ci_lower = np.percentile(null_distribution, 2.5)
        ci_upper = np.percentile(null_distribution, 97.5)

        return OverfittingResult(
            is_overfitted=p_value < 0.05,
            p_value=p_value,
            confidence_interval=(ci_lower, ci_upper),
            test_statistic=original_diff,
            method='Permutation Test'
        )

    def param_sensitivity_analysis(self,
                                   results: Dict[str, Dict[str, float]],
                                   metric: str = 'sharpe') -> Dict[str, float]:
        """
        参数敏感性分析

        Args:
            results: 不同参数组合的结果
            metric: 分析指标

        Returns:
            参数敏感性得分
        """
        # 提取指标值
        values = [r.get(metric, 0) for r in results.values()]

        if len(values) < 2:
            return {}

        # 计算变异系数
        sensitivity = {
            'coefficient_of_variation': np.std(values) / (np.abs(np.mean(values)) + 1e-6),
            'range': np.max(values) - np.min(values),
            'max_value': np.max(values),
            'min_value': np.min(values),
            'mean_value': np.mean(values)
        }

        return sensitivity

    def train_test_gap_analysis(self,
                               train_metrics: Dict[str, float],
                               test_metrics: Dict[str, float]) -> Dict[str, float]:
        """
        训练测试差距分析

        Args:
            train_metrics: 训练集指标
            test_metrics: 测试集指标

        Returns:
            差距分析结果
        """
        gaps = {}
        overfitting_signals = []

        for key in train_metrics:
            if key in test_metrics:
                train_val = train_metrics[key]
                test_val = test_metrics[key]
                gap = train_val - test_val
                gaps[key] = gap

                # 判断是否过拟合
                if key == 'sharpe' and gap > 0.5:
                    overfitting_signals.append(f"{key}: 训练集显著优于测试集")
                elif key == 'total_return' and gap > 0.1:
                    overfitting_signals.append(f"{key}: 训练集收益过高")
                elif key == 'max_drawdown' and gap < -0.05:
                    overfitting_signals.append(f"{key}: 测试集回撤更大")

        return {
            'gaps': gaps,
            'is_overfitted': len(overfitting_signals) > 0,
            'signals': overfitting_signals
        }
```

### 4. 统计显著性检验设计

```python
from typing import List, Dict, Tuple
import numpy as np
from scipy import stats

class SignificanceTester:
    """统计显著性检验器"""

    def __init__(self):
        pass

    def sharpe_ratio_test(self,
                         returns: np.ndarray,
                         risk_free_rate: float = 0.0,
                         periods_per_year: int = 252) -> Dict[str, float]:
        """
        夏普比率显著性检验

        使用Jobson & Korkie方法检验夏普比率是否显著大于0

        Args:
            returns: 收益率序列
            risk_free_rate: 无风险利率
            periods_per_year: 年化周期数

        Returns:
            检验结果
        """
        # 计算年化夏普比率
        excess_returns = returns - risk_free_rate / periods_per_year
        sharpe = np.mean(excess_returns) / (np.std(excess_returns) + 1e-6)
        sharpe_annual = sharpe * np.sqrt(periods_per_year)

        # 计算标准误差
        n = len(returns)
        sharpe_std_err = np.sqrt((1 + 0.5 * sharpe**2) / n)

        # t统计量
        t_stat = sharpe / sharpe_std_err

        # p值（双尾）
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

        # 置信区间
        t_critical = stats.t.ppf(0.975, df=n - 1)
        ci_lower = sharpe - t_critical * sharpe_std_err
        ci_upper = sharpe + t_critical * sharpe_std_err

        return {
            'sharpe_ratio': sharpe_annual,
            't_statistic': t_stat,
            'p_value': p_value,
            'is_significant': p_value < 0.05,
            'confidence_interval': (ci_lower * np.sqrt(periods_per_year),
                                  ci_upper * np.sqrt(periods_per_year)),
            'standard_error': sharpe_std_err
        }

    def bootstrap_confidence_interval(self,
                                     returns: np.ndarray,
                                     metric: str = 'mean',
                                     alpha: float = 0.05,
                                     n_bootstrap: int = 10000) -> Dict[str, float]:
        """
        Bootstrap置信区间

        Args:
            returns: 收益率序列
            metric: 估计指标
            alpha: 显著性水平
            n_bootstrap: Bootstrap次数

        Returns:
            置信区间结果
        """
        # 计算原始估计
        if metric == 'mean':
            original_estimate = np.mean(returns)
        elif metric == 'sharpe':
            original_estimate = np.mean(returns) / (np.std(returns) + 1e-6)
        elif metric == 'sortino':
            downside = returns[returns < 0]
            original_estimate = (np.mean(returns) /
                               (np.std(downside) + 1e-6) if len(downside) > 0 else 0)
        else:
            original_estimate = np.mean(returns)

        # Bootstrap重采样
        bootstrap_estimates = []
        for _ in range(n_bootstrap):
            bootstrap_sample = np.random.choice(returns, size=len(returns), replace=True)

            if metric == 'mean':
                estimate = np.mean(bootstrap_sample)
            elif metric == 'sharpe':
                estimate = np.mean(bootstrap_sample) / (np.std(bootstrap_sample) + 1e-6)
            elif metric == 'sortino':
                downside = bootstrap_sample[bootstrap_sample < 0]
                estimate = (np.mean(bootstrap_sample) /
                           (np.std(downside) + 1e-6) if len(downside) > 0 else 0)
            else:
                estimate = np.mean(bootstrap_sample)

            bootstrap_estimates.append(estimate)

        bootstrap_estimates = np.array(bootstrap_estimates)

        # 计算置信区间（percentile方法）
        ci_lower = np.percentile(bootstrap_estimates, alpha / 2 * 100)
        ci_upper = np.percentile(bootstrap_estimates, (1 - alpha / 2) * 100)

        # 计算标准误差
        std_err = np.std(bootstrap_estimates)

        # 偏差校正
        bias = np.mean(bootstrap_estimates) - original_estimate

        return {
            'estimate': original_estimate,
            'bias_corrected': original_estimate - bias,
            'confidence_interval': (ci_lower, ci_upper),
            'standard_error': std_err,
            'bias': bias
        }

    def bonferroni_correction(self,
                             p_values: List[float],
                             alpha: float = 0.05) -> Dict[str, any]:
        """
        Bonferroni多重比较修正

        Args:
            p_values: p值列表
            alpha: 显著性水平

        Returns:
            修正结果
        """
        n_tests = len(p_values)
        corrected_alpha = alpha / n_tests

        significant = [p < corrected_alpha for p in p_values]
        adjusted_p = [p * n_tests for p in p_values]

        return {
            'original_alpha': alpha,
            'corrected_alpha': corrected_alpha,
            'significant': significant,
            'adjusted_p_values': adjusted_p,
            'num_significant': sum(significant)
        }

    def benjamini_hochberg(self,
                          p_values: List[float],
                          q: float = 0.05) -> Dict[str, any]:
        """
        Benjamini-Hochberg FDR控制

        Args:
            p_values: p值列表
            q: FDR水平

        Returns:
            FDR控制结果
        """
        n_tests = len(p_values)

        # 排序p值
        sorted_indices = sorted(range(n_tests), key=lambda i: p_values[i])
        sorted_p = [p_values[i] for i in sorted_indices]

        # 找到最大显著p值
        threshold = None
        for rank, p in enumerate(sorted_p, 1):
            if p <= (rank / n_tests) * q:
                threshold = p
            else:
                break

        # 判断显著性
        if threshold is not None:
            significant = [p <= threshold for p in p_values]
        else:
            significant = [False] * n_tests

        # 计算q值
        q_values = []
        for i, p in enumerate(sorted_p, 1):
            q_value = min(p * n_tests / i, 1.0)
            q_values.append(q_value)

        # 恢复原始顺序
        adjusted_q = [q_values[sorted_indices.index(i)] for i in range(n_tests)]

        return {
            'q_level': q,
            'threshold': threshold,
            'significant': significant,
            'q_values': adjusted_q,
            'num_significant': sum(significant),
            'fdr': sum(significant) / n_tests if n_tests > 0 else 0
        }

    def multiple_strategy_test(self,
                               returns_dict: Dict[str, np.ndarray],
                               benchmark_returns: np.ndarray) -> Dict[str, Dict]:
        """
        多策略联合检验

        Args:
            returns_dict: 策略收益率字典
            benchmark_returns: 基准收益率

        Returns:
            各策略检验结果
        """
        results = {}
        p_values = []

        # 先计算各策略的p值
        for name, returns in returns_dict.items():
            perm_result = self.permutation_test(returns, benchmark_returns)
            p_values.append(perm_result.p_value)
            results[name] = {
                'original_p': perm_result.p_value,
                'mean_return': np.mean(returns),
                'sharpe': np.mean(returns) / (np.std(returns) + 1e-6)
            }

        # Bonferroni修正
        bonf_result = self.bonferroni_correction(p_values)
        for i, name in enumerate(returns_dict.keys()):
            results[name]['bonferroni_significant'] = bonf_result['significant'][i]
            results[name]['bonferroni_adjusted_p'] = bonf_result['adjusted_p_values'][i]

        # BH修正
        bh_result = self.benjamini_hochberg(p_values)
        for i, name in enumerate(returns_dict.keys()):
            results[name]['bh_significant'] = bh_result['significant'][i]
            results[name]['bh_q_value'] = bh_result['q_values'][i]

        return results

    def permutation_test(self,
                        strategy_returns: np.ndarray,
                        benchmark_returns: np.ndarray,
                        n_simulations: int = 1000) -> Dict[str, float]:
        """
        排列检验

        Args:
            strategy_returns: 策略收益率
            benchmark_returns: 基准收益率
            n_simulations: 模拟次数

        Returns:
            检验结果
        """
        # 原始差异
        original_diff = np.mean(strategy_returns) - np.mean(benchmark_returns)

        # 生成零分布
        null_distribution = []
        combined = np.concatenate([strategy_returns, benchmark_returns])
        n = len(strategy_returns)

        for _ in range(n_simulations):
            np.random.shuffle(combined)
            perm_strategy = combined[:n]
            perm_benchmark = combined[n:]

            diff = np.mean(perm_strategy) - np.mean(perm_benchmark)
            null_distribution.append(diff)

        null_distribution = np.array(null_distribution)

        # 计算p值（双尾）
        p_value = np.mean(np.abs(null_distribution) >= np.abs(original_diff))

        # 置信区间
        ci_lower = np.percentile(null_distribution, 2.5)
        ci_upper = np.percentile(null_distribution, 97.5)

        return {
            'original_diff': original_diff,
            'p_value': p_value,
            'is_significant': p_value < 0.05,
            'confidence_interval': (ci_lower, ci_upper),
            'test_statistic': original_diff / (np.std(null_distribution) + 1e-6)
        }
```

### 5. 稳健性测试框架设计

```python
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass
from enum import Enum
import numpy as np
import pandas as pd

class MarketRegime(Enum):
    """市场状态"""
    BULL = "牛市"      # 上涨趋势
    BEAR = "熊市"      # 下跌趋势
    SIDEWAYS = "震荡"   # 横盘整理
    HIGH_VOL = "高波动" # 高波动
    LOW_VOL = "低波动"  # 低波动

@dataclass
class RobustnessResult:
    """稳健性测试结果"""
    scenario_name: str
    scenario_value: Any
    metrics: Dict[str, float]
    baseline_diff: Dict[str, float]

class RobustnessTester:
    """稳健性测试器"""

    def __init__(self, baseline_metrics: Dict[str, float] = None):
        """
        Args:
            baseline_metrics: 基准指标
        """
        self.baseline_metrics = baseline_metrics or {}

    def test_market_conditions(self,
                              data: pd.DataFrame,
                              strategy_class: type,
                              params: Dict[str, Any]) -> Dict[MarketRegime, RobustnessResult]:
        """
        测试不同市场条件下的表现

        Args:
            data: 包含市场状态的数据
            strategy_class: 策略类
            params: 策略参数

        Returns:
            各市场状态下的结果
        """
        results = {}

        # 检测市场状态
        regimes = self._detect_market_regimes(data)

        for regime, regime_data in regimes.items():
            if len(regime_data) < 50:  # 数据不足
                continue

            # 在该市场状态下回测
            metrics = self._run_backtest(regime_data, strategy_class, params)

            # 计算与基准的差异
            baseline_diff = {}
            if self.baseline_metrics:
                for key in self.baseline_metrics:
                    if key in metrics:
                        baseline_diff[key] = metrics[key] - self.baseline_metrics[key]

            results[regime] = RobustnessResult(
                scenario_name=regime.value,
                scenario_value=regime,
                metrics=metrics,
                baseline_diff=baseline_diff
            )

        return results

    def test_transaction_costs(self,
                               data: pd.DataFrame,
                               strategy_class: type,
                               params: Dict[str, Any],
                               cost_scenarios: List[float] = None) -> List[RobustnessResult]:
        """
        测试不同交易成本下的表现

        Args:
            data: 回测数据
            strategy_class: 策略类
            params: 策略参数
            cost_scenarios: 手续费情景列表

        Returns:
            各成本情景下的结果
        """
        if cost_scenarios is None:
            cost_scenarios = [0.0001, 0.0003, 0.0005, 0.001, 0.002]

        results = []

        for cost in cost_scenarios:
            # 运行回测
            metrics = self._run_backtest(
                data, strategy_class, params,
                commission=cost
            )

            # 计算与基准的差异
            baseline_diff = {}
            if self.baseline_metrics:
                for key in self.baseline_metrics:
                    if key in metrics:
                        baseline_diff[key] = metrics[key] - self.baseline_metrics[key]

            results.append(RobustnessResult(
                scenario_name=f"Commission: {cost:.4f}",
                scenario_value=cost,
                metrics=metrics,
                baseline_diff=baseline_diff
            ))

        return results

    def test_slippage_scenarios(self,
                               data: pd.DataFrame,
                               strategy_class: type,
                               params: Dict[str, Any],
                               slippage_scenarios: List[float] = None) -> List[RobustnessResult]:
        """
        测试不同滑点下的表现

        Args:
            data: 回测数据
            strategy_class: 策略类
            params: 策略参数
            slippage_scenarios: 滑点情景列表

        Returns:
            各滑点情景下的结果
        """
        if slippage_scenarios is None:
            slippage_scenarios = [0.0, 0.0005, 0.001, 0.002, 0.005]

        results = []

        for slippage in slippage_scenarios:
            # 运行回测
            metrics = self._run_backtest(
                data, strategy_class, params,
                slippage_perc=slippage
            )

            # 计算与基准的差异
            baseline_diff = {}
            if self.baseline_metrics:
                for key in self.baseline_metrics:
                    if key in metrics:
                        baseline_diff[key] = metrics[key] - self.baseline_metrics[key]

            results.append(RobustnessResult(
                scenario_name=f"Slippage: {slippage:.4f}",
                scenario_value=slippage,
                metrics=metrics,
                baseline_diff=baseline_diff
            ))

        return results

    def test_parameter_perturbation(self,
                                    data: pd.DataFrame,
                                    strategy_class: type,
                                    base_params: Dict[str, Any],
                                    perturbation_pct: float = 0.1) -> Dict[str, RobustnessResult]:
        """
        测试参数扰动下的稳健性

        Args:
            data: 回测数据
            strategy_class: 策略类
            base_params: 基准参数
            perturbation_pct: 扰动比例

        Returns:
            各参数扰动下的结果
        """
        results = {}

        for param_name, param_value in base_params.items():
            if isinstance(param_value, (int, float)):
                # 向上扰动
                params_plus = base_params.copy()
                params_plus[param_name] = param_value * (1 + perturbation_pct)
                metrics_plus = self._run_backtest(data, strategy_class, params_plus)

                # 向下扰动
                params_minus = base_params.copy()
                params_minus[param_name] = param_value * (1 - perturbation_pct)
                metrics_minus = self._run_backtest(data, strategy_class, params_minus)

                # 敏感性得分
                sensitivity = abs(metrics_plus['sharpe'] - metrics_minus['sharpe']) / (2 * perturbation_pct)

                results[param_name] = RobustnessResult(
                    scenario_name=f"{param_name} ±{perturbation_pct*100:.0f}%",
                    scenario_value=param_name,
                    metrics={'plus': metrics_plus, 'minus': metrics_minus},
                    baseline_diff={'sensitivity': sensitivity}
                )

        return results

    def _detect_market_regimes(self, data: pd.DataFrame) -> Dict[MarketRegime, pd.DataFrame]:
        """检测市场状态"""
        regimes = {}

        # 计算趋势
        data['sma_50'] = data['close'].rolling(50).mean()
        data['sma_200'] = data['close'].rolling(200).mean()

        # 计算波动率
        data['volatility'] = data['close'].pct_change().rolling(20).std()

        # 牛市：短期均线上穿长期均线
        bull_mask = (data['sma_50'] > data['sma_200]) & (data['close'] > data['sma_50'])
        if bull_mask.sum() > 50:
            regimes[MarketRegime.BULL] = data[bull_mask]

        # 熊市：短期均线下穿长期均线
        bear_mask = (data['sma_50'] < data['sma_200']) & (data['close'] < data['sma_50'])
        if bear_mask.sum() > 50:
            regimes[MarketRegime.BEAR] = data[bear_mask]

        # 震荡：价格在均线附近
        sideways_mask = (abs(data['close'] - data['sma_50']) / data['sma_50'] < 0.02)
        if sideways_mask.sum() > 50:
            regimes[MarketRegime.SIDEWAYS] = data[sideways_mask]

        # 高波动
        vol_median = data['volatility'].median()
        high_vol_mask = data['volatility'] > vol_median * 1.5
        if high_vol_mask.sum() > 50:
            regimes[MarketRegime.HIGH_VOL] = data[high_vol_mask]

        # 低波动
        low_vol_mask = data['volatility'] < vol_median * 0.5
        if low_vol_mask.sum() > 50:
            regimes[MarketRegime.LOW_VOL] = data[low_vol_mask]

        return regimes

    def _run_backtest(self,
                     data: pd.DataFrame,
                     strategy_class: type,
                     params: Dict[str, Any],
                     **kwargs) -> Dict[str, float]:
        """运行单次回测"""
        import backtrader as bt

        cerebro = bt.Cerebro()
        cerebro.addstrategy(strategy_class, **params)

        data_feed = bt.feeds.PandasData(dataname=data)
        cerebro.adddata(data_feed)

        cerebro.broker.setcash(kwargs.get('cash', 100000))
        cerebro.broker.setcommission(kwargs.get('commission', 0.001))

        # 设置滑点
        if 'slippage_perc' in kwargs:
            cerebro.broker.set_slippage_perc(slippage_perc=kwargs['slippage_perc'])

        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

        results = cerebro.run()
        strat = results[0]

        sharpe = strat.analyzers.sharpe.get_analysis()
        drawdown = strat.analyzers.drawdown.get_analysis()
        returns = strat.analyzers.returns.get_analysis()

        return {
            'sharpe': sharpe.get('sharperatio', 0),
            'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
            'total_return': returns.get('rtot', 0),
            'annual_return': returns.get('rnorm', 0)
        }

    def calculate_robustness_score(self, results: List[RobustnessResult]) -> Dict[str, float]:
        """
        计算稳健性得分

        Args:
            results: 稳健性测试结果

        Returns:
            稳健性得分
        """
        if not results:
            return {}

        sharpe_values = [r.metrics.get('sharpe', 0) for r in results]
        return_values = [r.metrics.get('total_return', 0) for r in results]

        # 计算变异系数（越小越稳健）
        sharpe_cv = np.std(sharpe_values) / (np.abs(np.mean(sharpe_values)) + 1e-6)
        return_cv = np.std(return_values) / (np.abs(np.mean(return_values)) + 1e-6)

        # 最差情况表现
        worst_sharpe = min(sharpe_values)
        worst_return = min(return_values)

        # 胜率（表现优于基准的比例）
        if self.baseline_metrics:
            baseline_sharpe = self.baseline_metrics.get('sharpe', 0)
            win_rate = sum(s > baseline_sharpe for s in sharpe_values) / len(sharpe_values)
        else:
            win_rate = 0.5

        # 综合稳健性得分（0-100，越高越稳健）
        robustness_score = (
            (1 - min(sharpe_cv, 2) / 2) * 30 +  # 变异系数得分
            min(max(worst_sharpe, -1), 2) / 2 * 30 +  # 最差情况得分
            win_rate * 40  # 胜率得分
        )

        return {
            'robustness_score': robustness_score,
            'sharpe_cv': sharpe_cv,
            'return_cv': return_cv,
            'worst_sharpe': worst_sharpe,
            'worst_return': worst_return,
            'win_rate': win_rate
        }
```

### 6. 前瞻偏差预防器设计

```python
from typing import List, Optional, Callable
import pandas as pd
import numpy as np
from datetime import datetime
import backtrader as bt

class LookaheadBiasDetector:
    """前瞻偏差检测器"""

    def __init__(self):
        self.violations = []

    def check_signal_leakage(self,
                            data: pd.DataFrame,
                            signal_column: str) -> List[dict]:
        """
        检查信号是否存在数据泄露

        Args:
            data: 数据框
            signal_column: 信号列名

        Returns:
            违规记录列表
        """
        violations = []

        # 检查信号是否使用了未来数据
        for i in range(1, len(data)):
            current_signal = data[signal_column].iloc[i]

            # 如果信号完美预测未来收益，可能存在泄露
            future_return = (data['close'].iloc[min(i + 5, len(data) - 1)] /
                           data['close'].iloc[i] - 1)

            # 检查信号方向与未来收益的相关性
            if pd.notna(current_signal) and pd.notna(future_return):
                if (current_signal > 0 and future_return > 0.05) or \
                   (current_signal < 0 and future_return < -0.05):
                    violations.append({
                        'date': data.index[i],
                        'signal': current_signal,
                        'future_return': future_return,
                        'type': 'potential_leakage'
                    })

        self.violations.extend(violations)
        return violations

    def check_indicator_lag(self,
                           data: pd.DataFrame,
                           indicator: pd.Series,
                           price_column: str = 'close') -> List[dict]:
        """
        检查指标是否存在滞后

        Args:
            data: 价格数据
            indicator: 指标序列
            price_column: 价格列名

        Returns:
            违规记录列表
        """
        violations = []

        # 计算指标与价格的相关性（不同滞后阶数）
        max_lag = 5
        correlations = []

        for lag in range(max_lag + 1):
            shifted_indicator = indicator.shift(lag)
            correlation = data[price_column].corr(shifted_indicator)
            correlations.append((lag, correlation))

        # 如果最大相关性出现在滞后>0的位置，说明指标滞后
        best_lag, best_corr = max(correlations, key=lambda x: abs(x[1]))

        if best_lag > 0 and abs(best_corr) > 0.8:
            violations.append({
                'indicator_lag': best_lag,
                'correlation': best_corr,
                'type': 'indicator_lag',
                'message': f'指标滞后{best_lag}期，相关系数{best_corr:.2f}'
            })

        self.violations.extend(violations)
        return violations

    def check_future_information(self,
                                df: pd.DataFrame,
                                columns_to_check: List[str]) -> List[dict]:
        """
        检查数据是否包含未来信息

        Args:
            df: 数据框
            columns_to_check: 需要检查的列

        Returns:
            违规记录列表
        """
        violations = []

        for col in columns_to_check:
            if col not in df.columns:
                continue

            # 检查是否有未来函数
            if 'future' in col.lower():
                violations.append({
                    'column': col,
                    'type': 'future_function',
                    'message': f'列名包含"future"关键字'
                })

            # 检查是否完美预测未来收益
            if 'return' in col.lower():
                # 计算该列与未来收益的相关性
                future_returns = df['close'].pct_change().shift(-1)
                correlation = df[col].corr(future_returns)

                if abs(correlation) > 0.95:
                    violations.append({
                        'column': col,
                        'correlation': correlation,
                        'type': 'perfect_prediction',
                        'message': f'与未来收益相关系数{correlation:.2f}，可能包含未来信息'
                    })

        self.violations.extend(violations)
        return violations

class DataSplitter:
    """严格的数据分片器"""

    def __init__(self,
                 train_ratio: float = 0.7,
                 val_ratio: float = 0.15,
                 test_ratio: float = 0.15):
        """
        Args:
            train_ratio: 训练集比例
            val_ratio: 验证集比例
            test_ratio: 测试集比例
        """
        assert abs(train_ratio + val_ratio + test_ratio - 1.0) < 1e-6
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.test_ratio = test_ratio

    def split(self, data: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """
        分割数据

        Args:
            data: 时间序列数据

        Returns:
            分割后的数据字典
        """
        n_samples = len(data)

        train_end = int(n_samples * self.train_ratio)
        val_end = int(n_samples * (self.train_ratio + self.val_ratio))

        return {
            'train': data.iloc[:train_end].copy(),
            'validation': data.iloc[train_end:val_end].copy(),
            'test': data.iloc[val_end:].copy()
        }

    def split_with_gap(self,
                      data: pd.DataFrame,
                      gap_days: int = 5) -> Dict[str, pd.DataFrame]:
        """
        带间隔的分割（避免数据泄露）

        Args:
            data: 时间序列数据
            gap_days: 训练集和验证集之间的间隔天数

        Returns:
            分割后的数据字典
        """
        n_samples = len(data)

        train_end = int(n_samples * self.train_ratio)
        val_start = train_end + gap_days
        val_end = int(n_samples * (self.train_ratio + self.val_ratio)) + gap_days
        test_start = val_end + gap_days

        return {
            'train': data.iloc[:train_end].copy(),
            'validation': data.iloc[val_start:val_end].copy(),
            'test': data.iloc[test_start:].copy()
        }

class SafeDataFeed(bt.feeds.PandasData):
    """安全的数据源，防止前瞻偏差"""

    params = (
        ('signal_delay', 0),  # 信号延迟bar数
        ('validate', True),   # 是否验证数据
    )

    def __init__(self):
        super().__init__()

        if self.p.validate:
            self._validate_data()

    def _validate_data(self):
        """验证数据"""
        # 检查日期索引
        if not isinstance(self.data.index, pd.DatetimeIndex):
            raise ValueError("数据必须使用Datetime索引")

        # 检查重复日期
        if self.data.index.duplicated().any():
            raise ValueError(f"发现{self.data.index.duplicated().sum()}个重复日期")

        # 检查缺失值
        missing_pct = self.data.isnull().sum() / len(self.data)
        if (missing_pct > 0.1).any():
            raise ValueError(f"列缺失值超过10%: {missing_pct[missing_pct > 0.1].to_dict()}")

    def _get_delayed_signal(self, signal_col: str):
        """获取延迟的信号"""
        if self.p.signal_delay > 0:
            return self.data[signal_col].shift(self.p.signal_delay)
        return self.data[signal_col]

class LookaheadBiasPreventer(bt.Observer):
    """前瞻偏差预防观察者"""

    params = (
        ('check_signals', True),
        ('max_future_lookahead', 0),
    )

    def __init__(self):
        super().__init__()
        self.detector = LookaheadBiasDetector()
        self.signals_generated = []

    def next(self):
        """每个bar检查"""
        if self.p.check_signals:
            # 记录当前bar的信号
            current_data = {
                'date': self.datas[0].datetime.date(0),
                'close': self.datas[0].close[0],
                'strategy_position': self.strategy.position.size if hasattr(self, 'strategy') else 0
            }
            self.signals_generated.append(current_data)

    def stop(self):
        """回测结束检查"""
        # 检查信号是否存在前瞻偏差
        if len(self.signals_generated) > 10:
            df = pd.DataFrame(self.signals_generated)
            violations = self.detector.check_signal_leakage(df, 'strategy_position')

            if violations:
                print(f"警告: 检测到{len(violations)}个潜在前瞻偏差问题")
```

### 7. 整合到Backtrader

```python
import backtrader as bt
from typing import Dict, List, Optional, Any

class EnhancedCerebro(bt.Cerebro):
    """增强的Cerebro，集成验证功能"""

    def __init__(self):
        super().__init__()
        self.cv_results = []
        self.walkforward_results = None
        self.robustness_results = {}

    def add_time_series_cv(self,
                          cv_config: Dict[str, Any]) -> 'EnhancedCerebro':
        """
        添加时间序列交叉验证

        Args:
            cv_config: 交叉验证配置
        """
        self.cv_config = cv_config
        return self

    def run_walkforward(self,
                       param_grid: Dict[str, List],
                       train_size: int = 252,
                       test_size: int = 63,
                       step_size: int = 21) -> WalkForwardSummary:
        """
        运行Walk-forward分析

        Args:
            param_grid: 参数网格
            train_size: 训练窗口
            test_size: 测试窗口
            step_size: 步长

        Returns:
            Walk-forward汇总结果
        """
        analyzer = WalkForwardAnalyzer(
            train_size=train_size,
            test_size=test_size,
            step_size=step_size
        )

        # 获取数据
        data = self._get_combined_data()

        # 获取策略类
        strategy_class = self._get_strategy_class()
        strategy_params = self._get_strategy_params()

        # 运行Walk-forward
        self.walkforward_results = analyzer.run(
            data, strategy_class, param_grid
        )

        return self.walkforward_results

    def run_cross_validation(self,
                            method: str = 'rolling',
                            n_splits: int = 5) -> List[Dict]:
        """
        运行交叉验证

        Args:
            method: 分割方法
            n_splits: 分割数量

        Returns:
            交叉验证结果
        """
        cv = TimeSeriesCV(
            method=method,
            n_splits=n_splits
        )

        # 获取数据
        data = self._get_combined_data()
        splits = cv.split(data)

        # 获取策略类和参数
        strategy_class = self._get_strategy_class()
        strategy_params = self._get_strategy_params()

        results = []
        for split in splits:
            train_data = data.iloc[split.train_indices]
            test_data = data.iloc[split.test_indices]

            # 训练集验证
            train_metrics = self._run_single_backtest(train_data, strategy_class, strategy_params)

            # 测试集验证
            test_metrics = self._run_single_backtest(test_data, strategy_class, strategy_params)

            results.append({
                'split': split,
                'train_metrics': train_metrics,
                'test_metrics': test_metrics,
                'generalization_gap': {k: train_metrics[k] - test_metrics[k]
                                     for k in train_metrics if k in test_metrics}
            })

        self.cv_results = results
        return results

    def test_overfitting(self,
                        returns: np.ndarray,
                        methods: List[str] = None) -> Dict[str, OverfittingResult]:
        """
        测试过拟合

        Args:
            returns: 收益率序列
            methods: 检测方法列表

        Returns:
            过拟合检测结果
        """
        if methods is None:
            methods = ['whites_rc', 'bootstrap']

        detector = OverfittingDetector()
        results = {}

        if 'whites_rc' in methods:
            results['whites_rc'] = detector.whites_reality_check(returns)

        if 'bootstrap' in methods:
            results['bootstrap'] = detector.bootstrap_test(returns)

        if 'permutation' in methods:
            benchmark_returns = self._get_benchmark_returns()
            if benchmark_returns is not None:
                results['permutation'] = detector.permutation_test(returns, benchmark_returns)

        return results

    def test_robustness(self,
                       baseline_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        测试稳健性

        Args:
            baseline_params: 基准参数

        Returns:
            稳健性测试结果
        """
        data = self._get_combined_data()
        strategy_class = self._get_strategy_class()

        # 首先获取基准指标
        baseline_metrics = self._run_single_backtest(data, strategy_class, baseline_params)

        tester = RobustnessTester(baseline_metrics)

        # 交易成本测试
        cost_results = tester.test_transaction_costs(data, strategy_class, baseline_params)

        # 滑点测试
        slippage_results = tester.test_slippage_scenarios(data, strategy_class, baseline_params)

        # 参数扰动测试
        perturbation_results = tester.test_parameter_perturbation(data, strategy_class, baseline_params)

        # 计算稳健性得分
        all_results = cost_results + slippage_results
        robustness_score = tester.calculate_robustness_score(all_results)

        return {
            'cost_results': cost_results,
            'slippage_results': slippage_results,
            'perturbation_results': perturbation_results,
            'robustness_score': robustness_score
        }

    def _get_combined_data(self) -> pd.DataFrame:
        """获取合并后的数据"""
        # 收集所有数据源
        all_data = []
        for feed in self.datas:
            df = self._feed_to_dataframe(feed)
            all_data.append(df)

        if not all_data:
            raise ValueError("没有数据源")

        # 使用第一个数据源
        return all_data[0]

    def _get_strategy_class(self) -> type:
        """获取策略类"""
        if not self.strats:
            raise ValueError("没有添加策略")
        return type(self.strats[0])

    def _get_strategy_params(self) -> Dict[str, Any]:
        """获取策略参数"""
        if not self.strats:
            return {}
        return self.strats[0]._getparams()

    def _get_benchmark_returns(self) -> Optional[np.ndarray]:
        """获取基准收益率"""
        # 可以从配置中获取或计算
        return None

    def _run_single_backtest(self,
                            data: pd.DataFrame,
                            strategy_class: type,
                            params: Dict[str, Any]) -> Dict[str, float]:
        """运行单次回测"""
        cerebro = bt.Cerebro()
        cerebro.addstrategy(strategy_class, **params)

        data_feed = bt.feeds.PandasData(dataname=data)
        cerebro.adddata(data_feed)

        cerebro.broker.setcash(100000)
        cerebro.broker.setcommission(0.001)

        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

        results = cerebro.run()
        strat = results[0]

        return {
            'sharpe': strat.analyzers.sharpe.get_analysis().get('sharperatio', 0),
            'max_drawdown': strat.analyzers.drawdown.get_analysis()['max']['drawdown'],
            'total_return': strat.analyzers.returns.get_analysis()['rtot']
        }

    def _feed_to_dataframe(self, feed) -> pd.DataFrame:
        """将数据源转换为DataFrame"""
        # 简化实现
        return pd.DataFrame()
```

---

## 实施计划

### 第一阶段：交叉验证器（1周）

1. 实现TimeSeriesCV类
2. 实现rolling/expanding/kfold分割
3. 单元测试
4. 可视化功能

### 第二阶段：Walk-forward分析（2周）

1. 实现WalkForwardAnalyzer
2. 参数优化引擎
3. 结果汇总统计
4. 报告生成

### 第三阶段：过拟合检测（2周）

1. 实现White's Reality Check
2. 实现Bootstrap检验
3. 实现Permutation Test
4. 参数敏感性分析

### 第四阶段：统计检验（1周）

1. 实现夏普比率检验
2. 实现多重比较修正
3. 实现置信区间计算
4. 多策略联合检验

### 第五阶段：稳健性测试（1周）

1. 实现RobustnessTester
2. 市场状态检测
3. 成本/滑点敏感性
4. 参数扰动测试

### 第六阶段：前瞻偏差预防（1周）

1. 实现LookaheadBiasDetector
2. 实现DataSplitter
3. 实现SafeDataFeed
4. 集成到Cerebro

### 第七阶段：整合与文档（1周）

1. 实现EnhancedCerebro
2. 集成测试
3. 用户文档
4. 示例代码

---

## API兼容性保证

1. **新增功能独立模块**：所有新增功能作为独立模块
2. **保持原有API不变**：不影响现有回测代码
3. **可选集成**：用户可以选择性使用验证功能
4. **渐进式增强**：可以逐步添加验证步骤

---

## 使用示例

### 示例1：时间序列交叉验证

```python
from backtrader.validation import TimeSeriesCV, EnhancedCerebro

# 创建增强的Cerebro
cerebro = EnhancedCerebro()

# 添加数据和策略
cerebro.adddata(data)
cerebro.addstrategy(MyStrategy, param1=10, param2=20)

# 运行交叉验证
cv_results = cerebro.run_cross_validation(
    method='rolling',
    n_splits=5
)

# 查看结果
for i, result in enumerate(cv_results):
    print(f"Fold {i+1}:")
    print(f"  Train Sharpe: {result['train_metrics']['sharpe']:.2f}")
    print(f"  Test Sharpe: {result['test_metrics']['sharpe']:.2f}")
    print(f"  Generalization Gap: {result['generalization_gap']['sharpe']:.2f}")
```

### 示例2：Walk-forward分析

```python
# 定义参数网格
param_grid = {
    'fast_period': [5, 10, 15],
    'slow_period': [20, 30, 40]
}

# 运行Walk-forward
wf_result = cerebro.run_walkforward(
    param_grid=param_grid,
    train_size=252,
    test_size=63,
    step_size=21
)

# 查看结果
print(f"平均收益率: {wf_result.aggregate_metrics['mean_return']:.2%}")
print(f"胜率: {wf_result.aggregate_metrics['win_rate']:.2%}")
print(f"参数稳定性: {wf_result.param_stability}")
```

### 示例3：过拟合检测

```python
from backtrader.validation import OverfittingDetector

# 获取策略收益率
returns = strategy.get_returns()

# 创建检测器
detector = OverfittingDetector()

# White's Reality Check
wrc_result = detector.whites_reality_check(returns)
print(f"p-value: {wrc_result.p_value:.4f}")
print(f"是否过拟合: {wrc_result.is_overfitted}")

# Bootstrap检验
bs_result = detector.bootstrap_test(returns, metric='sharpe')
print(f"95% CI: [{bs_result.confidence_interval[0]:.2f}, {bs_result.confidence_interval[1]:.2f}]")
```

### 示例4：稳健性测试

```python
from backtrader.validation import RobustnessTester

# 创建测试器
tester = RobustnessTester(baseline_metrics={'sharpe': 1.5})

# 测试交易成本敏感性
cost_results = tester.test_transaction_costs(data, MyStrategy, params)

# 测试滑点敏感性
slippage_results = tester.test_slippage_scenarios(data, MyStrategy, params)

# 计算稳健性得分
score = tester.calculate_robustness_score(cost_results)
print(f"稳健性得分: {score['robustness_score']:.1f}/100")
```

### 示例5：前瞻偏差预防

```python
from backtrader.validation import DataSplitter, LookaheadBiasDetector

# 分割数据
splitter = DataSplitter(train_ratio=0.7, val_ratio=0.15, test_ratio=0.15)
splits = splitter.split(data)

# 检测前瞻偏差
detector = LookaheadBiasDetector()
violations = detector.check_future_information(data, ['signal', 'future_return'])

if violations:
    print(f"检测到{len(violations)}个前瞻偏差问题")
else:
    print("未检测到前瞻偏差")
```

### 示例6：完整验证流程

```python
# 创建增强的Cerebro
cerebro = EnhancedCerebro()
cerebro.adddata(data)
cerebro.addstrategy(MyStrategy)

# 1. 交叉验证
cv_results = cerebro.run_cross_validation(n_splits=5)

# 2. Walk-forward分析
param_grid = {'period': [10, 20, 30]}
wf_results = cerebro.run_walkforward(param_grid)

# 3. 过拟合检测
returns = np.array([r['test_metrics']['total_return'] for r in cv_results])
of_results = cerebro.test_overfitting(returns)

# 4. 稳健性测试
robust_results = cerebro.test_robustness({'period': 20})

# 5. 生成完整报告
generate_validation_report(
    cv_results=cv_results,
    wf_results=wf_results,
    of_results=of_results,
    robust_results=robust_results,
    output_path='validation_report.html'
)
```
