# 参数优化指南

本指南介绍如何使用 Backtrader 进行策略参数优化，以找到最佳的交易参数。

## 优化基础

### 参数定义

```python
class MyStrategy(bt.Strategy):
    params = (
        ('fast_period', 10),    # 快速均线周期
        ('slow_period', 30),    # 慢速均线周期
        ('rsi_period', 14),     # RSI周期
        ('risk_ratio', 0.02),   # 风险比率
    )
```

### 优化执行

```python
cerebro = bt.Cerebro(optreturn=False)  # 设置优化模式

# 添加策略和参数范围
cerebro.optstrategy(
    MyStrategy,
    fast_period=range(5, 20, 5),
    slow_period=range(20, 40, 5),
    rsi_period=[7, 14, 21],
    risk_ratio=[0.01, 0.02, 0.03]
)
```

## 优化方法

### 1. 网格搜索

```python
# 定义参数网格
params_grid = {
    'fast_period': range(5, 20, 5),
    'slow_period': range(20, 40, 5),
    'rsi_period': [7, 14, 21],
}

# 执行网格搜索
results = []
for fast in params_grid['fast_period']:
    for slow in params_grid['slow_period']:
        for rsi in params_grid['rsi_period']:
            cerebro.optstrategy(
                MyStrategy,
                fast_period=fast,
                slow_period=slow,
                rsi_period=rsi
            )
            result = cerebro.run()
            results.append((fast, slow, rsi, result[0].analyzers.returns.get_analysis()))
```

### 2. 遗传算法优化

```python
from deap import base, creator, tools, algorithms

# 定义适应度函数
def evaluate(individual):
    cerebro = bt.Cerebro()
    cerebro.addstrategy(
        MyStrategy,
        fast_period=individual[0],
        slow_period=individual[1],
        rsi_period=individual[2]
    )
    results = cerebro.run()
    return results[0].analyzers.returns.get_analysis()['sharpe'],

# 设置遗传算法
creator.create("FitnessMax", base.Fitness, weights=(1.0,))
creator.create("Individual", list, fitness=creator.FitnessMax)

toolbox = base.Toolbox()
toolbox.register("attr_fast", random.randint, 5, 20)
toolbox.register("attr_slow", random.randint, 20, 40)
toolbox.register("attr_rsi", random.choice, [7, 14, 21])
```

### 3. 贝叶斯优化

```python
from skopt import gp_minimize

# 定义目标函数
def objective(params):
    fast, slow, rsi = params
    cerebro = bt.Cerebro()
    cerebro.addstrategy(
        MyStrategy,
        fast_period=fast,
        slow_period=slow,
        rsi_period=rsi
    )
    results = cerebro.run()
    return -results[0].analyzers.returns.get_analysis()['sharpe']

# 执行贝叶斯优化
res = gp_minimize(
    objective,
    [(5, 20), (20, 40), (7, 21)],
    n_calls=50,
    random_state=1
)
```

## 评估指标

### 1. 性能指标

```python
class OptimizationAnalyzer(bt.Analyzer):
    def get_analysis(self):
        return {
            'sharpe': self.strategy.analyzers.sharpe.get_analysis()['sharperatio'],
            'drawdown': self.strategy.analyzers.drawdown.get_analysis()['max']['drawdown'],
            'returns': self.strategy.analyzers.returns.get_analysis()['rtot'],
            'trades': len(self.strategy.analyzers.trades.get_analysis())
        }
```

### 2. 稳定性评估

```python
def stability_score(results):
    # 计算参数敏感度
    returns = [r['returns'] for r in results]
    std = np.std(returns)
    mean = np.mean(returns)
    return mean / std if std != 0 else float('inf')
```

### 3. 过拟合检测

```python
def detect_overfitting(results, train_data, test_data):
    # 训练集性能
    train_performance = evaluate_strategy(results, train_data)
    # 测试集性能
    test_performance = evaluate_strategy(results, test_data)
    # 计算性能差异
    return abs(train_performance - test_performance)
```

## 优化策略

### 1. 时间窗口优化

```python
def time_window_optimization(strategy_class, data, window_size):
    results = []
    for i in range(0, len(data) - window_size, window_size):
        window_data = data[i:i+window_size]
        # 在每个时间窗口上优化
        window_results = optimize_strategy(strategy_class, window_data)
        results.append(window_results)
    return analyze_window_results(results)
```

### 2. 分步优化

