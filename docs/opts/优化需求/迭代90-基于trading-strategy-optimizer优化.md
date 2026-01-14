### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/trading-strategy-optimizer
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### trading-strategy-optimizer项目简介
trading-strategy-optimizer是一个策略参数优化框架，具有以下核心特点：
- **参数优化**: 策略参数优化
- **网格搜索**: 网格搜索优化
- **贝叶斯优化**: 贝叶斯优化方法
- **多目标**: 多目标优化
- **并行计算**: 并行优化计算
- **可视化**: 优化结果可视化

### 重点借鉴方向
1. **优化算法**: 优化算法实现
2. **网格搜索**: 网格搜索优化
3. **贝叶斯优化**: 贝叶斯优化
4. **并行优化**: 并行计算优化
5. **目标函数**: 目标函数设计
6. **结果分析**: 优化结果分析

---

# 分析与设计文档

## 一、框架对比分析

### 1.1 backtrader vs trading-strategy-optimizer 对比

| 维度 | backtrader (原生) | trading-strategy-optimizer |
|------|------------------|---------------------------|
| **定位** | 通用回测框架 | 策略参数优化框架 |
| **优化方法** | cerebro.optstrategy（简单网格） | 多阶段网格搜索 + 启发式评分 |
| **并行计算** | 基础多进程 | 队列式任务调度 + SQLite状态管理 |
| **目标函数** | 单一指标排序 | 多目标复合评分 |
| **结果分析** | 基本分析器 | 多维度排名 + 可视化 |
| **参数空间** | 简单枚举 | 分阶段优化 + 智能范围 |
| **任务管理** | 无 | Web界面 + 任务队列 |
| **结果存储** | 内存 | JSON + 数据库 |

### 1.2 可借鉴的核心优势

1. **分阶段优化**: 将高维参数空间分解为多个低维子问题
2. **复合评分系统**: Profit Factor × Sharpe × (1-Drawdown) 综合评分
3. **任务队列架构**: multiprocessing.Queue + SQLite状态跟踪
4. **智能参数范围**: 基于历史分析缩小搜索空间
5. **Web界面管理**: Flask服务器提供可视化优化控制
6. **结果持久化**: JSON格式保存完整优化结果

---

## 二、需求规格文档

### 2.1 高级优化器框架

**需求描述**: 创建一个统一的策略参数优化框架，支持多种优化算法和并行计算。

**功能要求**:
- 支持网格搜索、随机搜索、贝叶斯优化等算法
- 分阶段优化能力（逐步缩小参数范围）
- 多目标优化（收益率、夏普比率、最大回撤等）
- 参数约束和依赖关系处理
- 优化进度实时跟踪

**接口定义**:
```python
class OptimizerBase:
    def optimize(self, strategy, data, param_space, objective=None):
        """执行优化

        Args:
            strategy: 策略类
            data: 回测数据
            param_space: 参数空间定义
            objective: 目标函数或指标名称

        Returns:
            OptimizationResult对象
        """
        pass

    def get_progress(self):
        """获取优化进度"""
        pass
```

### 2.2 多阶段优化

**需求描述**: 支持将复杂参数空间分解为多个阶段，逐步优化。

**功能要求**:
- 定义优化阶段序列
- 每个阶段使用前一阶段最优参数作为起点
- 支持阶段间参数传递
- 可配置每阶段的搜索范围

**阶段定义示例**:
```python
STAGES = [
    {
        'name': 'Stage1_RiskParameters',
        'params': {
            'atr_sl_multiplier': [1.5, 2.0, 2.5, 3.0],
            'atr_tp_multiplier': [6.0, 8.0, 10.0, 12.0],
        }
    },
    {
        'name': 'Stage2_EntryParameters',
        'params': {
            'ema_fast': [10, 12, 14, 16],
            'ema_slow': [20, 24, 28, 32],
        }
    }
]
```

### 2.3 并行任务调度

**需求描述**: 实现高效的任务调度系统，支持多进程并行优化。

**功能要求**:
- 任务队列管理
- 进程池动态调整
- 任务失败重试机制
- 进度事件通知
- 资源限制（CPU、内存）

### 2.4 多目标优化

**需求描述**: 支持同时优化多个性能指标，提供帕累托前沿分析。

**功能要求**:
- 多目标权重配置
- 帕累托最优解集计算
- 自定义复合评分函数
- 约束条件处理（如最小交易数）

**评分函数示例**:
```python
def composite_score(metrics):
    # 盈利因子
    pf = metrics.get('profit_factor', 0)
    # 夏普比率
    sharpe = max(0, metrics.get('sharpe_ratio', 0))
    # 回撤惩罚
    dd_factor = 1 - (metrics.get('max_drawdown_pct', 100) / 100)
    return pf * sharpe * dd_factor
```

### 2.5 智能参数搜索

**需求描述**: 基于优化历史动态调整参数搜索范围。

**功能要求**:
- 参数敏感性分析
- 自动范围缩窄
- 参数相关性检测
- 早停机制（效果提升不明显时停止）

### 2.6 优化结果分析

**需求描述**: 提供全面的优化结果分析和可视化。

**功能要求**:
- 多维度排序（按不同指标）
- 参数重要性分析
- 优化过程可视化
- 结果对比报告
- 最优参数推荐

