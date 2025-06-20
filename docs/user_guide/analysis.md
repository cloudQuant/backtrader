# 交易分析指南

本指南介绍如何使用 Backtrader 分析交易策略的性能和风险。

## 性能分析器

### 1. 基础收益分析

```python
# 添加基础分析器
cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

# 运行回测
results = cerebro.run()
strat = results[0]

# 获取分析结果
print(f'总收益率: {strat.analyzers.returns.get_analysis()["rtot"]:.2%}')
print(f'年化收益率: {strat.analyzers.returns.get_analysis()["rnorm"]:.2%}')
print(f'夏普比率: {strat.analyzers.sharpe.get_analysis()["sharperatio"]:.2f}')
print(f'最大回撤: {strat.analyzers.drawdown.get_analysis()["max"]["drawdown"]:.2%}')
```

### 2. 交易统计

```python
# 添加交易分析器
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

# 分析交易结果
trade_analysis = strat.analyzers.trades.get_analysis()

# 打印交易统计
print(f'总交易次数: {trade_analysis.total.total}')
print(f'盈利交易: {trade_analysis.won.total}')
print(f'亏损交易: {trade_analysis.lost.total}')
print(f'胜率: {trade_analysis.won.total/trade_analysis.total.total:.2%}')
print(f'平均盈利: {trade_analysis.won.pnl.average:.2f}')
print(f'平均亏损: {trade_analysis.lost.pnl.average:.2f}')
```

### 3. 时间序列分析

```python
# 添加时序分析器
cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='time_return')
cerebro.addanalyzer(bt.analyzers.TimeDrawDown, _name='time_drawdown')

# 分析时间序列表现
time_returns = pd.Series(strat.analyzers.time_return.get_analysis())
time_drawdown = pd.Series(strat.analyzers.time_drawdown.get_analysis())

# 绘制收益曲线
plt.figure(figsize=(12, 6))
time_returns.cumsum().plot()
plt.title('累计收益率')
plt.show()
```

## 自定义分析器

### 1. 基本分析器

```python
class CustomAnalyzer(bt.Analyzer):
    def __init__(self):
        self.trades = []
        self.returns = []
        
    def notify_trade(self, trade):
        if trade.isclosed:
            self.trades.append({
                'size': trade.size,
                'price': trade.price,
                'pnl': trade.pnl,
                'commission': trade.commission
            })
            
    def notify_order(self, order):
        if order.status == order.Completed:
            self.returns.append(self.strategy.broker.get_value())
            
    def get_analysis(self):
        return {
            'trades': self.trades,
            'returns': self.returns
        }
```

### 2. 风险分析器

```python
class RiskAnalyzer(bt.Analyzer):
    params = (
        ('risk_free_rate', 0.02),  # 无风险利率
        ('target_return', 0.10),   # 目标收益率
    )
    
    def start(self):
        self.returns = []
        self.drawdowns = []
        
    def next(self):
        # 计算每日收益率
        ret = (self.strategy.broker.get_value() / 
               self.strategy.broker.startingcash - 1)
        self.returns.append(ret)
        
        # 计算回撤
        high = max(self.returns)
        dd = (high - ret) / (1 + high)
        self.drawdowns.append(dd)
        
    def get_analysis(self):
        returns = np.array(self.returns)
        
        return {
            'volatility': np.std(returns) * np.sqrt(252),
            'sortino': self._sortino_ratio(returns),
            'var_95': np.percentile(returns, 5),
            'max_dd': max(self.drawdowns)
        }
        
    def _sortino_ratio(self, returns):
        # 计算 Sortino 比率
        excess_returns = returns - self.p.risk_free_rate/252
        downside_returns = excess_returns[excess_returns < 0]
        
        if len(downside_returns) == 0:
            return float('inf')
            
        downside_std = np.std(downside_returns) * np.sqrt(252)
        return (np.mean(excess_returns) * 252) / downside_std
```

## 性能报告

### 1. 生成HTML报告

```python
class HTMLReporter:
    def __init__(self, strategy_results):
        self.results = strategy_results
        
    def create_report(self, filename='report.html'):
        # 生成报告内容
        html = f"""
        <html>
        <head>
            <title>策略分析报告</title>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .metric {{ margin: 20px; padding: 10px; }}
                .chart {{ width: 100%; height: 400px; }}
            </style>
        </head>
        <body>
            <h1>策略分析报告</h1>
            {self._performance_metrics()}
            {self._trade_statistics()}
            {self._charts()}
        </body>
        </html>
        """
        
        # 保存报告
        with open(filename, 'w') as f:
            f.write(html)
            
    def _performance_metrics(self):
        # 生成性能指标HTML
        pass
        
    def _trade_statistics(self):
        # 生成交易统计HTML
        pass
        
    def _charts(self):
        # 生成图表HTML
        pass
```

### 2. 导出Excel报告

