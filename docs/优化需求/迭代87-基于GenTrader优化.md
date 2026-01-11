### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/GenTrader
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### GenTrader项目简介
GenTrader是一个使用遗传算法优化交易策略的框架，具有以下核心特点：
- **遗传算法**: 使用遗传算法优化策略
- **参数优化**: 自动参数优化
- **策略进化**: 策略自动进化
- **适应度评估**: 策略适应度评估
- **种群管理**: 策略种群管理
- **交叉变异**: 策略交叉和变异

### 重点借鉴方向
1. **遗传算法**: 遗传算法优化
2. **参数优化**: 自动参数优化
3. **适应度函数**: 适应度函数设计
4. **种群进化**: 策略进化机制
5. **优化框架**: 优化框架设计
6. **多目标优化**: 多目标优化

---

## 一、项目对比分析

### 1.1 架构设计对比

| 特性 | Backtrader | GenTrader |
|------|-----------|-----------|
| **核心功能** | 回测和交易执行框架 | 基于遗传算法的参数优化器 |
| **优化方式** | Cerebro.optstrategy (网格搜索) | 遗传算法(GA)优化 |
| **优化效率** | 穷举搜索，O(N^k) | 进化搜索，O(G×P) |
| **参数约束** | 手动定义范围 | 约束表达式 + 自动验证 |
| **适应度函数** | 预定义指标 | 自定义evaluate函数 |
| **多数据集** | 单一数据集 | 多数据集加权评估 |
| **保存/加载** | 手动实现 | 自动保存历史记录 |
| **可视化** | matplotlib | 内置进度显示和绘图 |

### 1.2 GenTrader的核心优势

#### 1.2.1 遗传算法优化器

GenTrader实现了完整的遗传算法优化器：
- **初始化**: 从基础参数集生成初始种群
- **选择**: 选择top_n最优个体作为父代
- **交叉**: 单点交叉产生后代
- **变异**: 正态分布变异
- **精英保留**: 保留最优个体到下一代

**效率对比**：
```
网格搜索: 30×30×30 = 27,000次回测
遗传算法: 5代×10个体 = 50次回测
```

#### 1.2.2 参数约束系统

```python
# 约束表达式
constraints = {
    'rsi_period': [lambda x: x > 0],
    'rsi_low': [lambda x: x < 15]
}
```

**优势**：
- 表达式解析（>、<、>=、<=、==）
- 自动验证
- 防止无效参数

#### 1.2.3 自定义适应度函数

```python
def evaluate(sharpe_ratio, max_drawdown, total_compound_returns, sqn, all_analyzers):
    if max_drawdown == 0:
        return total_compound_returns
    return total_compound_returns / max_drawdown
```

**优势**：
- 完全自定义评估逻辑
- 访问所有backtrader分析器
- 灵活的多目标组合

#### 1.2.4 多数据集加权评估

```python
stock_data:
  - ticker: BTC-USD
    weight: 0.6
  - ticker: ETH-USD
    weight: 0.4
```

**优势**：
- 同时在多个数据集上评估
- 不同数据集不同权重
- 避免过拟合单一市场

#### 1.2.5 保存和加载系统

```python
# 保存到history目录
history/
  └── 2024-01-15 10·30·45/
      ├── run_info.json         # 最佳参数和得分
      ├── config/
      │   ├── optimizer_config.yaml
      │   ├── initial_params.json
      │   └── evaluate.py
```

**优势**：
- 完整记录每次优化运行
- 可从历史参数继续优化
- 配置可重现

#### 1.2.6 相对变异标准差

```python
if relative_std:
    mutation_std = base_mutation_std * abs(param_value)
else:
    mutation_std = base_mutation_std
```

**优势**：
- 大参数允许更大变异
- 小参数保持精细调整
- 提高收敛效率

### 1.3 可借鉴的具体设计

#### 1.3.1 遗传算法优化框架

Backtrader的optstrategy使用网格搜索：
- 可以添加遗传算法作为可选优化器
- 保持API兼容

#### 1.3.2 约束表达式解析

```python
# GenTrader的方式
constraints = [
    "rsi_period > 0",
    "rsi_low < 15"
]
```

#### 1.3.3 多数据集评估

GenTrader可以同时在多个股票上评估：
- 避免过拟合
- 提高策略泛化能力

#### 1.3.4 历史记录管理

