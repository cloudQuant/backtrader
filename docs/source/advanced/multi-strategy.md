- --

title: Multi-Strategy Backtesting
description: Guide for running and managing multiple strategies in backtrader

- --

# Multi-Strategy Backtesting

Running multiple strategies simultaneously allows you to diversify your approach, compare performance, and build robust trading systems. This guide covers techniques for multi-strategy portfolio management in backtrader.

## Quick Start

### Basic Multi-Strategy Setup

```python
import backtrader as bt

cerebro = bt.Cerebro()

# Add multiple strategies

cerebro.addstrategy(MomentumStrategy, period=20)
cerebro.addstrategy(MeanReversionStrategy, period=10)
cerebro.addstrategy(BreakoutStrategy, period=50)

# Run - all strategies trade with shared broker

results = cerebro.run()

# Each strategy result is returned separately

for i, strat in enumerate(results):
    print(f"Strategy {i}: Final Value {strat.broker.getvalue()}")

```bash

## Strategy Portfolio Management

### Equal Weight Allocation

```python
class EqualWeightStrategy(bt.Strategy):
    """Base class for equal-weight multi-strategy portfolio."""

    params = (
        ('weight', 0.33),  # Equal allocation for 3 strategies
        ('max_position', 0.95),
    )

    def __init__(self):
        self.order = None
        self.target_value = self.broker.getvalue() *self.p.weight

    def next(self):
        current_value = self.broker.getvalue()*self.p.weight

        if self.signal() and not self.position:

# Buy with allocated capital
            size = int(current_value / self.data.close[0])
            self.buy(size=size)
        elif not self.signal() and self.position:
            self.close()

    def signal(self):

# Override in subclass
        return False

```bash

### Risk Parity Allocation

```python
class RiskParityStrategy(bt.Strategy):
    """Allocate capital based on strategy volatility."""

    params = (
        ('lookback', 20),
        ('target_risk', 0.02),  # 2% daily risk
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.lookback)
        self.volatility = self.atr / self.data.close

    def get_position_size(self):
        """Calculate position size based on volatility."""
        risk_per_share = self.atr[0]
        account_risk = self.broker.getvalue()*self.p.target_risk
        return int(account_risk / risk_per_share) if risk_per_share > 0 else 0

```bash

## Resource Allocation

### Capital Allocation Strategies

```python
class CapitalAllocator(bt.Strategy):
    """Dynamically allocate capital between strategies."""

    params = (
        ('rebalance_freq', 20),  # Rebalance every 20 bars
        ('min_allocation', 0.1),  # Minimum 10% allocation
    )

    def __init__(self):
        self.strategies = []
        self.allocations = []
        self.last_rebalance = 0

    def add_strategy(self, strategy, allocation):
        """Add a strategy with its target allocation."""
        self.strategies.append(strategy)
        self.allocations.append(allocation)

    def next(self):
        if len(self.data) - self.last_rebalance >= self.p.rebalance_freq:
            self.rebalance()
            self.last_rebalance = len(self.data)

    def rebalance(self):
        """Rebalance capital based on performance."""

# Implementation depends on allocation method
        pass

```bash

### Commission Splitting

```python
class CommissionSplitter(bt.CommissionInfo):
    """Split commissions proportionally among strategies."""

    params = (('strategies', []),)

    def getcommission(self, size, price):
        comm = super().getcommission(size, price)

# Split commission if multiple strategies involved
        return comm / len(self.p.strategies) if self.p.strategies else comm

```bash

## Results Aggregation

### Portfolio-Level Analysis

```python
class PortfolioAnalyzer(bt.Analyzer):
    """Analyze combined performance of all strategies."""

    def __init__(self):
        self.returns = []
        self.drawdowns = []

    def next(self):
        total_value = self.strategy.broker.getvalue()
        self.returns.append(total_value)

    def get_analysis(self):
        import numpy as np

        returns_array = np.array(self.returns)
        cumulative_returns = (returns_array / returns_array[0]) - 1

# Calculate running maximum
        running_max = np.maximum.accumulate(returns_array)
        drawdowns = (returns_array - running_max) / running_max

        return {
            'total_return': cumulative_returns[-1],
            'max_drawdown': drawdowns.min(),
            'final_value': returns_array[-1],
            'returns_series': self.returns,
        }

# Usage

cerebro.addanalyzer(PortfolioAnalyzer, _name='portfolio')
results = cerebro.run()
portfolio_analysis = results[0].analyzers.portfolio.get_analysis()

```bash

### Multi-Strategy Comparison

