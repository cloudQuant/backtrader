- --

title: 多策略回测
description: 在 backtrader 中运行和管理多个策略的指南

- --

# 多策略回测

同时运行多个策略可以分散交易方法、比较绩效并构建稳健的交易系统。本指南介绍在 backtrader 中进行多策略组合管理的技术。

## 快速开始

### 基础多策略设置

```python
import backtrader as bt

cerebro = bt.Cerebro()

# 添加多个策略

cerebro.addstrategy(MomentumStrategy, period=20)
cerebro.addstrategy(MeanReversionStrategy, period=10)
cerebro.addstrategy(BreakoutStrategy, period=50)

# 运行 - 所有策略共享同一个经纪商

results = cerebro.run()

# 每个策略结果单独返回

for i, strat in enumerate(results):
    print(f"策略 {i}: 最终价值 {strat.broker.getvalue()}")

```bash

## 策略组合管理

### 等权重分配

```python
class EqualWeightStrategy(bt.Strategy):
    """等权重多策略组合的基础类。"""

    params = (
        ('weight', 0.33),  # 3 个策略等权重分配
        ('max_position', 0.95),
    )

    def __init__(self):
        self.order = None
        self.target_value = self.broker.getvalue() *self.p.weight

    def next(self):
        current_value = self.broker.getvalue()*self.p.weight

        if self.signal() and not self.position:

# 使用分配的资金买入
            size = int(current_value / self.data.close[0])
            self.buy(size=size)
        elif not self.signal() and self.position:
            self.close()

    def signal(self):

# 在子类中重写
        return False

```bash

### 风险平价分配

```python
class RiskParityStrategy(bt.Strategy):
    """根据策略波动率分配资金。"""

    params = (
        ('lookback', 20),
        ('target_risk', 0.02),  # 2% 日风险
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.lookback)
        self.volatility = self.atr / self.data.close

    def get_position_size(self):
        """根据波动率计算持仓大小。"""
        risk_per_share = self.atr[0]
        account_risk = self.broker.getvalue()*self.p.target_risk
        return int(account_risk / risk_per_share) if risk_per_share > 0 else 0

```bash

## 资源分配

### 资金分配策略

```python
class CapitalAllocator(bt.Strategy):
    """在策略之间动态分配资金。"""

    params = (
        ('rebalance_freq', 20),  # 每 20 根 K 线再平衡
        ('min_allocation', 0.1),  # 最小 10%分配
    )

    def __init__(self):
        self.strategies = []
        self.allocations = []
        self.last_rebalance = 0

    def add_strategy(self, strategy, allocation):
        """添加策略及其目标分配比例。"""
        self.strategies.append(strategy)
        self.allocations.append(allocation)

    def next(self):
        if len(self.data) - self.last_rebalance >= self.p.rebalance_freq:
            self.rebalance()
            self.last_rebalance = len(self.data)

    def rebalance(self):
        """根据绩效再平衡资金。"""

# 实现取决于分配方法
        pass

```bash

### 佣金分摊

```python
class CommissionSplitter(bt.CommissionInfo):
    """在多个策略之间按比例分摊佣金。"""

    params = (('strategies', []),)

    def getcommission(self, size, price):
        comm = super().getcommission(size, price)

# 如果涉及多个策略，分摊佣金
        return comm / len(self.p.strategies) if self.p.strategies else comm

```bash

## 结果聚合

### 组合层面分析

```python
class PortfolioAnalyzer(bt.Analyzer):
    """分析所有策略的合并绩效。"""

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

# 计算滚动最大值
        running_max = np.maximum.accumulate(returns_array)
        drawdowns = (returns_array - running_max) / running_max

        return {
            'total_return': cumulative_returns[-1],
            'max_drawdown': drawdowns.min(),
            'final_value': returns_array[-1],
            'returns_series': self.returns,
        }

# 使用方法

cerebro.addanalyzer(PortfolioAnalyzer, _name='portfolio')
results = cerebro.run()
portfolio_analysis = results[0].analyzers.portfolio.get_analysis()

```bash

### 多策略比较

```python
def compare_strategies(strategies, data_path):
    """运行并比较多个策略。"""
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

# 打印比较表格
    print(f"{'策略':<20} {'夏普':>10} {'最大回撤':>10} {'收益':>10}")
    print("-"* 52)
    for s in results_summary:
        print(f"{s['strategy']:<20} {s['sharpe']:>10.2f} {s['max_dd']:>10.2f} {s['return']:>10.2%}")

    return results_summary

```bash

## 策略相关性分析

### 计算相关性