```python
def staged_optimization(strategy_class, data):
    # 第一阶段：粗略搜索
    coarse_results = grid_search(
        strategy_class,
        {
            'fast_period': range(5, 20, 5),
            'slow_period': range(20, 40, 10)
        }
    )
    
    # 第二阶段：精细搜索
    best_params = get_best_params(coarse_results)
    fine_results = grid_search(
        strategy_class,
        {
            'fast_period': range(
                best_params['fast_period']-2,
                best_params['fast_period']+3
            ),
            'slow_period': range(
                best_params['slow_period']-5,
                best_params['slow_period']+6
            )
        }
    )
    return fine_results
```

### 3. 交叉验证

```python
def cross_validation(strategy_class, data, n_splits=5):
    # 创建时间序列分割
    tscv = TimeSeriesSplit(n_splits=n_splits)
    
    results = []
    for train_idx, test_idx in tscv.split(data):
        train_data = data.iloc[train_idx]
        test_data = data.iloc[test_idx]
        
        # 在训练集上优化
        train_results = optimize_strategy(strategy_class, train_data)
        
        # 在测试集上验证
        test_results = evaluate_strategy(
            strategy_class,
            test_data,
            train_results['best_params']
        )
        
        results.append({
            'train': train_results,
            'test': test_results
        })
    
    return analyze_cv_results(results)
```

## 结果分析

### 1. 性能评估

```python
def analyze_optimization_results(results):
    # 计算各项指标
    performance = pd.DataFrame([
        {
            'params': r[0],
            'sharpe': r[1]['sharpe'],
            'returns': r[1]['returns'],
            'drawdown': r[1]['drawdown'],
            'trades': r[1]['trades']
        }
        for r in results
    ])
    
    # 绘制性能分布
    plt.figure(figsize=(12, 8))
    sns.scatterplot(
        data=performance,
        x='sharpe',
        y='returns',
        size='trades',
        hue='drawdown'
    )
    plt.title('参数优化结果分布')
    plt.show()
    
    return performance
```

### 2. 参数敏感度分析

```python
def parameter_sensitivity(results):
    # 计算每个参数的敏感度
    sensitivity = {}
    for param in results[0][0].keys():
        values = [r[0][param] for r in results]
        returns = [r[1]['returns'] for r in results]
        
        # 计算相关系数
        correlation = np.corrcoef(values, returns)[0, 1]
        sensitivity[param] = correlation
    
    return sensitivity
```

### 3. 稳定性分析

```python
def stability_analysis(results, window_size=20):
    # 计算滚动性能
    rolling_performance = []
    for i in range(len(results) - window_size):
        window = results[i:i+window_size]
        stability = stability_score(window)
        rolling_performance.append(stability)
    
    # 绘制稳定性趋势
    plt.plot(rolling_performance)
    plt.title('策略稳定性趋势')
    plt.show()
```

## 最佳实践

### 1. 避免过拟合

```python
def prevent_overfitting(strategy_class, data):
    # 分割数据
    train_size = int(len(data) * 0.7)
    train_data = data[:train_size]
    test_data = data[train_size:]
    
    # 在训练集上优化
    train_results = optimize_strategy(strategy_class, train_data)
    
    # 在测试集上验证
    test_results = evaluate_strategy(
        strategy_class,
        test_data,
        train_results['best_params']
    )
    
    # 检查性能差异
    if detect_overfitting(train_results, test_results) > 0.3:
        print("警告：可能存在过拟合")
```

### 2. 参数约束

```python
def validate_parameters(params):
    # 检查参数是否合理
    if params['fast_period'] >= params['slow_period']:
        return False
    
    if params['risk_ratio'] > 0.05:
        return False
    
    return True
```

### 3. 计算效率

```python
def parallel_optimization(strategy_class, param_grid):
    # 使用多进程优化
    with Pool() as pool:
        results = pool.map(
            partial(evaluate_params, strategy_class),
            param_grid
        )
    return results
```

## 常见问题

1. **优化时间过长**
   - 减少参数范围
   - 使用并行计算
   - 采用分步优化

2. **过拟合问题**
   - 使用交叉验证
   - 增加样本外测试
   - 减少参数数量

3. **结果不稳定**
   - 检查参数敏感度
   - 增加优化约束
   - 使用稳定性指标

## 下一步

- 学习[策略开发](./strategies.md)
- 了解[风险管理](../advanced/risk_mgmt.md)
- 探索[实盘交易](../advanced/live_trading.md)
- 研究[机器学习](../advanced/machine_learning.md)