```python
def compare_strategies(strategies, data_path):
    """Run and compare multiple strategies."""
    results_summary = []

    for strat_class in strategies:
        cerebro = bt.Cerebro()
        cerebro.adddata(bt.feeds.CSVData(dataname=data_path))
        cerebro.addstrategy(strat_class)
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

        result = cerebro.run()[0]

        summary = {
            'strategy': strat_class.__name__,
            'sharpe': result.analyzers.sharpe.get_analysis().get('sharperatio'),
            'max_dd': result.analyzers.drawdown.get_analysis()['max']['drawdown'],
            'return': result.analyzers.returns.get_analysis()['rnorm'],
        }
        results_summary.append(summary)

# Print comparison table
    print(f"{'Strategy':<20} {'Sharpe':>10} {'Max DD':>10} {'Return':>10}")
    print("-"* 52)
    for s in results_summary:
        print(f"{s['strategy']:<20} {s['sharpe']:>10.2f} {s['max_dd']:>10.2f} {s['return']:>10.2%}")

    return results_summary

```bash

## Strategy Correlation Analysis

### Calculate Correlations

```python
def calculate_strategy_correlations(strategies, data_path):
    """Calculate return correlations between strategies."""
    from scipy.stats import pearsonr
    import pandas as pd

# Collect returns from each strategy
    all_returns = {}

    for strat_class in strategies:
        cerebro = bt.Cerebro()
        cerebro.adddata(bt.feeds.CSVData(dataname=data_path))
        cerebro.addstrategy(strat_class)
        cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='returns')

        result = cerebro.run()[0]
        returns_dict = result.analyzers.returns.get_analysis()
        all_returns[strat_class.__name__] = pd.Series(returns_dict)

# Calculate correlation matrix
    returns_df = pd.DataFrame(all_returns)
    correlation_matrix = returns_df.corr()

    return correlation_matrix

# Usage

strategies = [MomentumStrategy, MeanReversionStrategy, BreakoutStrategy]
corr_matrix = calculate_strategy_correlations(strategies, 'data.csv')
print(corr_matrix)

```bash

### Low-Correlation Portfolio

```python
class LowCorrelationSelector(bt.Strategy):
    """Select strategies with low correlation to each other."""

    params = (
        ('max_correlation', 0.7),
        ('min_strategies', 2),
    )

    def __init__(self):
        self.selected_strategies = []
        self.returns_history = {s: [] for s in self.p.strategies}

    def calculate_correlation(self, returns1, returns2):
        """Calculate correlation between two return series."""
        import numpy as np
        return np.corrcoef(returns1, returns2)[0, 1]

    def select_strategies(self):
        """Select strategies with correlations below threshold."""
        selected = [self.p.strategies[0]]  # Start with first strategy

        for candidate in self.p.strategies[1:]:

# Check correlation with all selected strategies
            correlations = [
                self.calculate_correlation(
                    self.returns_history[candidate],
                    self.returns_history[selected_strat]
                )
                for selected_strat in selected
            ]

            if all(c < self.p.max_correlation for c in correlations):
                selected.append(candidate)

        return selected[:self.p.max_strategies]

```bash

## Parallel Execution

### Multi-Process Optimization

```python
from multiprocessing import Pool
import itertools

def run_strategy_backtest(params):
    """Run a single backtest with given parameters."""
    strat_class, data_path, strat_params = params

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.CSVData(dataname=data_path))
    cerebro.addstrategy(strat_class, **strat_params)

    result = cerebro.run()[0]
    return {
        'params': strat_params,
        'final_value': cerebro.broker.getvalue(),
        'sharpe': result.analyzers.sharpe.get_analysis().get('sharperatio', 0),
    }

def parallel_optimize(strat_class, data_path, param_grid, n_workers=4):
    """Optimize strategy parameters in parallel."""

# Generate all parameter combinations
    param_combinations = list(itertools.product(*param_grid.values()))
    param_dicts = [dict(zip(param_grid.keys(), combo)) for combo in param_combinations]

# Create parameter tuples for each worker
    params_list = [(strat_class, data_path, p) for p in param_dicts]

# Run in parallel
    with Pool(n_workers) as pool:
        results = pool.map(run_strategy_backtest, params_list)

# Sort by Sharpe ratio
    results.sort(key=lambda x: x['sharpe'], reverse=True)
    return results

```bash

### Independent Strategy Execution

