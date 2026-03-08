# Parameter Optimization Guide

This guide explains how to use Backtrader for strategy parameter optimization to find the best trading parameters.

## Optimization Basics

### Parameter Definition

```python
class MyStrategy(bt.Strategy):
    params = (
        ('fast_period', 10),    # Fast MA period
        ('slow_period', 30),    # Slow MA period
        ('rsi_period', 14),     # RSI period
        ('risk_ratio', 0.02),   # Risk ratio
    )

```

### Running Optimization

```python
cerebro = bt.Cerebro(optreturn=False)  # Set optimization mode

# Add strategy with parameter ranges

cerebro.optstrategy(
    MyStrategy,
    fast_period=range(5, 20, 5),
    slow_period=range(20, 40, 5),
    rsi_period=[7, 14, 21],
    risk_ratio=[0.01, 0.02, 0.03]
)

```

## Optimization Methods

### 1. Grid Search

```python

# Define parameter grid

params_grid = {
    'fast_period': range(5, 20, 5),
    'slow_period': range(20, 40, 5),
    'rsi_period': [7, 14, 21],
}

# Execute grid search

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

### 2. Genetic Algorithm Optimization

```python
from deap import base, creator, tools, algorithms

# Define fitness function

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

# Set up genetic algorithm

creator.create("FitnessMax", base.Fitness, weights=(1.0,))
creator.create("Individual", list, fitness=creator.FitnessMax)

toolbox = base.Toolbox()
toolbox.register("attr_fast", random.randint, 5, 20)
toolbox.register("attr_slow", random.randint, 20, 40)
toolbox.register("attr_rsi", random.choice, [7, 14, 21])

```

### 3. Bayesian Optimization

```python
from skopt import gp_minimize

# Define objective function

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

# Execute Bayesian optimization

res = gp_minimize(
    objective,
    [(5, 20), (20, 40), (7, 21)],
    n_calls=50,
    random_state=1
)

```

## Evaluation Metrics

### 1. Performance Metrics

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

### 2. Stability Assessment

```python
def stability_score(results):

# Calculate parameter sensitivity
    returns = [r['returns'] for r in results]
    std = np.std(returns)
    mean = np.mean(returns)
    return mean / std if std != 0 else float('inf')

```

### 3. Overfitting Detection

```python
def detect_overfitting(results, train_data, test_data):

# Training set performance
    train_performance = evaluate_strategy(results, train_data)

# Test set performance
    test_performance = evaluate_strategy(results, test_data)

# Calculate performance gap
    return abs(train_performance - test_performance)

```

## Optimization Strategies

### 1. Rolling Window Optimization

```python
def time_window_optimization(strategy_class, data, window_size):
    results = []
    for i in range(0, len(data) - window_size, window_size):
        window_data = data[i:i+window_size]

# Optimize on each time window
        window_results = optimize_strategy(strategy_class, window_data)
        results.append(window_results)
    return analyze_window_results(results)

```

### 2. Staged Optimization

```python
def staged_optimization(strategy_class, data):

# Stage 1: Coarse search
    coarse_results = grid_search(
        strategy_class,
        {
            'fast_period': range(5, 20, 5),
            'slow_period': range(20, 40, 10)
        }
    )

# Stage 2: Fine search
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

### 3. Cross-Validation

```python
def cross_validation(strategy_class, data, n_splits=5):

# Create time series splits
    tscv = TimeSeriesSplit(n_splits=n_splits)

    results = []
    for train_idx, test_idx in tscv.split(data):
        train_data = data.iloc[train_idx]
        test_data = data.iloc[test_idx]

# Optimize on training set
        train_results = optimize_strategy(strategy_class, train_data)

# Validate on test set
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

## Results Analysis

### 1. Performance Evaluation

```python
def analyze_optimization_results(results):

# Calculate metrics
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

# Plot performance distribution
    plt.figure(figsize=(12, 8))
    sns.scatterplot(
        data=performance,
        x='sharpe',
        y='returns',
        size='trades',
        hue='drawdown'
    )
    plt.title('Optimization Results Distribution')
    plt.show()

    return performance

```

### 2. Parameter Sensitivity Analysis

```python
def parameter_sensitivity(results):

# Calculate sensitivity for each parameter
    sensitivity = {}
    for param in results[0][0].keys():
        values = [r[0][param] for r in results]
        returns = [r[1]['returns'] for r in results]

# Compute correlation coefficient
        correlation = np.corrcoef(values, returns)[0, 1]
        sensitivity[param] = correlation

    return sensitivity

```

### 3. Stability Analysis

```python
def stability_analysis(results, window_size=20):

# Calculate rolling performance
    rolling_performance = []
    for i in range(len(results) - window_size):
        window = results[i:i+window_size]
        stability = stability_score(window)
        rolling_performance.append(stability)

# Plot stability trend
    plt.plot(rolling_performance)
    plt.title('Strategy Stability Trend')
    plt.show()

```

## Best Practices

### 1. Avoiding Overfitting

```python
def prevent_overfitting(strategy_class, data):

# Split data
    train_size = int(len(data) * 0.7)
    train_data = data[:train_size]
    test_data = data[train_size:]

# Optimize on training set
    train_results = optimize_strategy(strategy_class, train_data)

# Validate on test set
    test_results = evaluate_strategy(
        strategy_class,
        test_data,
        train_results['best_params']
    )

# Check performance gap
    if detect_overfitting(train_results, test_results) > 0.3:
        print("Warning: possible overfitting detected")

```

### 2. Parameter Constraints

```python
def validate_parameters(params):

# Check parameter validity
    if params['fast_period'] >= params['slow_period']:
        return False

    if params['risk_ratio'] > 0.05:
        return False

    return True

```

### 3. Computational Efficiency

```python
def parallel_optimization(strategy_class, param_grid):

# Use multiprocessing for optimization
    with Pool() as pool:
        results = pool.map(
            partial(evaluate_params, strategy_class),
            param_grid
        )
    return results

```

## Common Issues

1. **Optimization takes too long**
   - Reduce parameter ranges
   - Use parallel computing
   - Adopt staged optimization

1. **Overfitting**
   - Use cross-validation
   - Add out-of-sample testing
   - Reduce number of parameters

1. **Unstable results**
   - Check parameter sensitivity
   - Add optimization constraints
   - Use stability metrics

## Next Steps

- Learn about [Strategy Development](../strategies/strategies.md)
- Explore [Performance Optimization](../../advanced/performance-optimization.md)
- Study [Tutorials](../../tutorials/complete-strategy.md)