每次优化运行保存完整记录：
- 参数、配置、评估函数
- 便于复现和继续优化

---

## 二、需求文档

### 2.1 优化目标

借鉴GenTrader的遗传算法优化能力，增强Backtrader：

1. **遗传算法优化器**: 作为optstrategy的补充
2. **参数约束系统**: 表达式约束和自动验证
3. **自定义适应度函数**: 灵活的评估函数
4. **多数据集评估**: 同时在多个数据集上评估
5. **历史记录管理**: 保存和加载优化记录
6. **优化进度监控**: 实时进度和可视化

### 2.2 详细需求

#### 需求1: 遗传算法优化器

**描述**: 实现遗传算法作为Cerebro的参数优化选项

**功能点**:
- 初始化种群
- 选择操作
- 交叉操作
- 变异操作
- 精英保留

**验收标准**:
- 提供GeneticOptimizer类
- 与现有Cerebro API兼容
- 收敛效率高于网格搜索

#### 需求2: 参数约束系统

**描述**: 支持表达式风格的参数约束

**功能点**:
- 约束表达式解析
- 自动验证
- 约束违反处理

**验收标准**:
- 支持>、<、>=、<=、==运算符
- 自动过滤无效参数
- 约束可配置

#### 需求3: 自定义适应度函数

**描述**: 灵活的适应度(评估)函数

**功能点**:
- 访问所有backtrader分析器
- 自定义评分逻辑
- 多目标组合

**验收标准**:
- 提供默认适应度函数
- 支持自定义函数
- 文档和示例

#### 需求4: 多数据集评估

**描述**: 同时在多个数据集上评估参数

**功能点**:
- 多数据集并行评估
- 加权评分
- 数据集特定配置

**验收标准**:
- 支持多个数据源
- 可配置权重
- 进度显示

#### 需求5: 历史记录管理

**描述**: 保存和加载优化历史

**功能点**:
- 自动保存优化记录
- 从历史参数继续优化
- 配置版本管理

**验收标准**:
- 完整保存每次运行
- 可加载历史参数
- 配置可重现

#### 需求6: 优化进度监控

**描述**: 实时显示优化进度

**功能点**:
- 进度百分比
- 当前最优参数
- 收敛曲线

**验收标准**:
- 实时进度显示
- 最优参数实时更新
- 支持日志记录

---

## 三、设计文档

### 3.1 遗传算法优化器设计

#### 3.1.1 遗传算法核心类