```python
def run_strategies_independent(strategies_config):
    """Run strategies independently and combine results."""
    import concurrent.futures

    def run_single(config):
        cerebro = bt.Cerebro()
        cerebro.adddata(bt.feeds.CSVData(dataname=config['data']))
        cerebro.addstrategy(config['strategy'], **config.get('params', {}))
        cerebro.broker.setcash(config.get('cash', 100000))

        result = cerebro.run()[0]
        return {
            'name': config['name'],
            'return': cerebro.broker.getvalue() / config.get('cash', 100000) - 1,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(run_single, config) for config in strategies_config]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    return results

```bash

## Risk Management Across Strategies

### Portfolio-Level Stop Loss

```python
class PortfolioStopLoss(bt.Strategy):
    """Implement portfolio-level stop loss across all strategies."""

    params = (
        ('max_drawdown', 0.15),  # 15% max drawdown
        ('stop_trading', False),
    )

    def __init__(self):
        self.peak_value = self.broker.getvalue()
        self.trading_stopped = False

    def next(self):
        current_value = self.broker.getvalue()

# Update peak
        if current_value > self.peak_value:
            self.peak_value = current_value

# Calculate drawdown
        drawdown = (self.peak_value - current_value) / self.peak_value

# Stop trading if max drawdown exceeded
        if drawdown >= self.p.max_drawdown and not self.trading_stopped:
            self.trading_stopped = True
            self.close()  # Close all positions

        if self.trading_stopped:
            return  # Skip all trading logic

# Normal strategy logic here
        self.execute_strategy()

    def execute_strategy(self):
        """Override in subclass."""
        pass

```bash

### Position-Level Risk Controls

```python
class MultiStrategyPositionSizer(bt.Sizer):
    """Size positions considering all strategy positions."""

    params = (
        ('max_total_exposure', 0.95),  # Max 95% of portfolio
        ('max_single_position', 0.20),  # Max 20% per position
    )

    def _getsizing(self, comminfo, cash, data, isbuy):
        total_value = self.strategy.broker.getvalue()
        current_exposure = abs(self.strategy.broker.getvalue() -
                               self.strategy.broker.get_cash()) / total_value

# Calculate available capacity
        available = self.p.max_total_exposure - current_exposure
        if available <= 0:
            return 0  # No capacity for new position

# Calculate position size
        max_size = (total_value * min(available, self.p.max_single_position))
        price = data.close[0]
        return int(max_size / price) if price > 0 else 0

```bash

## Complete Example

### Multi-Strategy Portfolio System