```python
def calculate_strategy_correlations(strategies, data_path):
    """计算策略之间的收益率相关性。"""
    from scipy.stats import pearsonr
    import pandas as pd

# 收集每个策略的收益
    all_returns = {}

    for strat_class in strategies:
        cerebro = bt.Cerebro()
        cerebro.adddata(bt.feeds.CSVData(dataname=data_path))
        cerebro.addstrategy(strat_class)
        cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='returns')

        result = cerebro.run()[0]
        returns_dict = result.analyzers.returns.get_analysis()
        all_returns[strat_class.__name__] = pd.Series(returns_dict)

# 计算相关矩阵
    returns_df = pd.DataFrame(all_returns)
    correlation_matrix = returns_df.corr()

    return correlation_matrix

# 使用方法

strategies = [MomentumStrategy, MeanReversionStrategy, BreakoutStrategy]
corr_matrix = calculate_strategy_correlations(strategies, 'data.csv')
print(corr_matrix)

```bash

### 低相关性组合

```python
class LowCorrelationSelector(bt.Strategy):
    """选择彼此相关性低的策略。"""

    params = (
        ('max_correlation', 0.7),
        ('min_strategies', 2),
    )

    def __init__(self):
        self.selected_strategies = []
        self.returns_history = {s: [] for s in self.p.strategies}

    def calculate_correlation(self, returns1, returns2):
        """计算两个收益率序列之间的相关性。"""
        import numpy as np
        return np.corrcoef(returns1, returns2)[0, 1]

    def select_strategies(self):
        """选择相关性低于阈值的策略。"""
        selected = [self.p.strategies[0]]  # 从第一个策略开始

        for candidate in self.p.strategies[1:]:

# 检查与所有已选策略的相关性
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

## 并行执行

### 多进程优化

```python
from multiprocessing import Pool
import itertools

def run_strategy_backtest(params):
    """使用给定参数运行单个回测。"""
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
    """并行优化策略参数。"""

# 生成所有参数组合
    param_combinations = list(itertools.product(*param_grid.values()))
    param_dicts = [dict(zip(param_grid.keys(), combo)) for combo in param_combinations]

# 为每个 worker 创建参数元组
    params_list = [(strat_class, data_path, p) for p in param_dicts]

# 并行运行
    with Pool(n_workers) as pool:
        results = pool.map(run_strategy_backtest, params_list)

# 按夏普比率排序
    results.sort(key=lambda x: x['sharpe'], reverse=True)
    return results

```bash

### 独立策略执行

```python
def run_strategies_independent(strategies_config):
    """独立运行策略并合并结果。"""
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

## 跨策略风险管理

### 组合层面止损

```python
class PortfolioStopLoss(bt.Strategy):
    """在所有策略中实现组合层面止损。"""

    params = (
        ('max_drawdown', 0.15),  # 15% 最大回撤
        ('stop_trading', False),
    )

    def __init__(self):
        self.peak_value = self.broker.getvalue()
        self.trading_stopped = False

    def next(self):
        current_value = self.broker.getvalue()

# 更新峰值
        if current_value > self.peak_value:
            self.peak_value = current_value

# 计算回撤
        drawdown = (self.peak_value - current_value) / self.peak_value

# 如果超过最大回撤则停止交易
        if drawdown >= self.p.max_drawdown and not self.trading_stopped:
            self.trading_stopped = True
            self.close()  # 平掉所有仓位

        if self.trading_stopped:
            return  # 跳过所有交易逻辑

# 正常策略逻辑
        self.execute_strategy()

    def execute_strategy(self):
        """在子类中重写。"""
        pass

```bash

### 持仓层面风险控制

```python
class MultiStrategyPositionSizer(bt.Sizer):
    """考虑所有策略持仓的仓位管理。"""

    params = (
        ('max_total_exposure', 0.95),  # 最大 95%组合敞口
        ('max_single_position', 0.20),  # 最大 20%单仓位
    )

    def _getsizing(self, comminfo, cash, data, isbuy):
        total_value = self.strategy.broker.getvalue()
        current_exposure = abs(self.strategy.broker.getvalue() -
                               self.strategy.broker.get_cash()) / total_value

# 计算可用容量
        available = self.p.max_total_exposure - current_exposure
        if available <= 0:
            return 0  # 新仓位无容量

# 计算持仓大小
        max_size = (total_value * min(available, self.p.max_single_position))
        price = data.close[0]
        return int(max_size / price) if price > 0 else 0

```bash

## 完整示例

### 多策略组合系统