---

## 三、详细设计文档

### 3.1 优化器框架核心

**设计思路**: 采用策略模式，将不同优化算法封装为独立的Optimizer类。

```python
# backtrader/optimizers/__init__.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import time
import multiprocessing as mp
from abc import ABCMeta, abstractmethod
from collections import namedtuple
from ..utils.py3 import Queue

logger = logging.getLogger(__name__)


# 优化结果数据结构
OptimizationResult = namedtuple('OptimizationResult', [
    'best_params',      # 最优参数
    'best_score',       # 最优得分
    'all_results',      # 所有结果
    'optimization_time', # 优化耗时
    'total_runs',       # 总运行次数
])


class ParamSpace:
    """参数空间定义

    支持多种参数类型：
    - 固定值: value=10
    - 离散列表: values=[1, 2, 3, 4, 5]
    - 范围: range=(1, 10, 1)  # start, stop, step
    - 对数范围: log_range=(0.001, 1.0, 10)
    """

    def __init__(self, **params):
        self.params = params

    def generate_combinations(self):
        """生成所有参数组合"""
        import itertools

        param_names = []
        param_values = []

        for name, spec in self.params.items():
            param_names.append(name)

            if isinstance(spec, (list, tuple)):
                if len(spec) == 3 and spec[0] == 'log':
                    # 对数范围
                    import numpy as np
                    start, stop, num = spec[1], spec[2], spec[3]
                    param_values.append(np.logspace(start, stop, num).tolist())
                elif isinstance(spec[0], (int, float)):
                    # 范围 (start, stop, step)
                    param_values.append(list(range(*spec)))
                else:
                    # 离散列表
                    param_values.append(spec)
            else:
                # 固定值
                param_values.append([spec])

        # 生成所有组合
        combinations = list(itertools.product(*param_values))

        # 转换为字典列表
        return [dict(zip(param_names, combo)) for combo in combinations]

    def sample(self, n_samples):
        """随机采样参数组合"""
        import random
        combos = self.generate_combinations()
        if len(combos) <= n_samples:
            return combos
        return random.sample(combos, n_samples)


class ObjectiveFunction:
    """目标函数基类

    支持多种目标函数类型：
    - 单指标优化: maximize='sharpe_ratio'
    - 加权组合: weights={'sharpe': 0.5, 'return': 0.3, 'drawdown': -0.2}
    - 自定义函数: custom_func=lambda metrics: metrics['pf'] * metrics['sharpe']
    """

    def __init__(self, maximize=None, weights=None, custom_func=None,
                 constraints=None):
        """
        Args:
            maximize: 单一指标名称（最大化）
            weights: 多指标权重字典
            custom_func: 自定义评分函数
            constraints: 约束条件列表
        """
        self.maximize = maximize
        self.weights = weights or {}
        self.custom_func = custom_func
        self.constraints = constraints or []

    def evaluate(self, metrics):
        """计算目标函数值

        Args:
            metrics: 性能指标字典

        Returns:
            (score, valid) 元组，valid表示是否满足约束
        """
        # 检查约束条件
        for constraint in self.constraints:
            if not constraint.check(metrics):
                return float('-inf'), False

        # 计算得分
        if self.custom_func:
            score = self.custom_func(metrics)
        elif self.maximize:
            score = metrics.get(self.maximize, float('-inf'))
        elif self.weights:
            score = sum(
                metrics.get(k, 0) * v
                for k, v in self.weights.items()
            )
        else:
            score = metrics.get('profit_factor', float('-inf'))

        return score, True

    def is_better(self, score1, score2):
        """比较两个得分"""
        return score1 > score2


class Constraint:
    """约束条件基类"""

    def __init__(self, condition):
        self.condition = condition

    def check(self, metrics):
        """检查是否满足约束"""
        return self.condition(metrics)


class MinTradesConstraint(Constraint):
    """最小交易数约束"""

    def __init__(self, min_trades=10):
        def condition(metrics):
            return metrics.get('trades', 0) >= min_trades
        super().__init__(condition)


class MaxDrawdownConstraint(Constraint):
    """最大回撤约束"""

    def __init__(self, max_dd_pct=30):
        def condition(metrics):
            return metrics.get('max_drawdown_pct', 100) <= max_dd_pct
        super().__init__(condition)


class OptimizerBase(six.with_metaclass(ABCMeta, object)):
    """优化器基类"""

    def __init__(self, cerebro_factory, objective=None, n_jobs=1,
                 callback=None, timeout=None):
        """
        Args:
            cerebro_factory: 创建cerebro实例的函数
            objective: 目标函数
            n_jobs: 并行任务数
            callback: 进度回调函数
            timeout: 单个回测超时时间
        """
        self.cerebro_factory = cerebro_factory
        self.objective = objective or ObjectiveFunction(maximize='profit_factor')
        self.n_jobs = max(1, n_jobs)
        self.callback = callback
        self.timeout = timeout

        self._results = []
        self._best_score = float('-inf')
        self._best_params = None

    @abstractmethod
    def _optimize(self, param_space):
        """执行优化（子类实现）"""
        pass

    def optimize(self, param_space):
        """执行优化"""
        start_time = time.time()

        # 执行优化
        self._optimize(param_space)

        # 返回结果
        return OptimizationResult(
            best_params=self._best_params,
            best_score=self._best_score,
            all_results=self._results,
            optimization_time=time.time() - start_time,
            total_runs=len(self._results)
        )

    def _evaluate_params(self, params):
        """评估单组参数

        Args:
            params: 参数字典

        Returns:
            (score, metrics, valid) 元组
        """
        # 创建cerebro
        cerebro = self.cerebro_factory(params)

        try:
            # 执行回测
            if self.timeout:
                import signal

                def timeout_handler(signum, frame):
                    raise TimeoutError()

                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(self.timeout)

            strats = cerebro.run()
            signal.alarm(0)  # 取消超时

            # 提取指标
            metrics = self._extract_metrics(strats[0])

            # 评估
            score, valid = self.objective.evaluate(metrics)

            return score, metrics, valid

        except Exception as e:
            logger.error(f'Backtest failed for params {params}: {e}')
            return float('-inf'), {}, False

    def _extract_metrics(self, strategy):
        """从策略中提取性能指标"""
        metrics = {}

        # 基础指标
        if hasattr(strategy, 'portfolio_values'):
            import numpy as np
            values = strategy.portfolio_values
            if values:
                metrics['final_value'] = values[-1]
                metrics['total_return'] = (values[-1] - values[0]) / values[0] * 100

                returns = np.diff(values) / values[:-1]
                metrics['volatility'] = np.std(returns) * np.sqrt(252) * 100
                metrics['sharpe_ratio'] = (
                    np.mean(returns) / np.std(returns) * np.sqrt(252)
                    if np.std(returns) > 0 else 0
                )

        # 交易指标
        if hasattr(strategy, 'trades'):
            metrics['trades'] = strategy.trades
            metrics['wins'] = getattr(strategy, 'wins', 0)
            metrics['losses'] = getattr(strategy, 'losses', 0)
            metrics['win_rate'] = (
                metrics['wins'] / metrics['trades'] * 100
                if metrics['trades'] > 0 else 0
            )

        # 盈亏指标
        if hasattr(strategy, 'gross_profit'):
            metrics['gross_profit'] = strategy.gross_profit
            metrics['gross_loss'] = abs(getattr(strategy, 'gross_loss', 1))
            metrics['profit_factor'] = (
                strategy.gross_profit / metrics['gross_loss']
                if metrics['gross_loss'] > 0 else float('inf')
            )

        # 回撤指标
        if hasattr(strategy, 'max_drawdown_pct'):
            metrics['max_drawdown_pct'] = strategy.max_drawdown_pct

        return metrics

    def _update_best(self, params, score, metrics):
        """更新最优结果"""
        if score > self._best_score:
            self._best_score = score
            self._best_params = params.copy()

        # 记录结果
        self._results.append({
            'params': params.copy(),
            'score': score,
            'metrics': metrics.copy()
        })

        # 回调
        if self.callback:
            self.callback(params, score, metrics)
```