```python
import backtrader as bt
import numpy as np
import heapq
from typing import Dict, List, Callable, Tuple, Optional, Any
from dataclasses import dataclass
import json
from datetime import datetime
import os

@dataclass
class GAConfig:
    """遗传算法配置"""
    generation_count: int = 5      # 代数
    population: int = 10            # 种群大小
    selected: int = 3               # 选择的个体数
    crossover_rate: float = 0.6     # 交叉概率
    mutation_std: float = 0.1       # 变异标准差
    relative_std: bool = True       # 相对标准差
    elite_size: int = 1             # 精英保留数量
    seed: Optional[int] = None      # 随机种子

@dataclass
class Individual:
    """个体（参数集）"""
    params: Dict[str, Any]
    fitness: float = 0.0

    def __hash__(self):
        return hash(tuple(sorted(self.params.items())))

class GeneticOptimizer:
    """遗传算法参数优化器

    使用遗传算法优化Backtrader策略参数
    """

    def __init__(
        self,
        strategy_class: type,
        data_feeds: List[bt.feed.FeedBase],
        config: GAConfig,
        fitness_func: Optional[Callable] = None,
        constraints: Optional[Dict[str, List[Callable]]] = None,
        cash: float = 100000.0,
        commission: float = 0.001,
    ):
        """初始化优化器

        Args:
            strategy_class: 策略类
            data_feeds: 数据源列表（支持多数据集）
            config: 遗传算法配置
            fitness_func: 适应度函数
            constraints: 参数约束
            cash: 初始资金
            commission: 手续费率
        """
        self.strategy_class = strategy_class
        self.data_feeds = data_feeds
        self.config = config
        self.fitness_func = fitness_func or self._default_fitness
        self.constraints = constraints or {}
        self.cash = cash
        self.commission = commission

        # 设置随机种子
        if config.seed is not None:
            np.random.seed(config.seed)

        # 历史记录
        self.history: List[Dict] = []
        self.best_individual: Optional[Individual] = None

    def _default_fitness(
        self,
        sharpe_ratio: float,
        max_drawdown: float,
        total_returns: float,
        sqn: float,
        analyzers: Dict,
    ) -> float:
        """默认适应度函数

        Args:
            sharpe_ratio: 夏普比率
            max_drawdown: 最大回撤
            total_returns: 总收益
            sqn: 系统质量数
            analyzers: 所有分析器

        Returns:
            适应度值
        """
        if max_drawdown == 0:
            return total_returns
        return total_returns / abs(max_drawdown)

    def _evaluate_individual(self, individual: Individual) -> float:
        """评估单个个体

        Args:
            individual: 要评估的个体

        Returns:
            适应度值
        """
        fitness_values = []

        for data_feed in self.data_feeds:
            cerebro = bt.Cerebro()

            # 添加数据
            cerebro.adddata(data_feed)

            # 添加策略
            cerebro.addstrategy(self.strategy_class, **individual.params)

            # 设置经纪商
            cerebro.broker.setcash(self.cash)
            cerebro.broker.setcommission(commission=self.commission)

            # 添加分析器
            cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
            cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
            cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')

            # 运行
            try:
                strats = cerebro.run()
                strat = strats[0]

                # 提取指标
                sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0)
                dd = strat.analyzers.drawdown.get_analysis()
                max_dd = dd['max']['drawdown'] if dd else 0
                returns = strat.analyzers.returns.get_analysis().get('rtot', 0)
                sqn = strat.analyzers.sqn.get_analysis().get('sqn', 0)

                # 计算适应度
                fitness = self.fitness_func(
                    sharpe_ratio=sharpe,
                    max_drawdown=max_dd,
                    total_returns=returns,
                    sqn=sqn,
                    analyzers=strat.analyzers
                )

                fitness_values.append(fitness)

            except Exception as e:
                # 如果回测失败，给予最低适应度
                fitness_values.append(float('-inf'))

        # 平均适应度（多数据集）
        return np.mean(fitness_values)

    def _check_constraints(self, params: Dict[str, Any]) -> bool:
        """检查参数是否满足约束

        Args:
            params: 参数字典

        Returns:
            True表示满足所有约束
        """
        for param_name, param_value in params.items():
            if param_name in self.constraints:
                for constraint in self.constraints[param_name]:
                    if not constraint(param_value):
                        return False
        return True

    def _mutate(self, individual: Individual) -> Individual:
        """变异操作

        Args:
            individual: 要变异的个体

        Returns:
            变异后的新个体
        """
        new_params = individual.params.copy()

        for param_name, param_value in new_params.items():
            # 计算变异标准差
            if self.config.relative_std:
                std = self.config.mutation_std * abs(param_value)
            else:
                std = self.config.mutation_std

            # 生成新值
            if isinstance(param_value, int):
                new_value = int(np.round(np.random.normal(param_value, std)))
            else:
                new_value = np.random.normal(param_value, std)

            new_params[param_name] = new_value

        new_individual = Individual(params=new_params)

        # 检查约束
        if not self._check_constraints(new_params):
            return individual  # 约束不满足，返回原个体

        return new_individual

    def _crossover(
        self,
        parent1: Individual,
        parent2: Individual
    ) -> Tuple[Individual, Individual]:
        """交叉操作

        Args:
            parent1: 父代1
            parent2: 父代2

        Returns:
            子代1, 子代2
        """
        # 按概率决定是否交叉
        if np.random.random() >= self.config.crossover_rate:
            return parent1, parent2

        # 单点交叉
        params_list = list(parent1.params.keys())
        if len(params_list) < 2:
            return parent1, parent2

        crossover_point = np.random.randint(1, len(params_list))

        # 创建子代
        child1_params = {}
        child2_params = {}

        for i, key in enumerate(params_list):
            if i < crossover_point:
                child1_params[key] = parent1.params[key]
                child2_params[key] = parent2.params[key]
            else:
                child1_params[key] = parent2.params[key]
                child2_params[key] = parent1.params[key]

        child1 = Individual(params=child1_params)
        child2 = Individual(params=child2_params)

        return child1, child2

    def _init_population(self, base_params: Dict[str, Any]) -> List[Individual]:
        """初始化种群

        Args:
            base_params: 基础参数

        Returns:
            初始种群
        """
        population = []

        # 第一个个体是基础参数
        population.append(Individual(params=base_params.copy()))

        # 其余个体通过变异生成
        for _ in range(self.config.population - 1):
            mutated_params = base_params.copy()

            for param_name, param_value in mutated_params.items():
                # 初始变异使用更大的标准差
                if self.config.relative_std:
                    std = self.config.mutation_std * 2 * abs(param_value)
                else:
                    std = self.config.mutation_std * 2

                if isinstance(param_value, int):
                    mutated_params[param_name] = int(np.round(np.random.normal(param_value, std)))
                else:
                    mutated_params[param_name] = np.random.normal(param_value, std)

            individual = Individual(params=mutated_params)
            if self._check_constraints(mutated_params):
                population.append(individual)

        return population

    def _select_top(self, population: List[Individual]) -> List[Individual]:
        """选择最优个体

        Args:
            population: 当前种群

        Returns:
            最优的selected个个体
        """
        # 先评估所有个体
        for individual in population:
            if individual.fitness == 0:
                individual.fitness = self._evaluate_individual(individual)

        # 返回最优的几个
        return heapq.nlargest(self.config.selected, population, key=lambda x: x.fitness)

    def _generate_next_generation(self, top_individuals: List[Individual]) -> List[Individual]:
        """生成下一代

        Args:
            top_individuals: 上一代的最优个体

        Returns:
            新一代种群
        """
        new_population = []

        # 精英保留
        for i in range(self.config.elite_size):
            new_population.append(top_individuals[i])

        # 生成剩余个体
        while len(new_population) < self.config.population:
            # 选择父代
            parent1 = top_individuals[np.random.randint(0, len(top_individuals))]
            parent2 = top_individuals[np.random.randint(0, len(top_individuals))]

            # 交叉
            child1, child2 = self._crossover(parent1, parent2)

            # 变异
            child1 = self._mutate(child1)
            child2 = self._mutate(child2)

            new_population.append(child1)
            if len(new_population) < self.config.population:
                new_population.append(child2)

        return new_population

    def optimize(self, base_params: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
        """执行优化

        Args:
            base_params: 基础参数

        Returns:
            (最优参数, 最优适应度)
        """
        print(f"=== 遗传算法优化 ===")
        print(f"基础参数: {base_params}")
        print(f"配置: 代数={self.config.generation_count}, "
              f"种群={self.config.population}, "
              f"选择={self.config.selected}")

        # 初始化种群
        population = self._init_population(base_params)

        # 进化循环
        for generation in range(self.config.generation_count):
            print(f"\n--- 第{generation + 1}代 ---")

            # 选择
            top_individuals = self._select_top(population)

            # 记录最优
            best = top_individuals[0]
            print(f"最优适应度: {best.fitness:.6f}")
            print(f"最优参数: {best.params}")

            # 更新全局最优
            if self.best_individual is None or best.fitness > self.best_individual.fitness:
                self.best_individual = best

            # 记录历史
            self.history.append({
                'generation': generation + 1,
                'best_fitness': best.fitness,
                'best_params': best.params,
                'avg_fitness': np.mean([ind.fitness for ind in top_individuals])
            })

            # 生成下一代
            if generation < self.config.generation_count - 1:
                population = self._generate_next_generation(top_individuals)

        print(f"\n=== 优化完成 ===")
        print(f"全局最优适应度: {self.best_individual.fitness:.6f}")
        print(f"全局最优参数: {self.best_individual.params}")

        return self.best_individual.params, self.best_individual.fitness

    def save_history(self, path: str):
        """保存优化历史

        Args:
            path: 保存路径
        """
        # 创建目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = os.path.join(path, f"run_{timestamp}")
        os.makedirs(run_dir, exist_ok=True)

        # 保存历史
        history_data = {
            'config': {
                'generation_count': self.config.generation_count,
                'population': self.config.population,
                'selected': self.config.selected,
                'crossover_rate': self.config.crossover_rate,
                'mutation_std': self.config.mutation_std,
                'relative_std': self.config.relative_std,
                'seed': self.config.seed,
            },
            'best_params': self.best_individual.params,
            'best_fitness': float(self.best_individual.fitness),
            'history': self.history
        }

        with open(os.path.join(run_dir, 'results.json'), 'w') as f:
            json.dump(history_data, f, indent=2)

        print(f"历史记录已保存到: {run_dir}")

    @staticmethod
    def load_history(path: str) -> Dict:
        """加载优化历史

        Args:
            path: 结果文件路径

        Returns:
            历史数据字典
        """
        with open(path, 'r') as f:
            return json.load(f)
```