```python
import backtrader as bt
import pandas as pd
from datetime import datetime

# Strategy 1: Momentum

class MomentumStrategy(bt.Strategy):
    """Momentum-based strategy using RSI."""

    params = (('rsi_period', 14), ('oversold', 30), ('overbought', 70))

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.signal = 0  # 1=buy, -1=sell, 0=hold

    def next(self):
        if self.rsi[0] < self.p.oversold and not self.position:
            self.buy(size=self.sizer.get_size(self))
            self.signal = 1
        elif self.rsi[0] > self.p.overbought and self.position:
            self.close()
            self.signal = -1
        else:
            self.signal = 0


# Strategy 2: Mean Reversion

class MeanReversionStrategy(bt.Strategy):
    """Mean reversion using Bollinger Bands."""

    params = (('period', 20), ('devfactor', 2.0))

    def __init__(self):
        self.boll = bt.indicators.BollingerBands(
            self.data.close,
            period=self.p.period,
            devfactor=self.p.devfactor
        )
        self.signal = 0

    def next(self):
        if self.data.close[0] < self.boll.lines.bot[0] and not self.position:
            self.buy(size=self.sizer.get_size(self))
            self.signal = 1
        elif self.data.close[0] > self.boll.lines.top[0] and self.position:
            self.close()
            self.signal = -1
        else:
            self.signal = 0


# Strategy 3: Trend Following

class TrendFollowingStrategy(bt.Strategy):
    """Trend following using moving average crossover."""

    params = (('fast_period', 10), ('slow_period', 30))

    def __init__(self):
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)
        self.signal = 0

    def next(self):
        if self.crossover[0] > 0 and not self.position:
            self.buy(size=self.sizer.get_size(self))
            self.signal = 1
        elif self.crossover[0] < 0 and self.position:
            self.close()
            self.signal = -1
        else:
            self.signal = 0


# Portfolio Manager

class MultiStrategyPortfolio(bt.Strategy):
    """Portfolio manager combining multiple strategies."""

    params = (
        ('strategies', []),
        ('weights', None),  # None = equal weight
        ('rebalance_freq', 5),
    )

    def __init__(self):

# Store strategy instances
        self.strategy_instances = []
        for strat_params in self.p.strategies:
            strat_class = strat_params['class']
            strat_instance = strat_class(**strat_params.get('params', {}))
            self.strategy_instances.append(strat_instance)

# Set weights
        if self.p.weights is None:
            self.weights = [1.0 / len(self.strategy_instances)] *len(self.strategy_instances)
        else:
            self.weights = self.p.weights

# Track allocations
        self.allocations = [0.0]*len(self.strategy_instances)
        self.last_rebalance = 0

    def next(self):

# Get signals from all strategies
        signals = []
        for i, strat in enumerate(self.strategy_instances):

# Execute strategy logic
            strat.next()
            signals.append(strat.signal)

# Rebalance if needed
        if len(self.data) - self.last_rebalance >= self.p.rebalance_freq:
            self.rebalance()
            self.last_rebalance = len(self.data)

    def rebalance(self):
        """Rebalance portfolio based on target weights."""
        total_value = self.broker.getvalue()

        for i, weight in enumerate(self.weights):
            target_value = total_value*weight
            current_value = self.get_strategy_value(i)

            if current_value < target_value*0.95:  # Underweight

# Buy to reach target
                pass
            elif current_value > target_value*1.05:  # Overweight

# Sell to reach target
                pass

    def get_strategy_value(self, index):
        """Get current value of strategy at index."""

# Implementation depends on tracking method
        return self.broker.getvalue() / len(self.strategy_instances)


# Custom Position Sizer

class EqualWeightSizer(bt.Sizer):
    """Equal weight position sizer for multi-strategy portfolio."""

    params = (('num_strategies', 3), ('target_weight', 0.33))

    def _getsizing(self, comminfo, cash, data, isbuy):
        total_value = self.strategy.broker.getvalue()
        target_value = total_value*self.p.target_weight
        return int(target_value / data.close[0]) if data.close[0] > 0 else 0


# Run the portfolio

def run_multi_strategy_portfolio(data_path):
    """Run multi-strategy portfolio backtest."""

    cerebro = bt.Cerebro()

# Add data
    data = bt.feeds.CSVData(dataname=data_path)
    cerebro.adddata(data)

# Add portfolio strategy
    strategies_config = [
        {'class': MomentumStrategy, 'params': {'rsi_period': 14}},
        {'class': MeanReversionStrategy, 'params': {'period': 20}},
        {'class': TrendFollowingStrategy, 'params': {'fast_period': 10, 'slow_period': 30}},
    ]

    cerebro.addstrategy(
        MultiStrategyPortfolio,
        strategies=strategies_config,
        weights=[0.3, 0.3, 0.4],  # Custom weights
    )

# Set broker
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)

# Add sizer
    cerebro.addsizer(EqualWeightSizer, num_strategies=3, target_weight=0.33)

# Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

# Run
    results = cerebro.run()
    strat = results[0]

# Print results
    print("\n" + "="*50)
    print("Multi-Strategy Portfolio Results")
    print("="*50)
    print(f"Final Value: {cerebro.broker.getvalue():.2f}")
    print(f"Sharpe Ratio: {strat.analyzers.sharpe.get_analysis().get('sharperatio', 'N/A')}")
    print(f"Max Drawdown: {strat.analyzers.drawdown.get_analysis()['max']['drawdown']:.2f}%")
    print(f"Annual Return: {strat.analyzers.returns.get_analysis().get('rnorm', 0):.2%}")
    print("="* 50)

    return results


if __name__ == '__main__':

# Run the portfolio
    results = run_multi_strategy_portfolio('data.csv')

```bash

## Best Practices

### Strategy Selection

1. **Diversification**: Combine strategies with different market conditions
2. **Low Correlation**: Select strategies that don't move together
3. **Complementary Signals**: Use strategies that confirm each other

### Risk Management

1. **Portfolio-Level Controls**: Implement maximum drawdown limits
2. **Position Sizing**: Use consistent sizing across strategies
3. **Capital Allocation**: Don't over-allocate to similar strategies

### Performance Monitoring

1. **Individual Metrics**: Track each strategy separately
2. **Combined Metrics**: Monitor portfolio-level performance
3. **Attribution Analysis**: Understand which strategies contribute most

## Next Steps

- [Performance Optimization](performance-optimization.md) - Speed up your backtests
- [TS Mode Guide](ts-mode.md) - Time series optimization
- [CS Mode Guide](cs-mode.md) - Cross-section mode for portfolios