### 3.2 网格搜索优化器

**设计思路**: 实现基础网格搜索，支持分阶段优化。

```python
# backtrader/optimizers/grid_search.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import itertools
from concurrent.futures import ProcessPoolExecutor, as_completed
from . import OptimizerBase, ParamSpace

logger = logging.getLogger(__name__)


class GridSearchOptimizer(OptimizerBase):
    """网格搜索优化器

    遍历所有参数组合，找到最优解
    """

    def __init__(self, cerebro_factory, objective=None, n_jobs=1,
                 callback=None, timeout=None, stage_name=None):
        super().__init__(cerebro_factory, objective, n_jobs, callback, timeout)
        self.stage_name = stage_name

    def _optimize(self, param_space):
        """执行网格搜索"""
        # 生成参数组合
        if isinstance(param_space, ParamSpace):
            combinations = param_space.generate_combinations()
        else:
            # 兼容字典格式
            ps = ParamSpace(**param_space)
            combinations = ps.generate_combinations()

        total = len(combinations)
        logger.info(f'Starting grid search with {total} combinations '
                   f'(stage: {self.stage_name or "default"})')

        # 并行执行
        if self.n_jobs > 1:
            self._parallel_evaluate(combinations)
        else:
            self._sequential_evaluate(combinations)

        logger.info(f'Grid search completed. Best score: {self._best_score:.4f}')

    def _sequential_evaluate(self, combinations):
        """顺序评估"""
        for i, params in enumerate(combinations):
            score, metrics, valid = self._evaluate_params(params)

            if valid:
                self._update_best(params, score, metrics)

            if (i + 1) % 10 == 0:
                logger.info(f'Progress: {i + 1}/{len(combinations)}')

    def _parallel_evaluate(self, combinations):
        """并行评估"""
        with ProcessPoolExecutor(max_workers=self.n_jobs) as executor:
            # 提交所有任务
            futures = {
                executor.submit(self._evaluate_params, params): params
                for params in combinations
            }

            # 收集结果
            completed = 0
            for future in as_completed(futures):
                params = futures[future]
                try:
                    score, metrics, valid = future.result()
                    if valid:
                        self._update_best(params, score, metrics)
                except Exception as e:
                    logger.error(f'Evaluation failed: {e}')

                completed += 1
                if completed % 10 == 0:
                    logger.info(f'Progress: {completed}/{len(combinations)}')


class MultiStageOptimizer:
    """多阶段优化器

    将高维参数空间分解为多个低维优化阶段
    """

    def __init__(self, cerebro_factory, stages, objective=None, n_jobs=1):
        """
        Args:
            cerebro_factory: cerebro工厂函数
            stages: 优化阶段列表
            objective: 目标函数
            n_jobs: 并行数
        """
        self.cerebro_factory = cerebro_factory
        self.stages = stages
        self.objective = objective
        self.n_jobs = n_jobs

        self.stage_results = []
        self.final_params = {}

    def optimize(self):
        """执行多阶段优化"""
        current_params = {}

        for i, stage in enumerate(self.stages):
            stage_name = stage.get('name', f'Stage{i+1}')
            stage_params = stage['params']

            logger.info(f'=== {stage_name} ===')

            # 创建工厂函数，使用当前最优参数
            def factory(params_override):
                cerebro = self.cerebro_factory({**current_params, **params_override})
                return cerebro

            # 执行阶段优化
            optimizer = GridSearchOptimizer(
                factory, self.objective, self.n_jobs,
                stage_name=stage_name
            )

            # 合并当前参数
            param_space = ParamSpace(**stage_params)
            result = optimizer.optimize(param_space)

            # 更新最优参数
            current_params.update(result.best_params)
            self.stage_results.append({
                'stage': stage_name,
                'best_params': result.best_params,
                'best_score': result.best_score,
            })

            logger.info(f'{stage_name} best: {result.best_params}')
            logger.info(f'{stage_name} score: {result.best_score:.4f}')

        self.final_params = current_params
        return self.stage_results

    def get_final_params(self):
        """获取最终最优参数"""
        return self.final_params

    def get_stage_results(self):
        """获取各阶段结果"""
        return self.stage_results
```