#### 3.1.2 约束解析器

```python
from typing import Dict, List, Callable

class ConstraintParser:
    """约束表达式解析器

    将字符串约束转换为可调用函数
    """

    OPERATORS = {
        '>': lambda x, v: x > v,
        '<': lambda x, v: x < v,
        '>=': lambda x, v: x >= v,
        '<=': lambda x, v: x <= v,
        '==': lambda x, v: abs(x - v) < 1e-9,  # 浮点数相等
    }

    @classmethod
    def parse(cls, constraint_strs: List[str]) -> Dict[str, List[Callable]]:
        """解析约束表达式

        Args:
            constraint_strs: 约束字符串列表，如 ["param > 0", "param < 100"]

        Returns:
            约束字典 {param_name: [constraint_func, ...]}
        """
        constraints: Dict[str, List[Callable]] = {}

        for expr in constraint_strs:
            parts = expr.strip().split()
            if len(parts) != 3:
                raise ValueError(f"无效的约束表达式: {expr}")

            param, op, value = parts

            try:
                value = float(value)
            except ValueError:
                raise ValueError(f"无效的约束值: {value}")

            if op not in cls.OPERATORS:
                raise ValueError(f"无效的运算符: {op}")

            constraint_func = cls.OPERATORS[op]

            # 部分应用，固定值
            from functools import partial
            func = partial(constraint_func, v=value)

            if param not in constraints:
                constraints[param] = []
            constraints[param].append(func)

        return constraints

# 使用示例
constraints = ConstraintParser.parse([
    "rsi_period > 0",
    "rsi_period < 50",
    "rsi_low < 30",
    "rsi_high > 50"
])
```