```python
class ExcelReporter:
    def __init__(self, strategy_results):
        self.results = strategy_results
        
    def create_report(self, filename='report.xlsx'):
        with pd.ExcelWriter(filename) as writer:
            # 写入性能指标
            self._write_performance(writer)
            # 写入交易记录
            self._write_trades(writer)
            # 写入持仓分析
            self._write_positions(writer)
            
    def _write_performance(self, writer):
        # 性能指标
        metrics = pd.DataFrame({
            'Metric': ['总收益率', '年化收益率', '夏普比率', '最大回撤'],
            'Value': [
                self.results.analyzers.returns.get_analysis()['rtot'],
                self.results.analyzers.returns.get_analysis()['rnorm'],
                self.results.analyzers.sharpe.get_analysis()['sharperatio'],
                self.results.analyzers.drawdown.get_analysis()['max']['drawdown']
            ]
        })
        metrics.to_excel(writer, sheet_name='Performance', index=False)
```

## 可视化分析

### 1. 收益分析图表

```python
def plot_returns(strategy_results):
    # 获取收益数据
    returns = pd.Series(
        strategy_results.analyzers.time_return.get_analysis()
    )
    
    # 创建图表
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    # 累计收益曲线
    cumreturns = (returns + 1).cumprod()
    ax1.plot(cumreturns.index, cumreturns.values)
    ax1.set_title('累计收益')
    ax1.grid(True)
    
    # 收益分布
    returns.hist(ax=ax2, bins=50)
    ax2.set_title('收益分布')
    ax2.grid(True)
    
    plt.tight_layout()
    plt.show()
```

### 2. 交易分析图表

```python
def plot_trades(strategy_results):
    trades = strategy_results.analyzers.trades.get_analysis()
    
    # 创建图表
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
    
    # 盈亏分布
    pnls = [t['pnl'] for t in trades['trades']]
    ax1.hist(pnls, bins=20)
    ax1.set_title('交易盈亏分布')
    
    # 持仓时间分布
    durations = [t['duration'] for t in trades['trades']]
    ax2.hist(durations, bins=20)
    ax2.set_title('持仓时间分布')
    
    plt.tight_layout()
    plt.show()
```

## 风险管理

### 1. 风险指标计算

```python
def calculate_risk_metrics(returns):
    """计算风险指标"""
    daily_returns = pd.Series(returns)
    
    metrics = {
        'volatility': daily_returns.std() * np.sqrt(252),
        'sharpe': (daily_returns.mean() / daily_returns.std()) * np.sqrt(252),
        'sortino': calculate_sortino_ratio(daily_returns),
        'max_drawdown': calculate_max_drawdown(daily_returns),
        'var_95': daily_returns.quantile(0.05),
        'cvar_95': daily_returns[daily_returns <= daily_returns.quantile(0.05)].mean()
    }
    
    return metrics

def calculate_sortino_ratio(returns, risk_free_rate=0.02):
    """计算 Sortino 比率"""
    excess_returns = returns - risk_free_rate/252
    downside_returns = excess_returns[excess_returns < 0]
    
    if len(downside_returns) == 0:
        return float('inf')
        
    downside_std = downside_returns.std() * np.sqrt(252)
    return (excess_returns.mean() * 252) / downside_std

def calculate_max_drawdown(returns):
    """计算最大回撤"""
    cum_returns = (1 + returns).cumprod()
    running_max = cum_returns.cummax()
    drawdown = (cum_returns - running_max) / running_max
    return drawdown.min()
```

### 2. 风险监控

```python
class RiskMonitor(bt.Analyzer):
    params = (
        ('max_drawdown', 0.20),        # 最大回撤限制
        ('daily_var_limit', 0.02),     # 日VaR限制
        ('volatility_limit', 0.25),    # 年化波动率限制
    )
    
    def __init__(self):
        self.returns = []
        self.drawdowns = []
        self.alerts = []
        
    def next(self):
        # 计算当前回撤
        ret = (self.strategy.broker.get_value() / 
               self.strategy.broker.startingcash - 1)
        self.returns.append(ret)
        
        # 计算风险指标
        if len(self.returns) > 30:  # 需要足够的数据
            metrics = self._calculate_metrics()
            
            # 检查风险限制
            self._check_limits(metrics)
            
    def _calculate_metrics(self):
        returns = pd.Series(self.returns)
        return {
            'drawdown': calculate_max_drawdown(returns),
            'volatility': returns.std() * np.sqrt(252),
            'var': returns.quantile(0.05)
        }
        
    def _check_limits(self, metrics):
        if metrics['drawdown'] < -self.p.max_drawdown:
            self.alerts.append(f'超过最大回撤限制: {metrics["drawdown"]:.2%}')
            
        if metrics['volatility'] > self.p.volatility_limit:
            self.alerts.append(f'超过波动率限制: {metrics["volatility"]:.2%}')
            
        if metrics['var'] < -self.p.daily_var_limit:
            self.alerts.append(f'超过VaR限制: {metrics["var"]:.2%}')
```

## 最佳实践

### 1. 性能评估

- 使用多个时间周期评估策略
- 考虑交易成本和滑点
- 进行样本外测试
- 比较基准收益

### 2. 风险控制

- 设置止损和止盈
- 监控持仓集中度
- 控制交易频率
- 设置风险预警

### 3. 报告生成

- 定期生成分析报告
- 包含关键指标摘要
- 添加图表可视化
- 保存详细交易记录

## 下一步

- 学习[策略优化](./optimization.md)
- 了解[风险管理](../advanced/risk_mgmt.md)
- 探索[实盘交易](../advanced/live_trading.md)
- 研究[机器学习](../advanced/machine_learning.md)