### 3.3 贝叶斯优化器

**设计思路**: 使用高斯过程代理模型，智能选择下一组评估参数。

```python
# backtrader/optimizers/bayesian.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import numpy as np

logger = logging.getLogger(__name__)


class BayesianOptimizer(OptimizerBase):
    """贝叶斯优化器

    使用高斯过程代理模型，通过采集函数智能选择下一组参数
    """

    def __init__(self, cerebro_factory, objective=None, n_jobs=1,
                 callback=None, timeout=None, n_iter=50,
                 init_points=5, acq='ei', kappa=2.576):
        """
        Args:
            cerebro_factory: cerebro工厂函数
            objective: 目标函数
            n_jobs: 并行数
            n_iter: 迭代次数
            init_points: 初始随机采样点数
            acq: 采集函数类型 ('ei', 'ucb', 'poi')
            kappa: UCB的探索参数
        """
        super().__init__(cerebro_factory, objective, n_jobs, callback, timeout)
        self.n_iter = n_iter
        self.init_points = init_points
        self.acq = acq
        self.kappa = kappa

        # 观测历史
        self._X = []  # 参数
        self._y = []  # 目标值

        # 参数空间（用于归一化）
        self._bounds = {}

    def _optimize(self, param_space):
        """执行贝叶斯优化"""
        # 设置参数空间
        if isinstance(param_space, ParamSpace):
            self._setup_bounds(param_space)
        else:
            self._setup_bounds(ParamSpace(**param_space))

        total = self.init_points + self.n_iter

        # 初始随机采样
        logger.info(f'Initial random sampling ({self.init_points} points)')
        for _ in range(self.init_points):
            x = self._random_sample()
            self._evaluate_and_record(x)

        # 贝叶斯优化迭代
        logger.info(f'Bayesian optimization ({self.n_iter} iterations)')
        for i in range(self.n_iter):
            # 选择下一个点
            x = self._suggest_next()

            # 评估
            self._evaluate_and_record(x)

            if (i + 1) % 10 == 0:
                logger.info(f'Iteration {i + 1}/{self.n_iter}, '
                           f'best: {self._best_score:.4f}')

    def _setup_bounds(self, param_space):
        """设置参数边界"""
        for name, values in param_space.params.items():
            if isinstance(values, list):
                self._bounds[name] = (min(values), max(values))
            elif len(values) >= 2:
                self._bounds[name] = (values[0], values[1])

    def _random_sample(self):
        """随机采样参数"""
        import random
        params = {}
        for name, (low, high) in self._bounds.items():
            params[name] = random.uniform(low, high)
        return params

    def _evaluate_and_record(self, params):
        """评估并记录结果"""
        score, metrics, valid = self._evaluate_params(params)

        if valid:
            # 记录
            x = self._params_to_vector(params)
            self._X.append(x)
            self._y.append(score)

            # 更新最优
            self._update_best(params, score, metrics)

    def _params_to_vector(self, params):
        """将参数字典转换为向量"""
        return np.array([params[name] for name in self._bounds.keys()])

    def _vector_to_params(self, vector):
        """将向量转换为参数字典"""
        return {name: val for name, val in zip(self._bounds.keys(), vector)}

    def _suggest_next(self):
        """建议下一个评估点"""
        if len(self._X) < 2:
            return self._random_sample()

        # 拟合高斯过程
        mu, sigma = self._fit_gp()

        # 优化采集函数
        x_next = self._optimize_acquisition(mu, sigma)

        return self._vector_to_params(x_next)

    def _fit_gp(self):
        """拟合高斯过程代理模型"""
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import RBF, ConstantKernel

        X = np.array(self._X)
        y = np.array(self._y)

        # 核函数
        kernel = ConstantKernel(1.0) * RBF(length_scale=1.0)

        # GP模型
        gp = GaussianProcessRegressor(kernel=kernel, alpha=1e-6,
                                     normalize_y=True)
        gp.fit(X, y)

        # 预测整个空间的均值和方差
        x_min = np.array([v[0] for v in self._bounds.values()])
        x_max = np.array([v[1] for v in self._bounds.values()])

        # 生成网格点
        n_grid = 100
        x_grid = np.random.uniform(x_min, x_max, (n_grid, len(x_min)))

        mu, sigma = gp.predict(x_grid, return_std=True)

        return gp, x_grid, mu, sigma

    def _optimize_acquisition(self, gp, x_grid, mu, sigma):
        """优化采集函数"""
        if self.acq == 'ei':
            # Expected Improvement
            y_max = np.max(self._y)
            with np.errstate(divide='warn'):
                imp = mu - y_max - self.kappa
                Z = imp / sigma
                ei = imp * norm.cdf(Z) + sigma * norm.pdf(Z)
                ei[sigma == 0.0] = 0.0
            scores = ei

        elif self.acq == 'ucb':
            # Upper Confidence Bound
            scores = mu + self.kappa * sigma

        elif self.acq == 'poi':
            # Probability of Improvement
            y_max = np.max(self._y)
            with np.errstate(divide='warn'):
                Z = (mu - y_max - self.kappa) / sigma
                scores = norm.cdf(Z)
            scores[sigma == 0.0] = 0.0

        else:
            raise ValueError(f'Unknown acquisition function: {self.acq}')

        # 返回得分最高的点
        best_idx = np.argmax(scores)
        return x_grid[best_idx]
```