#### 3.1.3 Cerebro集成

```python
class CerebroWithGA(bt.Cerebro):
    """支持遗传算法优化的Cerebro

    扩展Cerebro，添加遗传优化方法
    """

    def optgenetic(
        self,
        strategy: type,
        ga_config: GAConfig,
        fitness_func: Optional[Callable] = None,
        constraints: Optional[List[str]] = None,
        save_path: Optional[str] = "./ga_history"
    ) -> Tuple[Dict[str, Any], float]:
        """使用遗传算法优化策略参数

        Args:
            strategy: 策略类
            ga_config: 遗传算法配置
            fitness_func: 适应度函数
            constraints: 约束表达式列表
            save_path: 历史记录保存路径

        Returns:
            (最优参数, 最优适应度)
        """
        # 获取默认参数
        base_params = {}
        for key, value in strategy.params._getitems():
            if isinstance(value, (int, float)):
                base_params[key] = value

        # 解析约束
        constraint_funcs = None
        if constraints:
            constraint_funcs = ConstraintParser.parse(constraints)

        # 创建优化器
        optimizer = GeneticOptimizer(
            strategy_class=strategy,
            data_feeds=[self.datas[x] for x in range(len(self.datas))],
            config=ga_config,
            fitness_func=fitness_func,
            constraints=constraint_funcs,
        )

        # 执行优化
        best_params, best_fitness = optimizer.optimize(base_params)

        # 保存历史
        if save_path:
            optimizer.save_history(save_path)

        return best_params, best_fitness

# 使用示例
cerebro = CerebroWithGA()
cerebro.adddata(data)

ga_config = GAConfig(
    generation_count=5,
    population=10,
    selected=3
)

constraints = [
    "rsi_period > 5",
    "rsi_period < 30",
    "rsi_low < 40",
    "rsi_high > 60"
]

best_params, fitness = cerebro.optgenetic(
    strategy=MyStrategy,
    ga_config=ga_config,
    constraints=constraints
)
```

### 3.2 多数据集加权评估设计