```python
import backtrader as bt
import pandas as pd
from datetime import datetime

# 策略 1: 动量策略

class MomentumStrategy(bt.Strategy):
    """基于 RSI 的动量策略。"""

    params = (('rsi_period', 14), ('oversold', 30), ('overbought', 70))

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.signal = 0  # 1=买入, -1=卖出, 0=持有

    def next(self):
        if self.rsi[0] < self.p.oversold and not self.position:
            self.buy(size=self.sizer.get_size(self))
            self.signal = 1
        elif self.rsi[0] > self.p.overbought and self.position:
            self.close()
            self.signal = -1
        else:
            self.signal = 0


# 策略 2: 均值回归策略

class MeanReversionStrategy(bt.Strategy):
    """使用布林带的均值回归策略。"""

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


# 策略 3: 趋势跟踪策略

class TrendFollowingStrategy(bt.Strategy):
    """使用均线交叉的趋势跟踪策略。"""

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


# 组合管理器

class MultiStrategyPortfolio(bt.Strategy):
    """组合多个策略的组合管理器。"""

    params = (
        ('strategies', []),
        ('weights', None),  # None = 等权重
        ('rebalance_freq', 5),
    )

    def __init__(self):

# 存储策略实例
        self.strategy_instances = []
        for strat_params in self.p.strategies:
            strat_class = strat_params['class']
            strat_instance = strat_class(**strat_params.get('params', {}))
            self.strategy_instances.append(strat_instance)

# 设置权重
        if self.p.weights is None:
            self.weights = [1.0 / len(self.strategy_instances)] *len(self.strategy_instances)
        else:
            self.weights = self.p.weights

# 跟踪分配
        self.allocations = [0.0]*len(self.strategy_instances)
        self.last_rebalance = 0

    def next(self):

# 获取所有策略的信号
        signals = []
        for i, strat in enumerate(self.strategy_instances):

# 执行策略逻辑
            strat.next()
            signals.append(strat.signal)

# 如需则再平衡
        if len(self.data) - self.last_rebalance >= self.p.rebalance_freq:
            self.rebalance()
            self.last_rebalance = len(self.data)

    def rebalance(self):
        """根据目标权重再平衡组合。"""
        total_value = self.broker.getvalue()

        for i, weight in enumerate(self.weights):
            target_value = total_value*weight
            current_value = self.get_strategy_value(i)

            if current_value < target_value*0.95:  # 低配

# 买入达到目标
                pass
            elif current_value > target_value*1.05:  # 超配

# 卖出达到目标
                pass

    def get_strategy_value(self, index):
        """获取指定索引策略的当前价值。"""

# 实现取决于跟踪方法
        return self.broker.getvalue() / len(self.strategy_instances)


# 自定义仓位管理

class EqualWeightSizer(bt.Sizer):
    """多策略组合的等权重仓位管理。"""

    params = (('num_strategies', 3), ('target_weight', 0.33))

    def _getsizing(self, comminfo, cash, data, isbuy):
        total_value = self.strategy.broker.getvalue()
        target_value = total_value*self.p.target_weight
        return int(target_value / data.close[0]) if data.close[0] > 0 else 0


# 运行组合

def run_multi_strategy_portfolio(data_path):
    """运行多策略组合回测。"""

    cerebro = bt.Cerebro()

# 添加数据
    data = bt.feeds.CSVData(dataname=data_path)
    cerebro.adddata(data)

# 添加组合策略
    strategies_config = [
        {'class': MomentumStrategy, 'params': {'rsi_period': 14}},
        {'class': MeanReversionStrategy, 'params': {'period': 20}},
        {'class': TrendFollowingStrategy, 'params': {'fast_period': 10, 'slow_period': 30}},
    ]

    cerebro.addstrategy(
        MultiStrategyPortfolio,
        strategies=strategies_config,
        weights=[0.3, 0.3, 0.4],  # 自定义权重
    )

# 设置经纪商
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)

# 添加仓位管理
    cerebro.addsizer(EqualWeightSizer, num_strategies=3, target_weight=0.33)

# 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

# 运行
    results = cerebro.run()
    strat = results[0]

# 打印结果
    print("\n" + "="*50)
    print("多策略组合回测结果")
    print("="*50)
    print(f"最终价值: {cerebro.broker.getvalue():.2f}")
    print(f"夏普比率: {strat.analyzers.sharpe.get_analysis().get('sharperatio', 'N/A')}")
    print(f"最大回撤: {strat.analyzers.drawdown.get_analysis()['max']['drawdown']:.2f}%")
    print(f"年化收益: {strat.analyzers.returns.get_analysis().get('rnorm', 0):.2%}")
    print("="* 50)

    return results


if __name__ == '__main__':

# 运行组合
    results = run_multi_strategy_portfolio('data.csv')

```bash

## 最佳实践

### 策略选择

1. **多元化**: 组合适应不同市场条件的策略
2. **低相关性**: 选择走势不完全同步的策略
3. **互补信号**: 使用相互确认的策略

### 风险管理

1. **组合层面控制**: 实施最大回撤限制
2. **仓位管理**: 在策略间使用一致的仓位管理
3. **资金分配**: 不要过度分配给相似策略

### 绩效监控

1. **单独指标**: 分别跟踪每个策略
2. **组合指标**: 监控组合层面绩效
3. **归因分析**: 了解哪些策略贡献最大

## 相关阅读

- [性能优化](performance-optimization_zh.md) - 加速回测
- [TS 模式指南](ts-mode_zh.md) - 时间序列优化
- [CS 模式指南](cs-mode_zh.md) - 组合的横截面模式