### 3.4 并行任务调度器

**设计思路**: 实现基于队列的任务调度，支持动态进程池和状态跟踪。

```python
# backtrader/optimizers/scheduler.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import multiprocessing as mp
import time
import threading
from queue import Empty
from ..utils.py3 import Queue

logger = logging.getLogger(__name__)


class TaskStatus:
    """任务状态"""
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'


class Task:
    """优化任务"""

    def __init__(self, task_id, params, priority=0):
        self.task_id = task_id
        self.params = params
        self.priority = priority
        self.status = TaskStatus.PENDING
        self.result = None
        self.error = None
        self.created_time = time.time()
        self.started_time = None
        self.completed_time = None

    def __lt__(self, other):
        """用于优先级队列"""
        return self.priority > other.priority


class TaskScheduler:
    """任务调度器

    特性：
    - 基于队列的任务分发
    - 动态进程池
    - 任务状态跟踪
    - 失败重试
    """

    def __init__(self, n_workers=None, max_retries=2, timeout=300):
        """
        Args:
            n_workers: 工作进程数（默认CPU核心数）
            max_retries: 最大重试次数
            timeout: 任务超时时间（秒）
        """
        self.n_workers = n_workers or mp.cpu_count()
        self.max_retries = max_retries
        self.timeout = timeout

        # 任务队列
        self.task_queue = mp.Queue()
        self.result_queue = mp.Queue()

        # 状态跟踪
        self.tasks = {}
        self.task_counter = 0
        self._lock = threading.Lock()

        # 进程管理
        self.workers = []
        self.running = False

    def add_task(self, params, priority=0):
        """添加任务"""
        with self._lock:
            task_id = f'task_{self.task_counter}'
            self.task_counter += 1

            task = Task(task_id, params, priority)
            self.tasks[task_id] = task
            self.task_queue.put((task_id, params))

            return task_id

    def get_task_status(self, task_id):
        """获取任务状态"""
        task = self.tasks.get(task_id)
        return task.status if task else None

    def get_result(self, task_id, timeout=None):
        """获取任务结果"""
        task = self.tasks.get(task_id)
        if not task:
            return None

        if task.status == TaskStatus.COMPLETED:
            return task.result

        # 等待完成
        start = time.time()
        while task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            if timeout and (time.time() - start) > timeout:
                return None
            time.sleep(0.1)

        return task.result if task.status == TaskStatus.COMPLETED else None

    def start(self):
        """启动调度器"""
        if self.running:
            return

        self.running = True

        # 启动工作进程
        for i in range(self.n_workers):
            p = mp.Process(
                target=_worker_main,
                args=(self.task_queue, self.result_queue, i, self.timeout)
            )
            p.daemon = True
            p.start()
            self.workers.append(p)

        # 启动结果收集线程
        self.collector_thread = threading.Thread(target=self._collect_results)
        self.collector_thread.daemon = True
        self.collector_thread.start()

        logger.info(f'Scheduler started with {self.n_workers} workers')

    def stop(self):
        """停止调度器"""
        self.running = False

        # 终止工作进程
        for p in self.workers:
            if p.is_alive():
                p.terminate()
                p.join(timeout=1)

        self.workers = []

        logger.info('Scheduler stopped')

    def _collect_results(self):
        """收集结果"""
        while self.running:
            try:
                task_id, result, error = self.result_queue.get(timeout=1)

                with self._lock:
                    task = self.tasks.get(task_id)
                    if task:
                        task.completed_time = time.time()

                        if error:
                            task.status = TaskStatus.FAILED
                            task.error = error

                            # 重试
                            if task.error_count < self.max_retries:
                                task.error_count += 1
                                task.status = TaskStatus.PENDING
                                self.task_queue.put((task_id, task.params))
                                logger.info(f'Retrying task {task_id} '
                                           f'({task.error_count}/{self.max_retries})')
                        else:
                            task.status = TaskStatus.COMPLETED
                            task.result = result

            except Empty:
                continue
            except Exception as e:
                logger.error(f'Error collecting result: {e}')

    def get_progress(self):
        """获取进度"""
        with self._lock:
            total = len(self.tasks)
            completed = sum(1 for t in self.tasks.values()
                           if t.status == TaskStatus.COMPLETED)
            failed = sum(1 for t in self.tasks.values()
                        if t.status == TaskStatus.FAILED)
            running = sum(1 for t in self.tasks.values()
                         if t.status == TaskStatus.RUNNING)

            return {
                'total': total,
                'completed': completed,
                'failed': failed,
                'running': running,
                'pending': total - completed - failed - running,
            }


def _worker_main(task_queue, result_queue, worker_id, timeout):
    """工作进程主函数"""
    import signal

    def timeout_handler(signum, frame):
        raise TimeoutError()

    signal.signal(signal.SIGALRM, timeout_handler)

    logger.info(f'Worker {worker_id} started')

    while True:
        try:
            task_id, params = task_queue.get(timeout=1)

            # 执行任务
            try:
                signal.alarm(timeout)
                result = _execute_backtest(params)
                signal.alarm(0)

                result_queue.put((task_id, result, None))

            except TimeoutError:
                logger.warning(f'Task {task_id} timeout on worker {worker_id}')
                result_queue.put((task_id, None, 'Timeout'))

            except Exception as e:
                logger.error(f'Task {task_id} failed on worker {worker_id}: {e}')
                result_queue.put((task_id, None, str(e)))

        except Empty:
            continue
        except Exception as e:
            logger.error(f'Worker {worker_id} error: {e}')


def _execute_backtest(params):
    """执行回测（需要在子进程中重新导入）"""
    # 这里需要用户提供自己的回测执行函数
    # 或者使用cerebro工厂函数
    raise NotImplementedError('Use custom executor or provide cerebro_factory')
```