```python
@dataclass
class DataSet:
    """数据集配置"""
    feed: bt.feed.FeedBase
    weight: float = 1.0
    cash: float = 100000.0
    commission: float = 0.001

class MultiDataSetOptimizer(GeneticOptimizer):
    """多数据集优化器

    同时在多个数据集上评估策略参数
    """

    def __init__(
        self,
        strategy_class: type,
        datasets: List[DataSet],
        config: GAConfig,
        fitness_func: Optional[Callable] = None,
        constraints: Optional[Dict[str, List[Callable]]] = None,
    ):
        """初始化多数据集优化器

        Args:
            strategy_class: 策略类
            datasets: 数据集配置列表
            config: 遗传算法配置
            fitness_func: 适应度函数
            constraints: 参数约束
        """
        self.datasets = datasets
        self.strategy_class = strategy_class
        self.config = config
        self.fitness_func = fitness_func
        self.constraints = constraints or {}

        # 设置随机种子
        if config.seed is not None:
            np.random.seed(config.seed)

        self.history: List[Dict] = []
        self.best_individual: Optional[Individual] = None

    def _evaluate_individual(self, individual: Individual) -> float:
        """评估单个个体（多数据集加权）"""
        fitness_values = []
        weights = []

        for dataset in self.datasets:
            cerebro = bt.Cerebro()
            cerebro.adddata(dataset.feed)
            cerebro.addstrategy(self.strategy_class, **individual.params)
            cerebro.broker.setcash(dataset.cash)
            cerebro.broker.setcommission(commission=dataset.commission)

            # 添加分析器
            cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
            cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
            cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')

            try:
                strats = cerebro.run()
                strat = strats[0]

                sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0)
                dd = strat.analyzers.drawdown.get_analysis()
                max_dd = dd['max']['drawdown'] if dd else 0
                returns = strat.analyzers.returns.get_analysis().get('rtot', 0)
                sqn = strat.analyzers.sqn.get_analysis().get('sqn', 0)

                fitness = self.fitness_func(
                    sharpe_ratio=sharpe,
                    max_drawdown=max_dd,
                    total_returns=returns,
                    sqn=sqn,
                    analyzers=strat.analyzers
                )

                fitness_values.append(fitness)
                weights.append(dataset.weight)

            except Exception as e:
                fitness_values.append(float('-inf'))
                weights.append(dataset.weight)

        # 加权平均
        total_weight = sum(weights)
        if total_weight > 0:
            return sum(f * w for f, w in zip(fitness_values, weights)) / total_weight
        return 0

# 使用示例
datasets = [
    DataSet(
        feed=bt.feeds.YahooFinanceData(dataname='AAPL', fromdate='2020-01-01'),
        weight=0.4
    ),
    DataSet(
        feed=bt.feeds.YahooFinanceData(dataname='MSFT', fromdate='2020-01-01'),
        weight=0.3
    ),
    DataSet(
        feed=bt.feeds.YahooFinanceData(dataname='GOOGL', fromdate='2020-01-01'),
        weight=0.3
    ),
]

optimizer = MultiDataSetOptimizer(
    strategy_class=MyStrategy,
    datasets=datasets,
    config=GAConfig(generation_count=5, population=10)
)
```

### 3.3 预定义适应度函数库