### 3.5 优化结果分析器

**设计思路**: 提供多维度结果分析和可视化。

```python
# backtrader/optimizers/analysis.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import json
import numpy as np
from collections import defaultdict

logger = logging.getLogger(__name__)


class OptimizationAnalyzer:
    """优化结果分析器

    提供：
    - 多维度排序
    - 参数重要性分析
    - 帕累托前沿分析
    - 结果对比
    """

    def __init__(self, results):
        """
        Args:
            results: 优化结果列表
        """
        self.results = results
        self.df = None

    def to_dataframe(self):
        """转换为DataFrame"""
        import pandas as pd

        if self.df is None:
            records = []
            for r in self.results:
                record = r['params'].copy()
                record['score'] = r['score']
                record.update(r['metrics'])
                records.append(record)

            self.df = pd.DataFrame(records)

        return self.df

    def get_top_n(self, n=10, sort_by='score'):
        """获取前N个结果"""
        df = self.to_dataframe()
        return df.nlargest(n, sort_by)

    def get_bottom_n(self, n=10, sort_by='score'):
        """获取后N个结果"""
        df = self.to_dataframe()
        return df.nsmallest(n, sort_by)

    def rank_by(self, metric):
        """按指定指标排序"""
        df = self.to_dataframe()
        return df.sort_values(metric, ascending=False)

    def analyze_parameter_importance(self):
        """分析参数重要性

        使用方差分析计算每个参数对目标值的影响
        """
        import pandas as pd
        from scipy import stats

        df = self.to_dataframe()

        importance = {}
        param_cols = [c for c in df.columns
                     if c not in ['score', 'metrics'] and not c.startswith('_')]

        for param in param_cols:
            if param in df.columns:
                # 按参数值分组
                groups = df.groupby(param)['score'].apply(list)

                # 单因素方差分析
                if len(groups) > 1:
                    try:
                        f_stat, p_value = stats.f_oneway(*groups.values)
                        importance[param] = {
                            'f_statistic': f_stat,
                            'p_value': p_value,
                            'importance': -np.log10(p_value) if p_value > 0 else float('inf')
                        }
                    except:
                        pass

        # 按重要性排序
        sorted_importance = sorted(
            importance.items(),
            key=lambda x: x[1]['importance'],
            reverse=True
        )

        return sorted_importance

    def get_pareto_front(self, objectives=None):
        """获取帕累托前沿

        Args:
            objectives: 优化目标列表，默认 ['profit_factor', 'sharpe_ratio']
                        可指定方向，如 [('profit_factor', 'max'), ('max_drawdown_pct', 'min')]
        """
        if objectives is None:
            objectives = [
                ('score', 'max'),
                ('profit_factor', 'max'),
                ('sharpe_ratio', 'max'),
            ]

        df = self.to_dataframe()

        # 提取目标值
        points = []
        for _, row in df.iterrows():
            point = []
            for obj, direction in objectives:
                val = row.get(obj, 0)
                if direction == 'min':
                    val = -val
                point.append(val)
            points.append(point)

        points = np.array(points)

        # 计算帕累托前沿
        is_pareto = np.ones(len(points), dtype=bool)

        for i in range(len(points)):
            if not is_pareto[i]:
                continue
            for j in range(len(points)):
                if i != j and is_pareto[j]:
                    if np.all(points[j] >= points[i]) and np.any(points[j] > points[i]):
                        is_pareto[i] = False
                        break

        pareto_df = df[is_pareto].copy()
        return pareto_df

    def parameter_correlation(self):
        """分析参数相关性"""
        df = self.to_dataframe()

        # 只选择数值列
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        corr = df[numeric_cols].corr()

        return corr

    def generate_report(self, output_file=None):
        """生成优化报告"""
        report = {
            'summary': {
                'total_runs': len(self.results),
                'best_score': max(r['score'] for r in self.results),
                'worst_score': min(r['score'] for r in self.results),
            },
            'top_10': self.get_top_n(10).to_dict('records'),
            'parameter_importance': self.analyze_parameter_importance(),
        }

        if output_file:
            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2, default=str)
            logger.info(f'Report saved to {output_file}')

        return report

    def plot_optimization_surface(self, param1, param2, metric='score'):
        """绘制优化曲面

        Args:
            param1: X轴参数
            param2: Y轴参数
            metric: 颜色映射指标
        """
        import matplotlib.pyplot as plt
        import pandas as pd

        df = self.to_dataframe()

        # 创建透视表
        pivot = df.pivot_table(
            values=metric,
            index=param2,
            columns=param1,
            aggfunc='mean'
        )

        # 绘制热力图
        fig, ax = plt.subplots(figsize=(10, 8))
        im = ax.imshow(pivot.values, cmap='viridis', aspect='auto')

        # 设置坐标轴
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_yticks(range(len(pivot.index)))
        ax.set_xticklabels(pivot.columns)
        ax.set_yticklabels(pivot.index)

        # 颜色条
        plt.colorbar(im, ax=ax, label=metric)

        ax.set_xlabel(param1)
        ax.set_ylabel(param2)
        ax.set_title(f'Optimization Surface: {metric}')

        plt.tight_layout()
        return fig

    def plot_parameter_distribution(self, param=None, bins=20):
        """绘制参数分布

        Args:
            param: 参数名，None则绘制所有参数
            bins: 直方图箱数
        """
        import matplotlib.pyplot as plt
        import pandas as pd

        df = self.to_dataframe()

        if param:
            fig, ax = plt.subplots()
            ax.hist(df[param], bins=bins, edgecolor='black')
            ax.set_xlabel(param)
            ax.set_ylabel('Frequency')
            ax.set_title(f'Distribution of {param}')
            return fig
        else:
            # 绘制所有参数分布
            param_cols = [c for c in df.columns
                         if c not in ['score', 'metrics'] and not c.startswith('_')]

            n_cols = 4
            n_rows = (len(param_cols) + n_cols - 1) // n_cols

            fig, axes = plt.subplots(n_rows, n_cols, figsize=(16, 4*n_rows))
            axes = axes.flatten() if n_rows > 1 else [axes]

            for i, col in enumerate(param_cols):
                if i < len(axes):
                    axes[i].hist(df[col], bins=bins, edgecolor='black')
                    axes[i].set_xlabel(col)
                    axes[i].set_ylabel('Frequency')

            # 隐藏多余子图
            for i in range(len(param_cols), len(axes)):
                axes[i].set_visible(False)

            plt.tight_layout()
            return fig
```