```python
from typing import Dict, Callable

class FitnessFunctions:
    """预定义的适应度函数库"""

    @staticmethod
    def sharpe_ratio(
        sharpe_ratio: float,
        max_drawdown: float,
        total_returns: float,
        sqn: float,
        analyzers: Dict
    ) -> float:
        """仅使用夏普比率"""
        return sharpe_ratio if sharpe_ratio is not None else float('-inf')

    @staticmethod
    def returns_to_drawdown(
        sharpe_ratio: float,
        max_drawdown: float,
        total_returns: float,
        sqn: float,
        analyzers: Dict
    ) -> float:
        """收益/回撤比率"""
        if max_drawdown == 0:
            return total_returns
        return total_returns / abs(max_drawdown)

    @staticmethod
    def sharpe_with_penalty(
        sharpe_ratio: float,
        max_drawdown: float,
        total_returns: float,
        sqn: float,
        analyzers: Dict
    ) -> float:
        """带回撤惩罚的夏普比率"""
        if sharpe_ratio is None:
            return float('-inf')

        # 回撤惩罚
        penalty = 0
        if max_drawdown < -0.1:  # 回撤超过10%
            penalty = abs(max_drawdown) * 2

        return sharpe_ratio - penalty

    @staticmethod
    def sqn_based(
        sharpe_ratio: float,
        max_drawdown: float,
        total_returns: float,
        sqn: float,
        analyzers: Dict
    ) -> float:
        """基于SQN的评估"""
        return sqn if sqn is not None else float('-inf')

    @staticmethod
    def weighted_multi(
        sharpe_ratio: float,
        max_drawdown: float,
        total_returns: float,
        sqn: float,
        analyzers: Dict,
        sharpe_weight: float = 0.4,
        returns_weight: float = 0.3,
        sqn_weight: float = 0.3
    ) -> float:
        """加权多目标"""
        score = 0

        if sharpe_ratio is not None:
            score += sharpe_ratio * sharpe_weight

        if max_drawdown != 0:
            score += (total_returns / abs(max_drawdown)) * returns_weight
        else:
            score += total_returns * returns_weight

        if sqn is not None:
            score += sqn * sqn_weight

        return score

    @staticmethod
    def custom(weights: Dict[str, float] = None) -> Callable:
        """自定义权重适应度函数

        Args:
            weights: 各指标的权重字典

        Returns:
            适应度函数
        """
        default_weights = {
            'sharpe': 0.3,
            'returns/dd': 0.3,
            'sqn': 0.2,
            'total_returns': 0.2
        }
        weights = weights or default_weights

        def fitness_func(
            sharpe_ratio: float,
            max_drawdown: float,
            total_returns: float,
            sqn: float,
            analyzers: Dict
        ) -> float:
            score = 0

            if 'sharpe' in weights and sharpe_ratio is not None:
                score += sharpe_ratio * weights['sharpe']

            if 'returns/dd' in weights:
                if max_drawdown != 0:
                    score += (total_returns / abs(max_drawdown)) * weights['returns/dd']
                else:
                    score += total_returns * weights['returns/dd']

            if 'sqn' in weights and sqn is not None:
                score += sqn * weights['sqn']

            if 'total_returns' in weights:
                score += total_returns * weights['total_returns']

            return score

        return fitness_func
```

### 3.4 优化进度监控设计

```python
from abc import ABC, abstractmethod
from typing import Optional
import time

class ProgressMonitor(ABC):
    """进度监控抽象基类"""

    @abstractmethod
    def on_generation_start(self, generation: int, total: int):
        """代开始"""
        pass

    @abstractmethod
    def on_generation_end(
        self,
        generation: int,
        best_fitness: float,
        best_params: Dict,
        avg_fitness: float
    ):
        """代结束"""
        pass

    @abstractmethod
    def on_evaluation(self, completed: int, total: int):
        """单个评估完成"""
        pass

class ConsoleProgressMonitor(ProgressMonitor):
    """控制台进度监控"""

    def __init__(self):
        self.start_time = None
        self.last_update = None

    def on_generation_start(self, generation: int, total: int):
        self.start_time = time.time()
        print(f"\n{'='*50}")
        print(f"第 {generation}/{total} 代开始")

    def on_generation_end(
        self,
        generation: int,
        best_fitness: float,
        best_params: Dict,
        avg_fitness: float
    ):
        elapsed = time.time() - self.start_time
        print(f"最优适应度: {best_fitness:.6f}")
        print(f"平均适应度: {avg_fitness:.6f}")
        print(f"耗时: {elapsed:.2f}秒")

    def on_evaluation(self, completed: int, total: int):
        # 每10%更新一次
        if completed % max(1, total // 10) == 0 or completed == total:
            print(f"\r  进度: {completed}/{total} ({completed/total*100:.0f}%)", end='')
```

### 3.5 实现优先级

| 优先级 | 功能 | 复杂度 | 收益 |
|--------|------|--------|------|
| P0 | GeneticOptimizer核心类 | 高 | 高 |
| P0 | 约束解析器 | 低 | 中 |
| P1 | 预定义适应度函数 | 低 | 中 |
| P1 | Cerebro集成 | 中 | 高 |
| P2 | 多数据集评估 | 中 | 中 |
| P2 | 进度监控 | 低 | 低 |

### 3.6 兼容性保证

所有新功能通过以下方式保证兼容性：
1. 新增类不修改现有Cerebro API
2. optstrategy继续工作
3. 遗传算法作为可选优化方式
4. 约束系统向后兼容

---

## 四、使用示例

### 4.1 基础使用