### 3.6 使用示例

```python
# 使用优化器的完整示例

import backtrader as bt
from backtrader.optimizers import (
    GridSearchOptimizer, MultiStageOptimizer,
    BayesianOptimizer, ParamSpace, ObjectiveFunction,
    MinTradesConstraint
)


# 1. 定义策略
class MyStrategy(bt.Strategy):
    params = dict(
        ema_fast=10,
        ema_slow=20,
        atr_mult=2.0,
    )

    def __init__(self):
        self.ema_fast = bt.ind.EMA(self.data.close, period=self.p.ema_fast)
        self.ema_slow = bt.ind.EMA(self.data.close, period=self.p.ema_slow)
        self.atr = bt.ind.ATR(self.data, period=14)

    def next(self):
        if not self.position:
            if self.ema_fast[0] > self.ema_slow[0]:
                size = self.broker.getcash() / self.data.close[0] * 0.95
                self.buy(size=size)
        else:
            if self.ema_fast[0] < self.ema_slow[0]:
                self.sell()


# 2. 定义cerebro工厂函数
def create_cerebro(params_override=None):
    cerebro = bt.Cerebro()

    # 添加数据
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    # 添加策略
    if params_override:
        cerebro.addstrategy(MyStrategy, **params_override)
    else:
        cerebro.addstrategy(MyStrategy)

    # 设置初始资金
    cerebro.broker.setcash(10000)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    return cerebro


# 3. 定义参数空间
param_space = ParamSpace(
    ema_fast=[8, 10, 12, 14, 16],
    ema_slow=[18, 20, 24, 28, 32],
    atr_mult=[1.5, 2.0, 2.5, 3.0],
)


# 4. 定义目标函数
objective = ObjectiveFunction(
    custom_func=lambda m: m.get('profit_factor', 0) * max(0, m.get('sharpe_ratio', 0)),
    constraints=[
        MinTradesConstraint(min_trades=20),
    ]
)


# 5. 执行网格搜索
optimizer = GridSearchOptimizer(
    cerebro_factory=create_cerebro,
    objective=objective,
    n_jobs=4,
    callback=lambda p, s, m: print(f"Score: {s:.4f}, Params: {p}")
)

result = optimizer.optimize(param_space)
print(f"Best params: {result.best_params}")
print(f"Best score: {result.best_score:.4f}")


# 6. 多阶段优化
stages = [
    {
        'name': 'Stage1_EMA',
        'params': {
            'ema_fast': [8, 10, 12, 14, 16],
            'ema_slow': [18, 20, 24, 28, 32],
        }
    },
    {
        'name': 'Stage2_ATR',
        'params': {
            'atr_mult': [1.5, 2.0, 2.5, 3.0],
        }
    }
]

multi_optimizer = MultiStageOptimizer(
    cerebro_factory=create_cerebro,
    stages=stages,
    objective=objective,
    n_jobs=4
)

stage_results = multi_optimizer.optimize()
print(f"Final params: {multi_optimizer.get_final_params()}")


# 7. 结果分析
from backtrader.optimizers import OptimizationAnalyzer

analyzer = OptimizationAnalyzer(result.all_results)
print("Top 10:")
print(analyzer.get_top_n(10))

print("\nParameter importance:")
for param, imp in analyzer.analyze_parameter_importance():
    print(f"  {param}: {imp['importance']:.4f}")

# 生成报告
analyzer.generate_report('optimization_report.json')
```