```python
import backtrader as bt
from backtrader.optimizers import (
    GeneticOptimizer,
    GAConfig,
    ConstraintParser,
    FitnessFunctions
)

# 定义策略
class MyStrategy(bt.Strategy):
    params = (
        ('rsi_period', 14),
        ('rsi_low', 30),
        ('rsi_high', 70),
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

    def next(self):
        if self.rsi < self.p.rsi_low:
            self.buy()
        elif self.rsi > self.p.rsi_high:
            self.sell()

# 创建数据
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 1, 1)
)

# 配置遗传算法
ga_config = GAConfig(
    generation_count=10,
    population=20,
    selected=5,
    crossover_rate=0.7,
    mutation_std=0.15,
    relative_std=True
)

# 配置约束
constraints = [
    "rsi_period > 5",
    "rsi_period < 30",
    "rsi_low < 40",
    "rsi_high > 50"
]

# 创建并运行优化器
optimizer = GeneticOptimizer(
    strategy_class=MyStrategy,
    data_feeds=[data],
    config=ga_config,
    fitness_func=FitnessFunctions.returns_to_drawdown,
    constraints=ConstraintParser.parse(constraints)
)

# 执行优化
base_params = {'rsi_period': 14, 'rsi_low': 30, 'rsi_high': 70}
best_params, best_fitness = optimizer.optimize(base_params)

print(f"最优参数: {best_params}")
print(f"最优适应度: {best_fitness}")

# 保存结果
optimizer.save_history('./ga_results')
```

### 4.2 使用Cerebro集成

```python
from backtrader.optimizers import CerebroWithGA, GAConfig

cerebro = CerebroWithGA()
cerebro.adddata(data)

# 遗传算法优化
best_params, fitness = cerebro.optgenetic(
    strategy=MyStrategy,
    ga_config=GAConfig(
        generation_count=5,
        population=10,
        selected=3
    ),
    constraints=[
        "rsi_period > 5",
        "rsi_period < 30"
    ]
)

# 使用最优参数运行
cerebro.addstrategy(MyStrategy, **best_params)
result = cerebro.run()
```

### 4.3 多数据集优化

```python
from backtrader.optimizers import MultiDataSetOptimizer, DataSet, GAConfig

# 多数据集配置
datasets = [
    DataSet(
        feed=bt.feeds.YahooFinanceData(dataname='AAPL', fromdate='2020-01-01'),
        weight=0.4
    ),
    DataSet(
        feed=bt.feeds.YahooFinanceData(dataname='MSFT', fromdate='2020-01-01'),
        weight=0.3
    ),
    DataSet(
        feed=bt.feeds.YahooFinanceData(dataname='SPY', fromdate='2020-01-01'),
        weight=0.3
    ),
]

# 多数据集优化
optimizer = MultiDataSetOptimizer(
    strategy_class=MyStrategy,
    datasets=datasets,
    config=GAConfig(generation_count=10, population=20)
)

best_params, best_fitness = optimizer.optimize({
    'rsi_period': 14,
    'rsi_low': 30,
    'rsi_high': 70
})
```

### 4.4 自定义适应度函数

```python
from backtrader.optimizers import FitnessFunctions

# 使用预定义
fitness_func = FitnessFunctions.weighted_multi(
    weights={'sharpe': 0.5, 'returns/dd': 0.3, 'sqn': 0.2}
)

# 或完全自定义
def my_fitness(sharpe_ratio, max_drawdown, total_returns, sqn, analyzers):
    # 访问所有分析器
    trades = analyzers.tradeanalyzer.get_analysis()
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)

    if won + lost == 0:
        return 0

    win_rate = won / (won + lost)

    # 组合多个指标
    score = (
        sharpe_ratio * 0.4 +
        win_rate * 0.3 +
        total_returns * 0.3
    )

    return score

optimizer = GeneticOptimizer(
    strategy_class=MyStrategy,
    data_feeds=[data],
    config=ga_config,
    fitness_func=my_fitness
)
```

---

## 五、总结

通过借鉴GenTrader的优秀设计，Backtrader可以获得：

1. **高效的参数优化**: 遗传算法比网格搜索快100-1000倍
2. **灵活的约束系统**: 表达式约束，自动验证
3. **可扩展的适应度函数**: 完全自定义的评估逻辑
4. **多数据集支持**: 同时在多个市场评估，避免过拟合
5. **完整的历史记录**: 保存、加载、复现优化过程
6. **易于使用的API**: 与现有Cerebro无缝集成

这些改进将使Backtrader的参数优化能力达到新的水平，大大提高策略开发效率。