---

## 四、目录结构

```
backtrader/
├── optimizers/
│   ├── __init__.py                 # 优化器模块导出
│   ├── base.py                     # 基础类和接口
│   ├── grid_search.py              # 网格搜索优化器
│   ├── bayesian.py                 # 贝叶斯优化器
│   ├── random_search.py            # 随机搜索优化器
│   ├── genetic.py                  # 遗传算法优化器
│   ├── scheduler.py                # 并行任务调度器
│   └── analysis.py                 # 结果分析器
│
├── utils/
│   └── opt_utils.py                # 优化工具函数
│
└── analyzers/
    └── opt_analyzer.py             # 优化专用分析器
```

---

## 五、实施计划

### 第一阶段（高优先级）

1. **基础优化器框架**
   - 实现`OptimizerBase`基类
   - 实现`ParamSpace`参数空间类
   - 实现`ObjectiveFunction`目标函数类
   - 实现约束条件系统

2. **网格搜索优化器**
   - 实现`GridSearchOptimizer`
   - 支持并行执行
   - 进度回调

3. **结果分析器**
   - 实现`OptimizationAnalyzer`
   - 多维度排序
   - 参数重要性分析

### 第二阶段（中优先级）

4. **多阶段优化**
   - 实现`MultiStageOptimizer`
   - 阶段间参数传递
   - 阶段结果聚合

5. **并行任务调度**
   - 实现`TaskScheduler`
   - 动态进程池
   - 失败重试机制

6. **高级优化算法**
   - 实现贝叶斯优化器
   - 实现随机搜索
   - 实现遗传算法

### 第三阶段（可选）

7. **可视化和报告**
   - 优化曲面可视化
   - 参数分布图
   - HTML报告生成
   - 交互式Web界面

8. **高级功能**
   - 早停机制
   - 参数相关性分析
   - 自动参数范围推荐
   - 超参数迁移学习

---

## 六、向后兼容性

所有新增功能均为**可选扩展**，不影响现有backtrader代码：

1. 优化器作为独立模块，通过`backtrader.optimizers`导入
2. 现有`cerebro.optstrategy`继续工作
3. 新的优化框架提供更多算法和功能
4. 用户可按需选择使用哪种优化方式

---

## 七、与现有功能对比

| 功能 | cerebro.optstrategy | 新优化框架 |
|------|---------------------|-----------|
| 网格搜索 | ✅ | ✅ 增强版 |
| 随机搜索 | ❌ | ✅ |
| 贝叶斯优化 | ❌ | ✅ |
| 遗传算法 | ❌ | ✅ |
| 多阶段优化 | ❌ | ✅ |
| 并行执行 | ✅ | ✅ 增强版 |
| 多目标优化 | ❌ | ✅ |
| 约束条件 | ❌ | ✅ |
| 结果分析 | 基础 | ✅ 高级分析 |
| 进度跟踪 | ❌ | ✅ 回调+状态 |
| 参数空间定义 | 简单 | ✅ 灵活定义 |
